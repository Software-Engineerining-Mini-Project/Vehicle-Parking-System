import sqlite3

import pytest

from vps import create_app

GOOD = {"rate_two_wheeler": "20", "rate_car": "60", "rate_ev": "50", "grace_minutes": "10"}


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


def test_rate_change_is_saved_and_audited(client, db_path):
    assert client.post("/admin/settings", data=GOOD).status_code == 200
    assert query(db_path, "SELECT value FROM settings WHERE key = 'rate_car'") == [("60",)]
    rows = query(db_path, "SELECT a.action, a.old_value, a.new_value, u.username, a.logged_at"
                          " FROM audit_log a JOIN users u ON u.user_id = a.user_id"
                          " WHERE a.action = 'UPDATE_SETTING rate_car'")
    assert rows[0][:4] == ("UPDATE_SETTING rate_car", "40", "60", "admin") and rows[0][4]


def test_new_rate_and_grace_change_the_fee(client):
    client.post("/admin/settings", data=GOOD)
    ticket_id = client.post("/api/parking/entry", json={"plate": "KA01AB1234",
                                                        "vehicle_type": "CAR"}
                            ).get_json()["ticket_id"]
    client.post("/admin/demo-clock", json={"step": "1h"})
    assert client.post("/api/parking/exit", json={"ticket_id": ticket_id}).get_json()["fee"] == 60


@pytest.mark.parametrize("change", [{"grace_minutes": "31"}, {"grace_minutes": "-1"},
                                    {"rate_car": "0"}, {"rate_car": "abc"}, {"rate_ev": ""}])
def test_invalid_settings_are_rejected(client, db_path, change):
    response = client.post("/admin/settings", data={**GOOD, **change})
    assert response.status_code == 400
    assert query(db_path, "SELECT value FROM settings WHERE key = 'rate_car'") == [("40",)]
    assert query(db_path, "SELECT COUNT(*) FROM audit_log") == [(0,)]


def test_grace_limits_are_accepted(client):
    for value in ("0", "30"):
        assert client.post("/admin/settings",
                           data={**GOOD, "grace_minutes": value}).status_code == 200


def current_layout(client):
    page = client.get("/admin/settings").get_data(as_text=True)
    return page.split('spellcheck="false">')[1].split("</textarea>")[0]


def test_layout_can_add_a_slot_and_is_audited(client, db_path):
    layout = current_layout(client).replace("# # .", "S21:EV # .", 1)
    response = client.post("/admin/layout", data={"layout": layout})
    assert "Layout saved." in response.get_data(as_text=True)
    assert query(db_path, "SELECT category, status FROM slots WHERE slot_id = 'S21'") == [
        ("EV", "VACANT")]
    assert query(db_path, "SELECT COUNT(*) FROM audit_log WHERE action = 'UPDATE_LAYOUT'") == [(1,)]
    assert client.get("/api/slots").get_json()["counts"]["EV"]["total"] == 5


def test_blocking_a_road_changes_the_route(client):
    layout = current_layout(client)
    lines = layout.splitlines()
    cells = lines[1].split()
    cells[2] = "#"
    lines[1] = " ".join(cells)
    response = client.post("/admin/layout", data={"layout": "\n".join(lines)})
    assert "Warning: no route reaches" in response.get_data(as_text=True)
    ticket = client.post("/api/parking/entry", json={"plate": "KA01AB1234",
                                                     "vehicle_type": "CAR"}).get_json()
    assert ticket["slot_id"] == "S01"


@pytest.mark.parametrize("bad", [
    "N . X\n. .",                          # uneven rows
    ". . .",                               # no entrance or exit
    "N N X",                               # two entrances
    "N Q X",                               # unknown cell
    "N S99 X",                             # new slot without a category
    "N S99:BUS X",                         # unknown category
    "\n".join(["N X " + ". " * 9] * 2),    # too wide
])
def test_invalid_layouts_are_rejected(client, db_path, bad):
    before = query(db_path, "SELECT COUNT(*) FROM grid_cells")
    assert client.post("/admin/layout", data={"layout": bad}).status_code == 400
    assert query(db_path, "SELECT COUNT(*) FROM grid_cells") == before


def test_slot_with_history_cannot_be_removed(client, db_path):
    client.post("/api/parking/entry", json={"plate": "KA01AB1234", "vehicle_type": "CAR"})
    layout = current_layout(client).replace("S01", "#", 1)
    response = client.post("/admin/layout", data={"layout": layout})
    assert response.status_code == 400
    assert "S01 has parking history" in response.get_data(as_text=True)
    assert query(db_path, "SELECT COUNT(*) FROM slots") == [(20,)]


def test_reservation_from_settings_page_is_audited(client, db_path):
    assert client.post("/admin/reserve", data={"slot_id": "S05", "reserved": "1"}
                       ).status_code == 302
    assert query(db_path, "SELECT status FROM slots WHERE slot_id = 'S05'") == [("RESERVED",)]
    assert query(db_path, "SELECT old_value, new_value FROM audit_log"
                          " WHERE action = 'RESERVE_SLOT S05'") == [("VACANT", "RESERVED")]


def test_audit_page_lists_changes_read_only(client):
    client.post("/admin/settings", data=GOOD)
    page = client.get("/admin/audit").get_data(as_text=True)
    assert "UPDATE_SETTING rate_car" in page
    for method in (client.delete, client.put, client.patch, client.post):
        assert method("/admin/audit").status_code == 405


def test_database_refuses_to_change_audit_rows(client, db_path):
    client.post("/admin/settings", data=GOOD)
    con = sqlite3.connect(db_path)
    for sql in ("DELETE FROM audit_log", "UPDATE audit_log SET action = 'x'"):
        with pytest.raises(sqlite3.IntegrityError):
            con.execute(sql)
    con.close()


def test_attendant_gets_403_and_is_logged(db_path):
    client = create_app({"TESTING": True, "DATABASE": db_path}).test_client()
    client.post("/login", data={"username": "attendant", "password": "Attend@123"})
    assert client.get("/admin/settings").status_code == 403
    assert client.post("/admin/settings", data=GOOD).status_code == 403
    assert client.get("/admin/audit").status_code == 403
    assert query(db_path, "SELECT value FROM settings WHERE key = 'rate_car'") == [("40",)]
    assert query(db_path,
                 "SELECT COUNT(*) FROM audit_log WHERE action = 'ACCESS_DENIED'") == [(3,)]
