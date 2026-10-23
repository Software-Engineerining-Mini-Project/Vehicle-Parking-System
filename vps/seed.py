"""Demo data loaded on first run (SRS OR-01)."""
import os

from werkzeug.security import generate_password_hash

# Default 6 x 8 facility layout.
#   # wall   . road   N entrance   X exit
#   C car   T two-wheeler   A accessible   V EV
LAYOUT = [
    "#ATTCCC#",
    "N.......",
    "#ATTC##.",
    "#CCCC##.",
    "#......X",
    "#CCVVVV#",
]

SLOT_CATEGORIES = {"C": "CAR", "T": "TWO_WHEELER", "A": "ACCESSIBLE", "V": "EV"}
OTHER_CELLS = {"#": "WALL", ".": "ROAD", "N": "ENTRANCE", "X": "EXIT"}

DEFAULT_SETTINGS = {
    "rate_two_wheeler": "20",
    "rate_car": "40",
    "rate_ev": "50",
    "grace_minutes": "5",
    "overstay_hours": "24",
    "demo_clock_offset_min": "0",
}


def seed_demo_data(db):
    """Insert the default layout, slots, settings and the two demo accounts."""
    slot_no = 0
    for row_no, line in enumerate(LAYOUT):
        for col_no, char in enumerate(line):
            if char in SLOT_CATEGORIES:
                slot_no += 1
                slot_id = f"S{slot_no:02d}"
                db.execute(
                    "INSERT INTO slots (slot_id, category) VALUES (?, ?)",
                    (slot_id, SLOT_CATEGORIES[char]),
                )
                cell = ("SLOT", slot_id)
            else:
                cell = (OTHER_CELLS[char], None)
            db.execute(
                "INSERT INTO grid_cells (row_no, col_no, cell_type, slot_id)"
                " VALUES (?, ?, ?, ?)",
                (row_no, col_no, *cell),
            )

    db.executemany(
        "INSERT INTO settings (key, value) VALUES (?, ?)", DEFAULT_SETTINGS.items()
    )

    # Demo passwords can be overridden through environment variables.
    accounts = [
        ("admin", os.environ.get("VPS_ADMIN_PASSWORD", "admin123"), "ADMIN"),
        ("attendant", os.environ.get("VPS_ATTENDANT_PASSWORD", "attend123"), "ATTENDANT"),
    ]
    for username, password, role in accounts:
        db.execute(
            "INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)",
            (username, generate_password_hash(password), role),
        )
