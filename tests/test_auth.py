import sqlite3

import pytest
from werkzeug.security import check_password_hash

from vps import create_app


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "test.db")


@pytest.fixture
def client(db_path):
    return create_app({"TESTING": True, "DATABASE": db_path}).test_client()


def login(client, username, password):
    return client.post("/login", data={"username": username, "password": password})


def test_passwords_are_stored_as_salted_hashes(db_path, client):
    con = sqlite3.connect(db_path)
    rows = dict(con.execute("SELECT username, password_hash FROM users").fetchall())
    con.close()
    assert "admin123" not in rows["admin"]
    assert rows["admin"].startswith(("scrypt:", "pbkdf2:"))
    assert check_password_hash(rows["admin"], "admin123")
    assert check_password_hash(rows["attendant"], "attend123")


@pytest.mark.parametrize("path", ["/", "/entry", "/exit", "/slots"])
def test_staff_screens_need_login(client, path):
    response = client.get(path)
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_api_without_login_returns_401(client):
    response = client.get("/api/slots")
    assert response.status_code == 401
    assert response.get_json()["error"] == "LOGIN_REQUIRED"
    response = client.post("/api/parking/entry", json={"plate": "KA01AB1234",
                                                       "vehicle_type": "CAR"})
    assert response.status_code == 401


def test_wrong_password_is_rejected(client):
    response = login(client, "admin", "wrong")
    assert response.status_code == 401
    assert "Invalid username or password." in response.get_data(as_text=True)
    assert client.get("/entry").status_code == 302


def test_unknown_user_gets_the_same_message(client):
    response = login(client, "nobody", "admin123")
    assert response.status_code == 401
    assert "Invalid username or password." in response.get_data(as_text=True)


def test_attendant_can_use_entry_exit_and_slot_grid(client):
    assert login(client, "attendant", "attend123").status_code == 302
    for path in ["/", "/entry", "/exit", "/slots", "/api/slots"]:
        assert client.get(path).status_code == 200, path
    page = client.get("/").get_data(as_text=True)
    assert "attendant (Attendant)" in page and "Log out" in page


def test_attendant_gets_403_on_admin_route_and_it_is_audited(client, db_path):
    login(client, "attendant", "attend123")
    response = client.post("/api/slots/S05/reserve", json={"reserved": True})
    assert response.status_code == 403
    assert response.get_json()["error"] == "FORBIDDEN"

    con = sqlite3.connect(db_path)
    assert con.execute("SELECT action, new_value FROM audit_log").fetchall() == [
        ("ACCESS_DENIED", "POST /api/slots/S05/reserve")]
    assert con.execute("SELECT status FROM slots WHERE slot_id = 'S05'").fetchone() == ("VACANT",)
    con.close()


def test_admin_can_use_admin_routes(client):
    login(client, "admin", "admin123")
    response = client.post("/api/slots/S05/reserve", json={"reserved": True})
    assert response.status_code == 200
    assert response.get_json()["status"] == "RESERVED"


def test_logout_ends_the_session(client):
    login(client, "attendant", "attend123")
    assert client.get("/entry").status_code == 200
    response = client.post("/logout")
    assert response.status_code == 302
    assert client.get("/entry").status_code == 302


def test_login_returns_to_the_requested_page(client):
    response = client.post("/login?next=/exit", data={"username": "admin", "password": "admin123"})
    assert response.headers["Location"].endswith("/exit")


def test_login_never_redirects_to_another_site(client):
    response = client.post("/login?next=//evil.example.com",
                           data={"username": "admin", "password": "admin123"})
    assert response.headers["Location"] == "/"
