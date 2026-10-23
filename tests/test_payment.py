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


def query(db_path, sql):
    con = sqlite3.connect(db_path)
    try:
        return con.execute(sql).fetchall()
    finally:
        con.close()


def park(client, db_path, minutes_ago, plate="KA01AB1234"):
    ticket_id = client.post("/api/parking/entry", json={"plate": plate, "vehicle_type": "CAR"}
                            ).get_json()["ticket_id"]
    entered = (datetime.now() - timedelta(minutes=minutes_ago)).strftime("%Y-%m-%d %H:%M:%S")
    con = sqlite3.connect(db_path)
    con.execute("UPDATE tickets SET entry_time = ? WHERE ticket_id = ?", (entered, ticket_id))
    con.commit()
    con.close()
    return ticket_id


def pay(client, ticket_id):
    return client.post("/api/payment/mock", json={"ticket_id": ticket_id})


def test_successful_payment_closes_ticket_and_frees_slot(client, db_path):
    ticket_id = park(client, db_path, minutes_ago=130)
    response = pay(client, ticket_id)
    assert response.status_code == 200
    receipt = response.get_json()
    assert receipt["reference"] == "PAY-000001"
    assert receipt["amount"] == 120
    assert receipt["gate"] == "OPEN"
    for field in ["ticket_id", "plate_number", "slot_id", "entry_time", "exit_time",
                  "duration", "hourly_rate"]:
        assert receipt[field]

    assert query(db_path, "SELECT status FROM tickets") == [("CLOSED",)]
    assert query(db_path, "SELECT status FROM slots WHERE slot_id = 'S04'") == [("VACANT",)]
    assert query(db_path, "SELECT amount, status FROM payments") == [(120, "SUCCESS")]
    assert query(db_path, "SELECT COUNT(*) FROM dwell_history") == [(1,)]


def test_payment_within_grace_is_zero(client, db_path):
    ticket_id = park(client, db_path, minutes_ago=2)
    assert pay(client, ticket_id).get_json()["amount"] == 0


def test_forced_failure_keeps_ticket_open(client, db_path):
    ticket_id = park(client, db_path, minutes_ago=30)
    assert client.post("/api/admin/payment-mode", json={"force_failure": True}
                       ).get_json() == {"force_failure": True}

    response = pay(client, ticket_id)
    assert response.status_code == 402
    assert response.get_json()["error"] == "PAYMENT_FAILED"
    assert query(db_path, "SELECT status FROM tickets") == [("ACTIVE",)]
    assert query(db_path, "SELECT status FROM slots WHERE slot_id = 'S04'") == [("OCCUPIED",)]
    assert query(db_path, "SELECT status FROM payments") == [("FAILED",)]

    client.post("/api/admin/payment-mode", json={"force_failure": False})
    assert pay(client, ticket_id).status_code == 200
    assert query(db_path, "SELECT status FROM payments ORDER BY payment_id") == [
        ("FAILED",), ("SUCCESS",)]


def test_paying_twice_is_rejected(client, db_path):
    ticket_id = park(client, db_path, minutes_ago=30)
    pay(client, ticket_id)
    response = pay(client, ticket_id)
    assert response.status_code == 409
    assert response.get_json()["error"] == "TICKET_CLOSED"
    assert query(db_path, "SELECT COUNT(*) FROM payments") == [(1,)]


def test_unknown_ticket(client):
    assert pay(client, "VPS-20000101-0001").status_code == 404


def test_exit_page_offers_mock_payment(client, db_path):
    ticket_id = park(client, db_path, minutes_ago=30)
    page = client.post("/exit", data={"ticket_id": ticket_id}).get_data(as_text=True)
    assert "Pay (Mock) Rs. 40" in page


def test_receipt_page(client, db_path):
    ticket_id = park(client, db_path, minutes_ago=130)
    response = client.post("/pay", data={"ticket_id": ticket_id})
    assert response.status_code == 200
    page = response.get_data(as_text=True)
    for text in ["PAY-000001", ticket_id, "KA01AB1234", "S04", "2 h 10 min", "Rs. 120", "OPEN"]:
        assert text in page


def test_failed_payment_page_shows_error_and_keeps_quote(client, db_path):
    ticket_id = park(client, db_path, minutes_ago=30)
    client.post("/api/admin/payment-mode", json={"force_failure": True})
    response = client.post("/pay", data={"ticket_id": ticket_id})
    assert response.status_code == 402
    page = response.get_data(as_text=True)
    assert "Mock payment failed" in page and "Pay (Mock)" in page


def test_only_admin_can_force_failure_and_change_is_audited(db_path):
    client = create_app({"TESTING": True, "DATABASE": db_path}).test_client()
    client.post("/login", data={"username": "attendant", "password": "attend123"})
    assert client.post("/api/admin/payment-mode", json={"force_failure": True}
                       ).status_code == 403
    client.post("/logout")

    client.post("/login", data={"username": "admin", "password": "admin123"})
    assert client.post("/admin/payment-mode", data={"force_failure": "1"}).status_code == 302
    assert "Forced failure" in client.get("/").get_data(as_text=True)
    assert query(db_path, "SELECT action, old_value, new_value FROM audit_log"
                          " WHERE action = 'SET_PAYMENT_FORCE_FAILURE'") == [
        ("SET_PAYMENT_FORCE_FAILURE", "0", "1")]
