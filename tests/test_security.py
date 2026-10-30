import re
import sqlite3
import time

import pytest

from vps import create_app


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "test.db")


@pytest.fixture
def client(db_path):
    return create_app({"TESTING": True, "DATABASE": db_path}).test_client()


def query(db_path, sql):
    con = sqlite3.connect(db_path)
    try:
        return con.execute(sql).fetchall()
    finally:
        con.close()


def login(client, username="attendant", password="Attend@123"):
    return client.post("/login", data={"username": username, "password": password})


# ---------- SEC-02 lockout ----------

def test_five_failures_lock_the_account_and_are_logged(client, db_path):
    for _ in range(5):
        assert login(client, password="wrong").status_code == 401
    response = login(client)  # correct password while locked
    assert response.status_code == 401
    assert "locked" in response.get_data(as_text=True).lower()
    assert query(db_path, "SELECT action, new_value FROM audit_log"
                          " WHERE action = 'ACCOUNT_LOCKED'") == [("ACCOUNT_LOCKED", "attendant")]


def test_four_failures_do_not_lock_and_success_resets(client):
    for _ in range(4):
        login(client, password="wrong")
    assert login(client).status_code == 302
    client.post("/logout")
    for _ in range(4):
        login(client, password="wrong")
    assert login(client).status_code == 302


def test_lock_ends_after_5_minutes(client, db_path):
    for _ in range(5):
        login(client, password="wrong")
    con = sqlite3.connect(db_path)
    con.execute("UPDATE settings SET value = '6' WHERE key = 'demo_clock_offset_min'")
    con.commit()
    con.close()
    assert login(client).status_code == 302


# ---------- SEC-04, SEC-05 injection and escaping ----------

@pytest.mark.parametrize("attack", ["' OR '1'='1", "'; DROP TABLE tickets;--"])
def test_sql_injection_is_harmless(client, db_path, attack):
    assert login(client, attack, attack).status_code == 401
    login(client)
    assert client.post("/api/parking/entry", json={"plate": attack, "vehicle_type": "CAR"}
                       ).status_code == 400
    assert client.post("/api/parking/exit", json={"ticket_id": attack}).status_code == 404
    assert query(db_path, "SELECT COUNT(*) FROM tickets") == [(0,)]
    assert query(db_path, "SELECT COUNT(*) FROM users") == [(2,)]


def test_script_is_shown_as_escaped_text(client):
    login(client)
    attack = "<script>alert(1)</script>"
    for page in (client.post("/entry", data={"plate": attack, "vehicle_type": "CAR"}),
                 client.post("/exit", data={"ticket_id": attack}),
                 client.post("/login", data={"username": attack, "password": "x"})):
        text = page.get_data(as_text=True)
        assert attack not in text


def test_unexpected_target_slot_is_ignored(client):
    login(client)
    ticket = client.post("/api/parking/entry",
                         json={"plate": "KA01AB1234", "vehicle_type": "CAR",
                               "target_slot": "<b>S01"}).get_json()
    assert ticket["slot_id"] == "S01" and ticket["reassigned_from"] is None


# ---------- SEC-06 sessions ----------

def test_session_cookie_flags(client):
    cookie = login(client).headers["Set-Cookie"]
    assert "HttpOnly" in cookie and "SameSite=Lax" in cookie


def test_session_ends_after_15_minutes_idle(client):
    login(client)
    assert client.get("/entry").status_code == 200
    with client.session_transaction() as session:
        session["last_seen"] = time.time() - 15 * 60 - 1
    assert client.get("/entry").status_code == 302


def test_session_stays_alive_within_15_minutes(client):
    login(client)
    with client.session_transaction() as session:
        session["last_seen"] = time.time() - 14 * 60
    assert client.get("/entry").status_code == 200


def test_live_grid_polling_does_not_keep_the_session_alive(client):
    login(client)
    with client.session_transaction() as session:
        session["last_seen"] = time.time() - 14 * 60
        before = session["last_seen"]
    assert client.get("/api/slots").status_code == 200
    with client.session_transaction() as session:
        assert session["last_seen"] == before


def test_old_cookie_is_refused_after_logout(client, db_path):
    response = login(client)
    cookie = re.search(r"session=([^;]+)", response.headers["Set-Cookie"]).group(1)
    assert client.get("/entry").status_code == 200
    client.post("/logout")

    replay = create_app({"TESTING": True, "DATABASE": db_path}).test_client()
    replay.set_cookie("session", cookie)
    assert replay.get("/entry").status_code == 302


# ---------- SEC-07 CSRF ----------

@pytest.fixture
def csrf_client(db_path):
    return create_app({"TESTING": True, "WTF_CSRF_ENABLED": True,
                       "DATABASE": db_path}).test_client()


def token_from(page):
    return re.search(r'name="csrf_token" value="([^"]+)"', page.get_data(as_text=True)).group(1)


def test_post_without_token_gets_400(csrf_client):
    assert csrf_client.post("/login", data={"username": "admin", "password": "Admin@123"}
                            ).status_code == 400
    assert csrf_client.post("/api/parking/entry", json={"plate": "KA01AB1234",
                                                        "vehicle_type": "CAR"}).status_code == 400


def test_post_with_forged_token_gets_400(csrf_client):
    csrf_client.get("/login")
    assert csrf_client.post("/login", data={"username": "admin", "password": "Admin@123",
                                            "csrf_token": "forged"}).status_code == 400


def test_post_with_valid_token_works(csrf_client):
    token = token_from(csrf_client.get("/login"))
    assert csrf_client.post("/login", data={"username": "admin", "password": "Admin@123",
                                            "csrf_token": token}).status_code == 302
    page = csrf_client.get("/entry")
    response = csrf_client.post("/entry", data={"plate": "KA01AB1234", "vehicle_type": "CAR",
                                                "csrf_token": token_from(page)})
    assert response.status_code == 201


def test_every_post_form_has_a_token(csrf_client):
    token = token_from(csrf_client.get("/login"))
    csrf_client.post("/login", data={"username": "admin", "password": "Admin@123",
                                     "csrf_token": token})
    for path in ["/", "/entry", "/exit", "/admin/settings"]:
        page = csrf_client.get(path).get_data(as_text=True)
        forms = re.findall(r'<form method="post".*?</form>', page, re.S)
        assert forms, path
        for form in forms:
            assert 'name="csrf_token"' in form, path


def test_secret_key_is_not_the_default(client):
    assert client.application.secret_key != "dev-only-change-me"


def test_second_login_does_not_end_the_first_session(db_path):
    app = create_app({"TESTING": True, "DATABASE": db_path})
    first, second = app.test_client(), app.test_client()
    login(first)
    login(second)
    assert first.get("/entry").status_code == 200
    assert second.get("/entry").status_code == 200
