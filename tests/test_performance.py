"""Reliability and performance targets (NFR-REL-02, NFR-PERF-01 to 03; TC-10, TC-11)."""
import os
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from vps import create_app


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "test.db")


@pytest.fixture
def app(db_path):
    return create_app({"TESTING": True, "LOGIN_DISABLED": True, "DATABASE": db_path})


def parallel_entries(app, plates, vehicle_type="CAR"):
    def enter(plate):
        return app.test_client().post("/api/parking/entry",
                                      json={"plate": plate, "vehicle_type": vehicle_type})
    with ThreadPoolExecutor(max_workers=len(plates)) as pool:
        return list(pool.map(enter, plates))


def test_five_entries_for_one_free_slot_give_one_success(app, db_path):
    con = sqlite3.connect(db_path)
    con.execute("UPDATE slots SET status = 'OCCUPIED' WHERE category = 'CAR' AND slot_id != 'S10'")
    con.commit()
    con.close()

    responses = parallel_entries(app, [f"CAR000{n}" for n in range(5)])
    codes = sorted(r.status_code for r in responses)
    assert codes == [201, 409, 409, 409, 409]
    for response in responses:
        if response.status_code == 409:
            assert response.get_json()["error"] == "NO_SLOT_AVAILABLE"


def test_ten_parallel_entries_get_ten_different_slots(app, db_path):
    responses = parallel_entries(app, [f"CAR00{n:02d}" for n in range(10)])
    assert [r.status_code for r in responses] == [201] * 10
    assert len({r.get_json()["slot_id"] for r in responses}) == 10
    assert len({r.get_json()["ticket_id"] for r in responses}) == 10

    con = sqlite3.connect(db_path)
    assert con.execute("SELECT COUNT(*) FROM slots WHERE status = 'OCCUPIED'").fetchone() == (10,)
    con.close()


def test_database_refuses_two_active_tickets_on_one_slot(app, db_path):
    response = app.test_client().post("/api/parking/entry",
                                      json={"plate": "CAR0001", "vehicle_type": "CAR"})
    ticket = response.get_json()
    con = sqlite3.connect(db_path)
    with pytest.raises(sqlite3.IntegrityError):
        con.execute("INSERT INTO tickets (ticket_id, vehicle_id, slot_id, entry_time)"
                    " VALUES ('X', 1, ?, '2026-01-01 00:00:00')", (ticket["slot_id"],))
    con.close()


def test_two_payments_for_one_ticket_only_one_succeeds(app, db_path):
    ticket_id = app.test_client().post("/api/parking/entry",
                                       json={"plate": "CAR0001", "vehicle_type": "CAR"}
                                       ).get_json()["ticket_id"]

    def pay(_):
        return app.test_client().post("/api/payment/mock", json={"ticket_id": ticket_id})
    with ThreadPoolExecutor(max_workers=2) as pool:
        codes = sorted(r.status_code for r in pool.map(pay, range(2)))
    assert codes == [200, 409]

    con = sqlite3.connect(db_path)
    assert con.execute("SELECT COUNT(*) FROM payments").fetchone() == (1,)
    con.close()


@pytest.mark.skipif("CI" in os.environ, reason="timing is measured on the reference "
                                              "machine; shared CI runners are too variable")
def test_entry_and_exit_p95_under_one_second(app):
    client = app.test_client()
    timings = []
    for n in range(20):
        started = time.perf_counter()
        ticket = client.post("/api/parking/entry",
                             json={"plate": f"CAR{n:04d}", "vehicle_type": "CAR"}).get_json()
        client.post("/api/payment/mock", json={"ticket_id": ticket["ticket_id"]})
        timings.append(time.perf_counter() - started)
    assert sorted(timings)[18] < 1.0


def test_dashboard_polls_at_least_every_500_ms():
    # NFR-PERF-02: the page refreshes itself, so a change shows within 1 s
    script = Path(__file__).parent.parent / "vps" / "static" / "grid.js"
    assert "}, 500);" in script.read_text(encoding="utf-8")
