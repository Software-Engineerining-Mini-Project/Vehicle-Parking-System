import sqlite3

import pytest

from vps import create_app


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "test.db")


@pytest.fixture
def app(db_path):
    return create_app({"TESTING": True, "LOGIN_DISABLED": True, "DATABASE": db_path})


def query(db_path, sql):
    con = sqlite3.connect(db_path)
    try:
        return con.execute(sql).fetchall()
    finally:
        con.close()


def test_home_page_loads(app):
    response = app.test_client().get("/")
    assert response.status_code == 200
    assert b"Vehicle Parking System" in response.data


def test_all_tables_are_created(app, db_path):
    tables = {r[0] for r in query(db_path, "SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert {"users", "vehicles", "slots", "grid_cells", "tickets",
            "payments", "audit_log", "dwell_history", "settings"} <= tables


def test_default_layout_has_20_slots(app, db_path):
    counts = dict(query(db_path, "SELECT category, COUNT(*) FROM slots GROUP BY category"))
    assert counts == {"CAR": 10, "TWO_WHEELER": 4, "ACCESSIBLE": 2, "EV": 4}
    assert query(db_path, "SELECT COUNT(*) FROM grid_cells") == [(48,)]
    assert query(db_path, "SELECT MAX(row_no), MAX(col_no) FROM grid_cells") == [(5, 7)]


def test_admin_and_attendant_accounts_exist(app, db_path):
    users = dict(query(db_path, "SELECT username, role FROM users"))
    assert users == {"admin": "ADMIN", "attendant": "ATTENDANT"}
    for (password_hash,) in query(db_path, "SELECT password_hash FROM users"):
        assert "admin123" not in password_hash and "attend123" not in password_hash


def test_data_survives_restart(app, db_path):
    con = sqlite3.connect(db_path)
    con.execute("UPDATE slots SET status = 'OCCUPIED' WHERE slot_id = 'S01'")
    con.commit()
    con.close()

    create_app({"TESTING": True, "LOGIN_DISABLED": True, "DATABASE": db_path})  # simulate a restart

    assert query(db_path, "SELECT status FROM slots WHERE slot_id = 'S01'") == [("OCCUPIED",)]
    assert query(db_path, "SELECT COUNT(*) FROM slots") == [(20,)]
