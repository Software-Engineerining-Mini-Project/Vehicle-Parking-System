"""System tests that follow the Test Plan (VPS-TP-01) step by step, TC-01 to TC-17.

TC-13 needs real first-time users and is run by hand, see docs/Test_Results.md.
"""
import os
import re
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

import pytest
from werkzeug.security import check_password_hash

from vps import create_app
from vps.fees import calculate_fee

ADMIN = ("admin", "Admin@123")
ATTENDANT = ("attendant", "Attend@123")


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "test.db")


@pytest.fixture
def app(db_path):
    return create_app({"TESTING": True, "DATABASE": db_path})


def logged_in(app, account=ATTENDANT):
    client = app.test_client()
    client.post("/login", data={"username": account[0], "password": account[1]})
    return client


def sql(db_path, statement, args=()):
    con = sqlite3.connect(db_path)
    try:
        rows = con.execute(statement, args).fetchall()
        con.commit()
        return rows
    finally:
        con.close()


def enter(client, plate="TN09AB1234", vehicle_type="CAR", **extra):
    return client.post("/api/parking/entry",
                       json={"plate": plate, "vehicle_type": vehicle_type, **extra})


def set_clock(db_path, minutes):
    sql(db_path, "UPDATE settings SET value = ? WHERE key = 'demo_clock_offset_min'",
        (str(minutes),))


