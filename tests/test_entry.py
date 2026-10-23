import re
import sqlite3

import pytest

from vps import create_app

TICKET_PATTERN = re.compile(r"^VPS-\d{8}-\d{4}$")


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "test.db")


@pytest.fixture
def client(db_path):
    return create_app({"TESTING": True, "DATABASE": db_path}).test_client()


def enter(client, plate="KA01AB1234", vehicle_type="CAR", **extra):
    return client.post("/api/parking/entry",
                       json={"plate": plate, "vehicle_type": vehicle_type, **extra})


def query(db_path, sql, args=()):
    con = sqlite3.connect(db_path)
    try:
        return con.execute(sql, args).fetchall()
    finally:
        con.close()


def test_entry_creates_ticket_and_occupies_slot(client, db_path):
    response = enter(client)
    assert response.status_code == 201
    ticket = response.get_json()
    assert TICKET_PATTERN.match(ticket["ticket_id"])
    assert ticket["slot_id"] == "S04"
    assert ticket["status"] == "ACTIVE"
    assert ticket["path"][0] == [1, 0]
    assert query(db_path, "SELECT status FROM slots WHERE slot_id = 'S04'") == [("OCCUPIED",)]


def test_plate_is_normalised(client):
    ticket = enter(client, plate=" ka 01 ab 1234 ").get_json()
    assert ticket["plate_number"] == "KA01AB1234"


@pytest.mark.parametrize("plate", ["", "AB1", "ABCDEFGHIJK", "KA-01-AB", "KA01@B"])
def test_invalid_plate_is_rejected_with_clear_message(client, plate):
    response = enter(client, plate=plate)
    assert response.status_code == 400
    body = response.get_json()
    assert body["error"] == "INVALID_PLATE"
    assert "4 to 10 letters or digits" in body["message"]
    assert "Traceback" not in response.get_data(as_text=True)


@pytest.mark.parametrize("plate", ["AB12", "ABCDE12345"])
def test_plate_length_boundaries_are_accepted(client, plate):
    assert enter(client, plate=plate).status_code == 201


def test_invalid_vehicle_type_is_rejected(client):
    response = enter(client, vehicle_type="TRUCK")
    assert response.status_code == 400
    assert response.get_json()["error"] == "INVALID_VEHICLE_TYPE"


def test_same_plate_cannot_enter_twice(client):
    first = enter(client).get_json()
    response = enter(client, plate="ka01ab1234")
    assert response.status_code == 409
    assert response.get_json()["error"] == "DUPLICATE_ACTIVE_TICKET"
    assert first["ticket_id"] in response.get_json()["message"]


def test_ticket_numbers_increase_through_the_day(client):
    first = enter(client, plate="CAR0001").get_json()["ticket_id"]
    second = enter(client, plate="CAR0002").get_json()["ticket_id"]
    assert first.endswith("-0001") and second.endswith("-0002")
    assert first[:13] == second[:13]


def test_entry_time_is_saved_to_the_second(client, db_path):
    ticket_id = enter(client).get_json()["ticket_id"]
    (entry_time,), = query(db_path, "SELECT entry_time FROM tickets WHERE ticket_id = ?",
                           (ticket_id,))
    assert re.match(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$", entry_time)


def test_vehicles_get_slots_of_their_own_category(client):
    assert enter(client, plate="BIKE01", vehicle_type="TWO_WHEELER").get_json()["category"] \
        == "TWO_WHEELER"
    assert enter(client, plate="EV0001", vehicle_type="EV").get_json()["category"] == "EV"
    assert enter(client, plate="ACC001", accessible=True).get_json()["category"] == "ACCESSIBLE"


def test_next_car_gets_next_nearest_slot(client):
    assert enter(client, plate="CAR0001").get_json()["slot_id"] == "S04"
    assert enter(client, plate="CAR0002").get_json()["slot_id"] == "S10"


def test_full_category_returns_no_slot_available(client):
    for n in range(4):
        assert enter(client, plate=f"BIKE{n:02d}", vehicle_type="TWO_WHEELER").status_code == 201
    response = enter(client, plate="BIKE99", vehicle_type="TWO_WHEELER")
    assert response.status_code == 409
    assert response.get_json()["error"] == "NO_SLOT_AVAILABLE"


def test_get_ticket_and_unknown_ticket(client):
    ticket_id = enter(client).get_json()["ticket_id"]
    assert client.get(f"/api/parking/{ticket_id}").get_json()["plate_number"] == "KA01AB1234"
    response = client.get("/api/parking/VPS-20000101-0001")
    assert response.status_code == 404
    assert response.get_json()["error"] == "TICKET_NOT_FOUND"


def test_ticket_has_qr_code(client):
    ticket_id = enter(client).get_json()["ticket_id"]
    response = client.get(f"/tickets/{ticket_id}/qr.svg")
    assert response.status_code == 200
    assert response.mimetype == "image/svg+xml"
    assert b"<svg" in response.data
    assert client.get("/tickets/VPS-20000101-0001/qr.svg").status_code == 404


def test_entry_page_shows_ticket(client):
    response = client.post("/entry", data={"plate": "KA01AB1234", "vehicle_type": "CAR"})
    assert response.status_code == 201
    page = response.get_data(as_text=True)
    assert "Ticket VPS-" in page and "S04" in page and "OPEN" in page


def test_entry_page_shows_error_next_to_form(client):
    response = client.post("/entry", data={"plate": "x", "vehicle_type": "CAR"})
    assert response.status_code == 400
    assert "4 to 10 letters or digits" in response.get_data(as_text=True)
