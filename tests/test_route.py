import os
import sqlite3
import time

import pytest

from vps import create_app


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "test.db")


@pytest.fixture
def client(db_path):
    return create_app({"TESTING": True, "LOGIN_DISABLED": True,
                       "DATABASE": db_path}).test_client()


def run_sql(db_path, sql):
    con = sqlite3.connect(db_path)
    rows = con.execute(sql).fetchall()
    con.commit()
    con.close()
    return rows


def enter(client, plate="KA01AB1234", **extra):
    return client.post("/api/parking/entry",
                       json={"plate": plate, "vehicle_type": "CAR", **extra})


def preview(client, **extra):
    return client.post("/api/parking/preview",
                       json={"plate": "KA01AB1234", "vehicle_type": "CAR", **extra})


def test_preview_returns_route_and_changes_nothing(client, db_path):
    data = preview(client).get_json()
    assert data["slot_id"] == "S01"
    assert data["path"] == [[1, 0], [1, 1], [0, 1]]
    assert run_sql(db_path, "SELECT COUNT(*) FROM tickets") == [(0,)]
    assert run_sql(db_path, "SELECT status FROM slots WHERE slot_id = 'S01'") == [("VACANT",)]


def test_tc04_route_length_and_exit_mode(client, db_path):
    run_sql(db_path, "UPDATE slots SET status = 'OCCUPIED' WHERE slot_id IN ('S01', 'S02')")
    data = preview(client).get_json()
    assert data["slot_id"] == "S03" and len(data["path"]) - 1 == 4
    assert preview(client, start_from="EXIT").get_json()["slot_id"] == "S10"


def test_invalid_start_point_is_rejected(client):
    assert enter(client, start_from="ROOF").status_code == 400
    assert preview(client, start_from="ROOF").status_code == 400


def test_confirm_keeps_the_previewed_slot(client):
    ticket = enter(client, start_from="EXIT", target_slot="S10").get_json()
    assert ticket["slot_id"] == "S10" and ticket["reassigned_from"] is None


def test_taken_target_is_reassigned_within_500_ms(client, db_path):
    target = preview(client).get_json()["slot_id"]
    run_sql(db_path, f"UPDATE slots SET status = 'OCCUPIED' WHERE slot_id = '{target}'")
    started = time.perf_counter()
    response = enter(client, target_slot=target)
    elapsed = time.perf_counter() - started
    ticket = response.get_json()
    assert response.status_code == 201
    assert ticket["slot_id"] == "S02" and ticket["reassigned_from"] == "S01"
    assert "CI" in os.environ or elapsed < 0.5


def test_blocked_path_is_reassigned(client, db_path):
    run_sql(db_path, "UPDATE grid_cells SET cell_type = 'WALL' WHERE row_no = 1 AND col_no = 4")
    ticket = enter(client, target_slot="S04").get_json()
    assert ticket["slot_id"] == "S01" and ticket["reassigned_from"] == "S04"


def test_full_category_on_preview(client, db_path):
    run_sql(db_path, "UPDATE slots SET status = 'OCCUPIED' WHERE category = 'EV'")
    response = client.post("/api/parking/preview",
                           json={"plate": "KA01AB1234", "vehicle_type": "EV"})
    assert response.status_code == 409


def test_entry_page_draws_preview_then_confirms(client):
    page = client.post("/entry", data={"plate": "KA01AB1234", "vehicle_type": "CAR",
                                       "action": "preview"}).get_data(as_text=True)
    assert "Proposed slot" in page and "data-path=" in page and "[1, 1]" in page
    assert 'name="target_slot" value="S01"' in page
    assert "Confirm Entry" in page and 'value="KA01AB1234"' in page

    response = client.post("/entry", data={"plate": "KA01AB1234", "vehicle_type": "CAR",
                                           "action": "confirm", "target_slot": "S01"})
    assert response.status_code == 201
    assert "Ticket VPS-" in response.get_data(as_text=True)


def test_entry_page_reports_reassignment(client, db_path):
    run_sql(db_path, "UPDATE slots SET status = 'OCCUPIED' WHERE slot_id = 'S01'")
    page = client.post("/entry", data={"plate": "KA01AB1234", "vehicle_type": "CAR",
                                       "action": "confirm", "target_slot": "S01"}
                       ).get_data(as_text=True)
    assert "Slot S01 is no longer available" in page and "S02" in page
