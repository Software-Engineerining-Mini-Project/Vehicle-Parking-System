import sqlite3
from datetime import datetime, timedelta

import pytest

from vps import create_app


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "test.db")


@pytest.fixture
def client(db_path):
    client = create_app({"TESTING": True, "DATABASE": db_path}).test_client()
    client.post("/login", data={"username": "admin", "password": "Admin@123"})
    return client


def query(db_path, sql):
    con = sqlite3.connect(db_path)
    try:
        return con.execute(sql).fetchall()
    finally:
        con.close()


def test_seed_creates_200_records_over_14_days(client, db_path):
    assert client.post("/admin/demo-data", json={}).status_code == 201
    assert query(db_path, "SELECT COUNT(*) FROM dwell_history") == [(200,)]
    assert query(db_path, "SELECT COUNT(*) FROM tickets WHERE status = 'CLOSED'") == [(200,)]
    assert query(db_path, "SELECT COUNT(*) FROM payments WHERE status = 'SUCCESS'") == [(200,)]
    (oldest, newest), = query(db_path, "SELECT MIN(entry_time), MAX(entry_time) FROM tickets")
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    assert datetime.fromisoformat(oldest) >= today - timedelta(days=14)
    assert datetime.fromisoformat(newest) < today + timedelta(days=1)
    assert query(db_path, "SELECT COUNT(*) FROM slots WHERE status != 'VACANT'") == [(0,)]


def test_seeded_history_never_double_books_a_slot(client, db_path):
    client.post("/admin/demo-data", json={})
    rows = query(db_path, "SELECT slot_id, entry_time, exit_time FROM tickets"
                          " ORDER BY slot_id, entry_time")
    for first, second in zip(rows, rows[1:]):
        if first[0] == second[0]:
            assert first[2] <= second[1]


def test_seed_twice_is_refused_and_audited_once(client, db_path):
    client.post("/admin/demo-data", json={})
    assert client.post("/admin/demo-data", json={}).status_code == 409
    assert query(db_path, "SELECT COUNT(*) FROM dwell_history") == [(200,)]
    assert query(db_path,
                 "SELECT COUNT(*) FROM audit_log WHERE action = 'SEED_DEMO_DATA'") == [(1,)]


def test_new_ticket_numbering_is_unaffected_by_seed(client):
    client.post("/admin/demo-data", json={})
    ticket = client.post("/api/parking/entry",
                         json={"plate": "KA01AB1234", "vehicle_type": "CAR"}).get_json()
    assert ticket["ticket_id"].endswith("-0001")


@pytest.mark.parametrize("step, minutes", [("5min", 5), ("1h", 60), ("1day", 1440)])
def test_demo_clock_steps(client, db_path, step, minutes):
    assert client.post("/admin/demo-clock", json={"step": step}
                       ).get_json()["offset_minutes"] == minutes
    assert query(db_path, "SELECT old_value, new_value FROM audit_log"
                          " WHERE action = 'ADVANCE_DEMO_CLOCK'") == [("0", str(minutes))]


def test_demo_clock_rejects_other_steps(client):
    assert client.post("/admin/demo-clock", json={"step": "99"}).status_code == 400


def test_demo_clock_drives_the_fee(client):
    ticket_id = client.post("/api/parking/entry", json={"plate": "KA01AB1234",
                                                        "vehicle_type": "CAR"}
                            ).get_json()["ticket_id"]
    client.post("/admin/demo-clock", json={"step": "1h"})
    client.post("/admin/demo-clock", json={"step": "1h"})
    client.post("/admin/demo-clock", json={"step": "5min"})
    assert client.post("/api/parking/exit", json={"ticket_id": ticket_id}).get_json()["fee"] == 120


def test_attendant_cannot_use_demo_controls(db_path):
    client = create_app({"TESTING": True, "DATABASE": db_path}).test_client()
    client.post("/login", data={"username": "attendant", "password": "Attend@123"})
    assert client.post("/admin/demo-clock", json={"step": "1h"}).status_code == 403
    assert client.post("/admin/demo-data", json={}).status_code == 403
    assert "Demo controls" not in client.get("/").get_data(as_text=True)


def test_overstay_flag_only_after_24_hours(client, db_path):
    # TC-09: 23 h 55 min is not flagged, 24 h 5 min is
    client.post("/api/parking/entry", json={"plate": "KA01AB1234", "vehicle_type": "CAR"})
    con = sqlite3.connect(db_path)
    set_offset = "UPDATE settings SET value = ? WHERE key = 'demo_clock_offset_min'"
    con.execute(set_offset, (str(23 * 60 + 55),))
    con.commit()
    assert "No vehicle has been parked" in client.get("/").get_data(as_text=True)
    con.execute(set_offset, (str(24 * 60 + 5),))
    con.commit()
    con.close()
    page = client.get("/").get_data(as_text=True)
    assert "Overstay</td>" in page and "KA01AB1234" in page
