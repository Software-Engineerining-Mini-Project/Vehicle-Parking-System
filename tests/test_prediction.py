import sqlite3
from datetime import datetime, timedelta

import pytest

from vps import create_app


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "test.db")


@pytest.fixture
def client(db_path):
    return create_app({"TESTING": True, "LOGIN_DISABLED": True,
                       "DATABASE": db_path}).test_client()


def add_history(db_path, count, minutes, vehicle_type="CAR"):
    con = sqlite3.connect(db_path)
    con.executemany(
        "INSERT INTO dwell_history (vehicle_type, entry_time, exit_time, duration_min)"
        " VALUES (?, '2026-01-01 09:00:00', '2026-01-01 10:00:00', ?)",
        [(vehicle_type, minutes)] * count)
    con.commit()
    con.close()


def park(client, db_path, plate, minutes_ago, vehicle_type="CAR"):
    ticket_id = client.post("/api/parking/entry", json={"plate": plate,
                                                        "vehicle_type": vehicle_type}
                            ).get_json()["ticket_id"]
    entered = (datetime.now() - timedelta(minutes=minutes_ago)).strftime("%Y-%m-%d %H:%M:%S")
    con = sqlite3.connect(db_path)
    con.execute("UPDATE tickets SET entry_time = ? WHERE ticket_id = ?", (entered, ticket_id))
    con.commit()
    con.close()
    return ticket_id


def estimate(client, category="CAR"):
    return client.get(f"/api/prediction/next-vacancy?category={category}"
                      ).get_json()["estimates"][0]


def test_completed_ticket_stores_dwell_per_vehicle_type(client, db_path):
    ticket_id = park(client, db_path, "EV0001", 45, "EV")
    client.post("/api/payment/mock", json={"ticket_id": ticket_id})
    con = sqlite3.connect(db_path)
    assert con.execute("SELECT vehicle_type, duration_min FROM dwell_history"
                       ).fetchall() == [("EV", 45)]
    con.close()


def test_estimate_formula(client, db_path):
    # Average 90 min; longest parked 86 min gives about 4 min (TC-05)
    add_history(db_path, 5, 90)
    park(client, db_path, "CAR0001", 86)
    park(client, db_path, "CAR0002", 30)
    data = estimate(client)
    assert data["minutes"] == 5 or data["minutes"] == 4
    assert data["message"] == f"Next Car slot expected in about {data['minutes']} min"


def test_estimate_rounds_up_to_a_whole_minute(client, db_path):
    add_history(db_path, 5, 90)
    park(client, db_path, "CAR0001", 80)
    assert estimate(client)["minutes"] == 10


def test_estimate_is_never_negative(client, db_path):
    add_history(db_path, 5, 30)
    park(client, db_path, "CAR0001", 100)
    assert estimate(client)["minutes"] == 0


def test_fewer_than_5_records_is_unavailable(client, db_path):
    add_history(db_path, 4, 90)
    park(client, db_path, "CAR0001", 10)
    data = estimate(client)
    assert data["minutes"] is None and data["message"] == "Estimate unavailable"


def test_full_category_refused_with_estimate(client, db_path):
    add_history(db_path, 5, 90)
    for n in range(4):
        park(client, db_path, f"BIKE{n:02d}", 10, "TWO_WHEELER")
    add_history(db_path, 5, 60, "TWO_WHEELER")
    response = client.post("/api/parking/entry", json={"plate": "BIKE99",
                                                       "vehicle_type": "TWO_WHEELER"})
    assert response.status_code == 409
    message = response.get_json()["message"]
    assert message.startswith("No Two-Wheeler slot available.")
    assert "Next Two-Wheeler slot expected in about" in message


def test_full_category_without_history_says_unavailable(client, db_path):
    for n in range(4):
        park(client, db_path, f"EV{n:04d}", 10, "EV")
    message = client.post("/api/parking/entry", json={"plate": "EV0099", "vehicle_type": "EV"}
                          ).get_json()["message"]
    assert message == "No EV slot available. Estimate unavailable"


def test_entry_screen_shows_estimates(client, db_path):
    add_history(db_path, 5, 90)
    park(client, db_path, "CAR0001", 30)
    page = client.get("/entry").get_data(as_text=True)
    assert "Next Car slot expected in about" in page
    assert "Estimate unavailable" in page


def test_invalid_category_is_rejected(client):
    assert client.get("/api/prediction/next-vacancy?category=BUS").status_code == 400


def test_api_without_category_lists_all(client):
    data = client.get("/api/prediction/next-vacancy").get_json()
    assert len(data["estimates"]) == 4
