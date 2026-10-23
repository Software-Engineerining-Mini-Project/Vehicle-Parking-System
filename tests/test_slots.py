import pytest

from vps import create_app


@pytest.fixture
def client(tmp_path):
    app = create_app({"TESTING": True, "LOGIN_DISABLED": True,
                      "DATABASE": str(tmp_path / "test.db")})
    return app.test_client()


def slots(client, **params):
    response = client.get("/api/slots", query_string=params)
    assert response.status_code == 200
    return response.get_json()


def test_every_slot_has_one_category_and_a_status(client):
    data = slots(client)
    assert len(data["slots"]) == 20
    for slot in data["slots"]:
        assert slot["category"] in {"TWO_WHEELER", "CAR", "ACCESSIBLE", "EV"}
        assert slot["status"] in {"VACANT", "OCCUPIED", "RESERVED"}


def test_vacant_counts_per_category(client):
    counts = slots(client)["counts"]
    assert {k: (v["vacant"], v["total"]) for k, v in counts.items()} == {
        "TWO_WHEELER": (4, 4), "CAR": (10, 10), "ACCESSIBLE": (2, 2), "EV": (4, 4)}
    assert counts["TWO_WHEELER"]["label"] == "Two-Wheeler"


def test_grid_matches_the_layout(client):
    grid = slots(client)["grid"]
    assert len(grid) == 6 and all(len(row) == 8 for row in grid)
    assert grid[1][0]["type"] == "ENTRANCE"
    assert grid[0][1] == {"type": "SLOT", "slot_id": "S01", "category": "ACCESSIBLE",
                          "status": "VACANT"}


def test_entry_and_exit_change_status_immediately(client):
    ticket = client.post("/api/parking/entry",
                         json={"plate": "KA01AB1234", "vehicle_type": "CAR"}).get_json()
    data = slots(client)
    assert {s["slot_id"]: s["status"] for s in data["slots"]}[ticket["slot_id"]] == "OCCUPIED"
    assert data["counts"]["CAR"]["vacant"] == 9


def test_filter_by_category_and_status(client):
    assert len(slots(client, category="ev")["slots"]) == 4
    client.post("/api/parking/entry", json={"plate": "EV0001", "vehicle_type": "EV"})
    assert [s["category"] for s in slots(client, status="occupied")["slots"]] == ["EV"]


def test_reserve_and_release_a_slot(client):
    response = client.post("/api/slots/S05/reserve", json={"reserved": True})
    assert response.status_code == 200 and response.get_json()["status"] == "RESERVED"
    assert slots(client)["counts"]["CAR"]["vacant"] == 9

    response = client.post("/api/slots/S05/reserve", json={"reserved": False})
    assert response.get_json()["status"] == "VACANT"


def test_reserved_slot_is_not_assigned(client):
    client.post("/api/slots/S04/reserve", json={"reserved": True})
    ticket = client.post("/api/parking/entry",
                         json={"plate": "KA01AB1234", "vehicle_type": "CAR"}).get_json()
    assert ticket["slot_id"] != "S04"


def test_occupied_or_unknown_slot_cannot_be_reserved(client):
    ticket = client.post("/api/parking/entry",
                         json={"plate": "KA01AB1234", "vehicle_type": "CAR"}).get_json()
    response = client.post(f"/api/slots/{ticket['slot_id']}/reserve", json={"reserved": True})
    assert response.status_code == 409
    assert client.post("/api/slots/S99/reserve", json={}).status_code == 404


@pytest.mark.parametrize("path", ["/", "/slots", "/entry"])
def test_pages_include_the_live_grid(client, path):
    page = client.get(path).get_data(as_text=True)
    assert "data-slot-panel" in page and "grid.js" in page


def test_entry_page_highlights_assigned_slot(client):
    page = client.post("/entry", data={"plate": "KA01AB1234", "vehicle_type": "CAR"}
                       ).get_data(as_text=True)
    assert 'data-highlight="S04"' in page