def test_tc01_valid_entry(app, db_path):
    client = logged_in(app)
    ticket = enter(client, "TN 09 AB 1234").get_json()
    assert ticket["plate_number"] == "TN09AB1234"
    assert re.match(r"^VPS-\d{8}-\d{4}$", ticket["ticket_id"])
    assert ticket["slot_id"] == "S01"
    assert client.get(f"/tickets/{ticket['ticket_id']}/qr.svg").status_code == 200
    assert sql(db_path, "SELECT status FROM slots WHERE slot_id = 'S01'") == [("OCCUPIED",)]
    assert re.match(r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d$", ticket["entry_time"])


@pytest.mark.parametrize("plate", ["", "AB1", "ABCDEFGHIJKL", "TN-09@AB"])
def test_tc02_invalid_plates(app, db_path, plate):
    response = enter(logged_in(app), plate)
    assert response.status_code == 400
    assert "Traceback" not in response.get_data(as_text=True)
    assert sql(db_path, "SELECT COUNT(*) FROM tickets") == [(0,)]


def test_tc02_duplicate_plate(app):
    client = logged_in(app)
    enter(client, "TN09AB1234")
    assert enter(client, "tn09ab1234").status_code == 409


def test_tc03_matching_categories(app):
    client = logged_in(app)
    assert enter(client, "EV000001", "EV").get_json()["slot_id"] == "S17"
    assert enter(client, "BIKE0001", "TWO_WHEELER").get_json()["slot_id"] == "S11"
    assert enter(client, "CAR00001", accessible=True).get_json()["slot_id"] == "S15"


def test_tc04_route_exit_mode_and_reassignment(app, db_path):
    client = logged_in(app)
    sql(db_path, "UPDATE slots SET status = 'OCCUPIED' WHERE slot_id IN ('S01', 'S02')")
    body = {"plate": "TN09AB1234", "vehicle_type": "CAR"}
    route = client.post("/api/parking/preview", json=body).get_json()
    assert route["slot_id"] == "S03" and len(route["path"]) - 1 == 4
    exit_route = client.post("/api/parking/preview", json={**body, "start_from": "EXIT"}).get_json()
    assert exit_route["slot_id"] == "S10"

    sql(db_path, "UPDATE slots SET status = 'OCCUPIED' WHERE slot_id = 'S10'")
    started = time.perf_counter()
    ticket = enter(client, start_from="EXIT", target_slot="S10").get_json()
    elapsed = time.perf_counter() - started
    assert "CI" in os.environ or elapsed < 0.5
    assert ticket["slot_id"] != "S10" and ticket["reassigned_from"] == "S10"


def test_tc05_full_category_and_prediction(app, db_path):
    client = logged_in(app)
    sql(db_path, "UPDATE slots SET status = 'OCCUPIED' WHERE category = 'CAR' AND slot_id != 'S01'")
    enter(client, "CAR00001")
    entered = (datetime.now() - timedelta(minutes=86)).strftime("%Y-%m-%d %H:%M:%S")
    sql(db_path, "UPDATE tickets SET entry_time = ?", (entered,))
    for _ in range(5):
        sql(db_path, "INSERT INTO dwell_history (vehicle_type, entry_time, exit_time, duration_min)"
                     " VALUES ('CAR', '2026-01-01 09:00:00', '2026-01-01 10:30:00', 90)")
    response = enter(client, "CAR00002")
    assert response.status_code == 409
    message = response.get_json()["message"]
    assert "No Car slot available" in message and "expected in about 4 min" in message


@pytest.mark.parametrize("vehicle_type, seconds, fee", [
    ("CAR", 2 * 3600 + 600, 120), ("EV", 3601, 100),
    ("CAR", 299, 0), ("CAR", 300, 0), ("CAR", 301, 40),
])
def test_tc06_fees(app, db_path, vehicle_type, seconds, fee):
    client = logged_in(app)
    ticket = enter(client, "TESTCAR1", vehicle_type).get_json()
    entered = datetime.now() + timedelta(seconds=1) - timedelta(seconds=seconds)
    sql(db_path, "UPDATE tickets SET entry_time = ?", (entered.strftime("%Y-%m-%d %H:%M:%S"),))
    quote = client.post("/api/parking/exit", json={"ticket_id": ticket["ticket_id"]}).get_json()
    assert abs(quote["duration_seconds"] - seconds) <= 2
    assert calculate_fee(seconds, quote["hourly_rate"], quote["grace_minutes"]) == fee


def test_tc07_payment_failure_then_success(app, db_path):
    admin = logged_in(app, ADMIN)
    ticket_id = enter(admin).get_json()["ticket_id"]
    admin.post("/api/admin/payment-mode", json={"force_failure": True})
    assert admin.post("/api/payment/mock", json={"ticket_id": ticket_id}).status_code == 402
    assert sql(db_path, "SELECT status FROM tickets") == [("ACTIVE",)]
    assert sql(db_path, "SELECT status FROM slots WHERE slot_id = 'S01'") == [("OCCUPIED",)]

    admin.post("/api/admin/payment-mode", json={"force_failure": False})
    receipt = admin.post("/api/payment/mock", json={"ticket_id": ticket_id}).get_json()
    assert receipt["gate"] == "OPEN" and receipt["reference"].startswith("PAY-")
    for field in ("ticket_id", "plate_number", "slot_id", "entry_time", "exit_time", "duration",
                  "hourly_rate"):
        assert receipt[field]
    assert sql(db_path, "SELECT status FROM slots WHERE slot_id = 'S01'") == [("VACANT",)]


def test_tc08_reports(app, db_path):
    admin = logged_in(app, ADMIN)
    admin.post("/admin/demo-data", json={})
    total = sql(db_path, "SELECT SUM(amount) FROM payments WHERE status = 'SUCCESS'")[0][0]
    for period in ("daily", "weekly", "monthly"):
        started = time.perf_counter()
        data = admin.get(f"/api/reports/revenue?period={period}").get_json()
        assert "CI" in os.environ or time.perf_counter() - started <= 3
        assert data["total_revenue"] == total
    assert re.match(r"^\d\d:00$", admin.get("/api/reports/occupancy").get_json()["peak_hour"])
    assert str(total) in admin.get("/reports/export.csv").get_data(as_text=True)
    assert admin.get("/reports/export.pdf").data.startswith(b"%PDF")


def test_tc09_demo_data_clock_and_overstay(app, db_path):
    assert sql(db_path, "SELECT COUNT(*) FROM slots") == [(20,)]
    assert sql(db_path, "SELECT COUNT(*) FROM users") == [(2,)]
    admin = logged_in(app, ADMIN)
    admin.post("/admin/demo-data", json={})
    assert sql(db_path, "SELECT COUNT(*) FROM dwell_history") == [(200,)]
    enter(admin)
    set_clock(db_path, 23 * 60 + 55)
    assert "Overstay</td>" not in admin.get("/").get_data(as_text=True)
    set_clock(db_path, 24 * 60 + 5)
    assert "Overstay</td>" in admin.get("/").get_data(as_text=True)


@pytest.mark.skipif("CI" in os.environ, reason="timing is checked on the reference machine")
def test_tc10_timing(app):
    client = logged_in(app)
    timings = []
    for n in range(20):
        started = time.perf_counter()
        ticket_id = enter(client, f"CAR{n:05d}").get_json()["ticket_id"]
        client.post("/api/payment/mock", json={"ticket_id": ticket_id})
        timings.append(time.perf_counter() - started)
    assert sorted(timings)[18] <= 1


def test_tc11_parallel_entries(app, db_path):
    def parallel(plates):
        def one(plate):
            return enter(logged_in(app), plate).status_code
        with ThreadPoolExecutor(max_workers=len(plates)) as pool:
            return list(pool.map(one, plates))

    assert parallel([f"CARA{n:03d}" for n in range(9)]) == [201] * 9
    assert sorted(parallel([f"CARB{n:03d}" for n in range(5)])) == [201, 409, 409, 409, 409]
    assert sql(db_path, "SELECT slot_id, COUNT(*) FROM tickets WHERE status = 'ACTIVE'"
                        " GROUP BY slot_id HAVING COUNT(*) > 1") == []


def test_tc12_data_survives_restart(app, db_path):
    client = logged_in(app)
    ticket_id = enter(client).get_json()["ticket_id"]
    restarted = create_app({"TESTING": True, "DATABASE": db_path})
    again = logged_in(restarted)
    assert again.get(f"/api/parking/{ticket_id}").get_json()["status"] == "ACTIVE"


def test_tc14_hashing_and_lockout(app, db_path):
    hashes = dict(sql(db_path, "SELECT username, password_hash FROM users"))
    assert hashes["admin"] != hashes["attendant"]
    assert hashes["admin"].startswith("scrypt:") and "Admin@123" not in hashes["admin"]
    assert check_password_hash(hashes["admin"], "Admin@123")

    client = app.test_client()
    good = {"username": "attendant", "password": "Attend@123"}
    for _ in range(5):
        client.post("/login", data={**good, "password": "wrong"})
    assert client.post("/login", data=good).status_code == 401
    assert sql(db_path, "SELECT COUNT(*) FROM audit_log WHERE action = 'ACCOUNT_LOCKED'") == [(1,)]
    set_clock(db_path, 6)
    assert client.post("/login", data=good).status_code == 302


def test_tc15_roles_and_audit(app, db_path):
    attendant = logged_in(app)
    rates = {"rate_two_wheeler": "20", "rate_car": "55", "rate_ev": "50", "grace_minutes": "5"}
    for path in ("/admin/settings", "/admin/audit", "/reports"):
        assert attendant.get(path).status_code == 403
    assert attendant.post("/admin/settings", data=rates).status_code == 403
    assert sql(db_path, "SELECT COUNT(*) FROM audit_log WHERE action = 'ACCESS_DENIED'") == [(4,)]

    admin = logged_in(app, ADMIN)
    admin.post("/admin/settings", data=rates)
    assert sql(db_path, "SELECT old_value, new_value FROM audit_log"
                        " WHERE action = 'UPDATE_SETTING rate_car'") == [("40", "55")]
    assert admin.delete("/admin/audit").status_code == 405


@pytest.mark.parametrize("attack", ["' OR '1'='1", "'; DROP TABLE tickets;--"])
def test_tc16_sql_injection(app, db_path, attack):
    anonymous = app.test_client()
    assert anonymous.post("/login", data={"username": attack, "password": attack}
                          ).status_code == 401
    client = logged_in(app)
    assert enter(client, attack).status_code == 400
    assert client.post("/api/parking/exit", json={"ticket_id": attack}).status_code == 404
    assert sql(db_path, "SELECT COUNT(*) FROM tickets") == [(0,)]


def test_tc16_script_is_escaped(app):
    client = logged_in(app)
    page = client.post("/entry", data={"plate": "<script>alert(1)</script>",
                                       "vehicle_type": "CAR"}).get_data(as_text=True)
    assert "<script>alert(1)</script>" not in page
    assert "&lt;script&gt;" in page


def test_tc17_sessions_and_csrf(db_path):
    app = create_app({"TESTING": True, "WTF_CSRF_ENABLED": True, "DATABASE": db_path})
    client = app.test_client()
    assert client.post("/login", data={"username": "admin", "password": "Admin@123"}
                       ).status_code == 400
    page = client.get("/login").get_data(as_text=True)
    token = re.search(r'name="csrf_token" value="([^"]+)"', page).group(1)
    assert client.post("/login", data={"username": "admin", "password": "Admin@123",
                                       "csrf_token": "forged"}).status_code == 400
    response = client.post("/login", data={"username": "admin", "password": "Admin@123",
                                           "csrf_token": token})
    assert response.status_code == 302
    cookie = response.headers["Set-Cookie"]
    assert "HttpOnly" in cookie and "SameSite=Lax" in cookie

    with client.session_transaction() as session:
        session["last_seen"] = time.time() - 16 * 60
    assert client.get("/entry").status_code == 302

    fresh = app.test_client()
    page = fresh.get("/login").get_data(as_text=True)
    token = re.search(r'name="csrf_token" value="([^"]+)"', page).group(1)
    login = fresh.post("/login", data={"username": "admin", "password": "Admin@123",
                                       "csrf_token": token})
    value = re.search(r"session=([^;]+)", login.headers["Set-Cookie"]).group(1)
    page = fresh.get("/entry").get_data(as_text=True)
    token = re.search(r'name="csrf_token" value="([^"]+)"', page).group(1)
    fresh.post("/logout", data={"csrf_token": token})
    replay = app.test_client()
    replay.set_cookie("session", value)
    assert replay.get("/entry").status_code == 302
