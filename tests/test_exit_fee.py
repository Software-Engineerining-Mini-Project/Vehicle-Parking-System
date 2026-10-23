import sqlite3
from datetime import datetime, timedelta

import pytest

from vps import create_app
from vps.fees import billable_hours, calculate_fee, format_duration
from vps.parking import close_ticket

CAR, TWO_WHEELER, EV = 40, 20, 50


def mins(m, s=0):
    return m * 60 + s


# ---------- fee rules ----------

@pytest.mark.parametrize("seconds, fee", [
    (0, 0),
    (mins(4, 59), 0),        # inside grace
    (mins(5, 0), 0),         # grace boundary is still free
    (mins(5, 1), CAR),       # one second past grace starts hour 1
    (mins(60), CAR),         # exactly one hour
    (mins(60, 1), 2 * CAR),  # second hour has started
    (mins(130), 3 * CAR),    # 2 h 10 min -> Rs. 120 (TC-06)
])
def test_car_fee_boundaries(seconds, fee):
    assert calculate_fee(seconds, CAR) == fee


def test_rates_differ_by_vehicle_type():
    assert calculate_fee(mins(90), TWO_WHEELER) == 40
    assert calculate_fee(mins(90), EV) == 100


def test_grace_period_is_configurable():
    assert billable_hours(mins(9), grace_minutes=10) == 0
    assert billable_hours(mins(11), grace_minutes=10) == 1


def test_duration_text():
    assert format_duration(mins(130)) == "2 h 10 min"
    assert format_duration(mins(4, 59)) == "4 min 59 s"
    assert format_duration(42) == "42 s"


# ---------- exit endpoint ----------

@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "test.db")


@pytest.fixture
def client(db_path):
    return create_app({"TESTING": True, "DATABASE": db_path}).test_client()


def park(client, db_path, minutes_ago, plate="KA01AB1234", vehicle_type="CAR"):
    """Create a ticket and move its entry time back by the given number of minutes."""
    ticket_id = client.post("/api/parking/entry",
                            json={"plate": plate, "vehicle_type": vehicle_type}
                            ).get_json()["ticket_id"]
    entered = (datetime.now() - timedelta(minutes=minutes_ago)).strftime("%Y-%m-%d %H:%M:%S")
    con = sqlite3.connect(db_path)
    con.execute("UPDATE tickets SET entry_time = ? WHERE ticket_id = ?", (entered, ticket_id))
    con.commit()
    con.close()
    return ticket_id


def test_exit_shows_duration_and_fee(client, db_path):
    ticket_id = park(client, db_path, minutes_ago=130)
    response = client.post("/api/parking/exit", json={"ticket_id": ticket_id})
    assert response.status_code == 200
    quote = response.get_json()
    assert quote["duration"].startswith("2 h 10 min")
    assert quote["billable_hours"] == 3
    assert quote["fee"] == 120


def test_exit_within_grace_is_free(client, db_path):
    ticket_id = park(client, db_path, minutes_ago=3, vehicle_type="EV")
    assert client.post("/api/parking/exit", json={"ticket_id": ticket_id}).get_json()["fee"] == 0


def test_exit_does_not_release_slot_before_payment(client, db_path):
    ticket_id = park(client, db_path, minutes_ago=30)
    client.post("/api/parking/exit", json={"ticket_id": ticket_id})
    con = sqlite3.connect(db_path)
    assert con.execute("SELECT status FROM tickets").fetchone() == ("ACTIVE",)
    assert con.execute("SELECT status FROM slots WHERE slot_id = 'S04'").fetchone() == ("OCCUPIED",)
    con.close()


def test_unknown_ticket_returns_404(client):
    response = client.post("/api/parking/exit", json={"ticket_id": "VPS-20000101-0001"})
    assert response.status_code == 404
    assert response.get_json()["error"] == "TICKET_NOT_FOUND"


def test_missing_ticket_id_returns_400(client):
    response = client.post("/api/parking/exit", json={})
    assert response.status_code == 400
    assert response.get_json()["error"] == "MISSING_TICKET_ID"


def test_close_ticket_frees_slot_and_blocks_second_exit(client, db_path):
    ticket_id = park(client, db_path, minutes_ago=45)
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    closed = close_ticket(con, ticket_id, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    assert closed["status"] == "CLOSED"
    assert con.execute("SELECT status FROM slots WHERE slot_id = 'S04'").fetchone()[0] == "VACANT"
    assert con.execute("SELECT duration_min FROM dwell_history").fetchone()[0] == 45
    con.close()

    response = client.post("/api/parking/exit", json={"ticket_id": ticket_id})
    assert response.status_code == 409
    assert response.get_json()["error"] == "TICKET_CLOSED"


def test_exit_page_shows_fee(client, db_path):
    ticket_id = park(client, db_path, minutes_ago=130)
    page = client.post("/exit", data={"ticket_id": ticket_id.lower()}).get_data(as_text=True)
    assert "Rs. 120" in page
    assert "3 started hours x Rs. 40" in page


def test_exit_page_shows_error(client):
    response = client.post("/exit", data={"ticket_id": "nope"})
    assert response.status_code == 404
    assert "No ticket found" in response.get_data(as_text=True)
