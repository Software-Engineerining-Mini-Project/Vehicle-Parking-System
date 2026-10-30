"""Demo data loaded on first run (SRS OR-01)."""
import os

from werkzeug.security import generate_password_hash

# Default 6 x 8 facility layout (OR-01). Numbers are slot IDs; the numbering is the one
# the Test Plan uses: S01-S10 Car, S11-S14 Two-Wheeler, S15-S16 Accessible, S17-S20 EV.
#   # wall   . road   N entrance   X exit
LAYOUT = [
    "#  01 02 03 04 05 06 #",
    "N  .  .  .  .  .  .  .",
    "#  11 12 13 14 #  #  .",
    "#  20 19 18 17 #  #  .",
    "#  .  .  .  .  .  .  X",
    "#  16 15 07 08 09 10 #",
]

OTHER_CELLS = {"#": "WALL", ".": "ROAD", "N": "ENTRANCE", "X": "EXIT"}


def slot_category(number):
    """Return the default category of a slot number."""
    if number <= 10:
        return "CAR"
    if number <= 14:
        return "TWO_WHEELER"
    if number <= 16:
        return "ACCESSIBLE"
    return "EV"


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
    for row_no, line in enumerate(LAYOUT):
        for col_no, token in enumerate(line.split()):
            if token.isdigit():
                slot_id = f"S{token}"
                db.execute(
                    "INSERT INTO slots (slot_id, category) VALUES (?, ?)",
                    (slot_id, slot_category(int(token))),
                )
                cell = ("SLOT", slot_id)
            else:
                cell = (OTHER_CELLS[token], None)
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
        ("admin", os.environ.get("VPS_ADMIN_PASSWORD", "Admin@123"), "ADMIN"),
        ("attendant", os.environ.get("VPS_ATTENDANT_PASSWORD", "Attend@123"), "ATTENDANT"),
    ]
    for username, password, role in accounts:
        db.execute(
            "INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)",
            (username, generate_password_hash(password), role),
        )
