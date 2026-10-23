import sqlite3
import time

import pytest

from vps import create_app
from vps.grid import (GridError, assign_slot, bfs, build_path, load_grid, nearest_slot,
                      validate_grid)


def make_grid(lines):
    """Build a grid from text: # wall, . road, N entrance, X exit, digits are slots."""
    kinds = {"#": "WALL", ".": "ROAD", "N": "ENTRANCE", "X": "EXIT"}
    return [[("SLOT", f"S{int(ch):02d}") if ch.isdigit() else (kinds[ch], None) for ch in line]
            for line in lines]


@pytest.fixture
def db(tmp_path):
    path = str(tmp_path / "test.db")
    app = create_app({"TESTING": True, "DATABASE": path})
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    yield app, con
    con.close()


def test_path_goes_round_walls():
    grid = make_grid([
        "N.#1",
        ".#..",
        "....",
    ])
    slot_id, path = nearest_slot(grid, {"S01"})
    assert slot_id == "S01"
    assert path[0] == (0, 0) and path[-1] == (0, 3)
    assert len(path) - 1 == 7
    assert all(grid[r][c][0] != "WALL" for r, c in path)


def test_nearest_slot_wins():
    grid = make_grid(["N...2", "1####"])
    assert nearest_slot(grid, {"S01", "S02"})[0] == "S01"


def test_tie_goes_to_lower_slot_number():
    grid = make_grid(["#3#", "N..", "#1#"])
    slot_id, path = nearest_slot(grid, {"S01", "S03"})
    assert slot_id == "S01"
    assert len(path) - 1 == 2


def test_cannot_drive_through_a_slot():
    grid = make_grid(["N12"])
    distance, _ = bfs(grid, (0, 0))
    assert (0, 1) in distance
    assert (0, 2) not in distance
    assert nearest_slot(grid, {"S02"}) is None


def test_only_vacant_listed_slots_are_considered():
    grid = make_grid(["N12.", "...."])
    assert nearest_slot(grid, {"S02"})[0] == "S02"
    assert nearest_slot(grid, set()) is None


def test_search_can_start_from_exit():
    grid = make_grid(["N..X", "1##2"])
    assert nearest_slot(grid, {"S01", "S02"}, start_from="EXIT")[0] == "S02"


def test_build_path_returns_start_to_goal():
    parent = {(0, 0): None, (0, 1): (0, 0), (1, 1): (0, 1)}
    assert build_path(parent, (1, 1)) == [(0, 0), (0, 1), (1, 1)]


def test_grid_larger_than_10_by_10_is_rejected():
    with pytest.raises(GridError):
        validate_grid(make_grid(["N" + "." * 10]))


def test_grid_needs_one_entrance():
    with pytest.raises(GridError):
        validate_grid(make_grid(["..1"]))


def test_bfs_is_fast_on_largest_grid():
    # NFR-PERF-04: within 500 ms for 50+ nodes; a full 10 x 10 grid has 100
    lines = ["N" + "." * 9] + ["." * 10 for _ in range(8)] + ["." * 9 + "9"]
    grid = make_grid(lines)
    started = time.perf_counter()
    for _ in range(100):
        nearest_slot(grid, {"S09"})
    assert (time.perf_counter() - started) / 100 < 0.5


def test_default_layout_loads_from_database(db):
    _, con = db
    grid = load_grid(con)
    assert len(grid) == 6 and len(grid[0]) == 8
    assert sum(cell[0] == "SLOT" for row in grid for cell in row) == 20


def test_assign_slot_on_default_layout(db):
    _, con = db
    # S01 and S07 are both 2 steps from the entrance; the lower number wins
    assert assign_slot(con, "CAR", accessible=True)[0] == "S01"
    assert assign_slot(con, "CAR")[0] == "S04"
    assert assign_slot(con, "TWO_WHEELER")[0] == "S02"
    # EV bays are reached from the far road, so S20 (nearest the exit lane) is closest
    assert assign_slot(con, "EV")[0] == "S20"


def test_assign_slot_skips_occupied_and_reports_full(db):
    _, con = db
    con.execute("UPDATE slots SET status = 'OCCUPIED' WHERE slot_id = 'S04'")
    assert assign_slot(con, "CAR")[0] == "S10"
    con.execute("UPDATE slots SET status = 'OCCUPIED' WHERE category = 'EV'")
    assert assign_slot(con, "EV") is None
