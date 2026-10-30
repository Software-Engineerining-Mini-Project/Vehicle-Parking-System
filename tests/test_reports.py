import csv
import io
import os
import sqlite3
import time
from datetime import date, timedelta

import pytest

from vps import create_app


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "test.db")


@pytest.fixture
def client(db_path):
    client = create_app({"TESTING": True, "DATABASE": db_path}).test_client()
    client.post("/login", data={"username": "admin", "password": "Admin@123"})
    client.post("/admin/demo-data", json={})
    return client


def sql_total(db_path):
    con = sqlite3.connect(db_path)
    total = con.execute("SELECT SUM(amount) FROM payments WHERE status = 'SUCCESS'").fetchone()[0]
    con.close()
    return total


def test_revenue_matches_the_database(client, db_path):
    data = client.get("/api/reports/revenue").get_json()
    assert data["total_revenue"] == sql_total(db_path) > 0
    assert sum(r["revenue"] for r in data["rows"]) == data["total_revenue"]


@pytest.mark.parametrize("period", ["daily", "weekly", "monthly"])
def test_every_period_adds_up_to_the_same_total(client, db_path, period):
    data = client.get(f"/api/reports/revenue?period={period}").get_json()
    assert sum(r["revenue"] for r in data["rows"]) == sql_total(db_path)


def test_number_of_rows_per_period(client):
    start, end = date(2026, 1, 1), date(2026, 3, 15)
    query = f"start={start}&end={end}"
    assert len(client.get(f"/api/reports/occupancy?{query}&period=daily").get_json()["rows"]) == 74
    weekly = client.get(f"/api/reports/occupancy?{query}&period=weekly").get_json()
    assert len(weekly["rows"]) == 11
    assert len(client.get(f"/api/reports/occupancy?{query}&period=monthly").get_json()["rows"]) == 3


def test_occupancy_of_a_known_stay(db_path):
    client = create_app({"TESTING": True, "DATABASE": db_path}).test_client()
    client.post("/login", data={"username": "admin", "password": "Admin@123"})
    con = sqlite3.connect(db_path)
    con.execute("INSERT INTO vehicles (plate_number, vehicle_type) VALUES ('CAR0001', 'CAR')")
    # One of 20 slots used for 12 of 24 hours is 2.5 %
    con.execute("INSERT INTO tickets"
                " (ticket_id, vehicle_id, slot_id, entry_time, exit_time, status)"
                " VALUES ('T1', 1, 'S01', '2026-01-10 09:00:00', '2026-01-10 21:00:00', 'CLOSED')")
    con.commit()
    con.close()
    data = client.get("/api/reports/occupancy?start=2026-01-10&end=2026-01-10").get_json()
    assert data["rows"] == [{"period": "2026-01-10", "occupancy_percent": 2.5}]
    assert data["peak_hour"] == "09:00"
    car = [u for u in data["utilisation"] if u["category"] == "Car"][0]
    assert car["utilisation_percent"] == 5.0


def test_peak_hour_and_utilisation_are_shown(client):
    page = client.get("/reports").get_data(as_text=True)
    assert "Peak hour" in page and "Average utilisation" in page and "Two-Wheeler" in page


def test_csv_figures_match_the_screen(client):
    data = client.get("/api/reports/revenue").get_json()
    occupancy = client.get("/api/reports/occupancy").get_json()
    body = client.get("/reports/export.csv").get_data(as_text=True)
    rows = list(csv.reader(io.StringIO(body)))
    table = {r[0]: r for r in rows}
    for row in data["rows"]:
        assert int(table[row["period"]][2]) == row["revenue"]
    for row in occupancy["rows"]:
        assert float(table[row["period"]][1]) == row["occupancy_percent"]
    assert int(table["Total revenue (Rs.)"][2]) == data["total_revenue"]
    assert table["Peak hour"][1] == occupancy["peak_hour"]


def test_pdf_export_is_a_pdf(client):
    response = client.get("/reports/export.pdf")
    assert response.status_code == 200
    assert response.mimetype == "application/pdf"
    assert response.data.startswith(b"%PDF")


@pytest.mark.skipif("CI" in os.environ, reason="timing is checked on the reference machine")
def test_30_day_report_within_3_seconds(client):
    started = time.perf_counter()
    assert client.get("/reports").status_code == 200
    assert time.perf_counter() - started < 3


@pytest.mark.parametrize("query", ["start=nope", "start=2026-13-01", "period=hourly",
                                   "start=2026-02-02&end=2026-02-01",
                                   "start=2020-01-01&end=2026-01-01"])
def test_invalid_input_gets_a_clear_message(client, query):
    response = client.get(f"/reports?{query}")
    assert response.status_code == 400
    assert 'class="error"' in response.get_data(as_text=True)
    assert client.get(f"/reports/export.csv?{query}").status_code == 400


def test_attendant_cannot_see_reports(db_path):
    client = create_app({"TESTING": True, "DATABASE": db_path}).test_client()
    client.post("/login", data={"username": "attendant", "password": "Attend@123"})
    for path in ["/reports", "/reports/export.csv", "/reports/export.pdf",
                 "/api/reports/occupancy", "/api/reports/revenue"]:
        assert client.get(path).status_code == 403, path
    assert ">Reports<" not in client.get("/").get_data(as_text=True)


def test_future_days_do_not_lower_occupancy(client):
    tomorrow = date.today() + timedelta(days=1)
    data = client.get(f"/api/reports/occupancy?start={tomorrow}&end={tomorrow}").get_json()
    assert data["rows"][0]["occupancy_percent"] == 0.0
