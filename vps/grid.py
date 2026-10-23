"""Facility grid model and BFS smart slot assignment (REQ-NAV-01, REQ-NAV-02)."""
from collections import deque

MAX_SIZE = 10
PASSABLE = {"ROAD", "ENTRANCE", "EXIT"}
MOVES = ((-1, 0), (1, 0), (0, -1), (0, 1))


class GridError(ValueError):
    pass


def load_grid(db):
    """Read the layout from the database as a list of rows of (cell_type, slot_id)."""
    rows = db.execute(
        "SELECT row_no, col_no, cell_type, slot_id FROM grid_cells ORDER BY row_no, col_no"
    ).fetchall()
    if not rows:
        raise GridError("The facility layout is empty")
    n_rows = max(r["row_no"] for r in rows) + 1
    n_cols = max(r["col_no"] for r in rows) + 1
    grid = [[("WALL", None)] * n_cols for _ in range(n_rows)]
    for r in rows:
        grid[r["row_no"]][r["col_no"]] = (r["cell_type"], r["slot_id"])
    validate_grid(grid)
    return grid


def validate_grid(grid):
    if not grid or len(grid) > MAX_SIZE or any(len(row) > MAX_SIZE for row in grid):
        raise GridError(f"The grid must be between 1 x 1 and {MAX_SIZE} x {MAX_SIZE}")
    kinds = [cell[0] for row in grid for cell in row]
    if kinds.count("ENTRANCE") != 1:
        raise GridError("The grid must have exactly one entrance")


def find_cell(grid, cell_type):
    for r, row in enumerate(grid):
        for c, (kind, _) in enumerate(row):
            if kind == cell_type:
                return r, c
    raise GridError(f"The grid has no {cell_type.lower()} cell")


def bfs(grid, start):
    """Breadth-first search from start over road cells.

    Returns (distance, parent) dictionaries keyed by (row, col). Slots can be
    reached but not driven through, and walls block movement.
    """
    distance = {start: 0}
    parent = {start: None}
    queue = deque([start])
    while queue:
        r, c = queue.popleft()
        if grid[r][c][0] == "SLOT" and (r, c) != start:
            continue
        for dr, dc in MOVES:
            nr, nc = r + dr, c + dc
            if not (0 <= nr < len(grid) and 0 <= nc < len(grid[nr])):
                continue
            if (nr, nc) in distance:
                continue
            if grid[nr][nc][0] in PASSABLE or grid[nr][nc][0] == "SLOT":
                distance[(nr, nc)] = distance[(r, c)] + 1
                parent[(nr, nc)] = (r, c)
                queue.append((nr, nc))
    return distance, parent


def build_path(parent, goal):
    """Walk the parent links back from goal and return the path start -> goal."""
    path = []
    cell = goal
    while cell is not None:
        path.append(cell)
        cell = parent[cell]
    return path[::-1]


def slot_number(slot_id):
    return int(slot_id.lstrip("S"))


def nearest_slot(grid, vacant_slot_ids, start_from="ENTRANCE"):
    """Pick the vacant slot with the shortest BFS path; ties go to the lower slot number.

    Returns (slot_id, path) or None when no listed slot can be reached.
    """
    start = find_cell(grid, start_from)
    distance, parent = bfs(grid, start)
    candidates = []
    for r, row in enumerate(grid):
        for c, (kind, slot_id) in enumerate(row):
            if kind == "SLOT" and slot_id in vacant_slot_ids and (r, c) in distance:
                candidates.append((distance[(r, c)], slot_number(slot_id), slot_id, (r, c)))
    if not candidates:
        return None
    _, _, slot_id, cell = min(candidates)
    return slot_id, build_path(parent, cell)


# Which slot category each vehicle may use
CATEGORY_FOR = {"TWO_WHEELER": "TWO_WHEELER", "CAR": "CAR", "EV": "EV"}


def assign_slot(db, vehicle_type, accessible=False, start_from="ENTRANCE"):
    """Choose a slot for a new vehicle. Returns (slot_id, path) or None if none is free."""
    category = "ACCESSIBLE" if accessible else CATEGORY_FOR[vehicle_type]
    vacant = {
        r["slot_id"]
        for r in db.execute(
            "SELECT slot_id FROM slots WHERE category = ? AND status = 'VACANT'", (category,)
        )
    }
    if not vacant:
        return None
    return nearest_slot(load_grid(db), vacant, start_from)
