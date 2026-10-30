"""Slot categories, live slot grid and vacant counts (REQ-SLOT-01 to 03)."""
from flask import Blueprint, jsonify, render_template, request

from .audit import record_action
from .auth import login_required, role_required
from .db import get_db
from .grid import load_grid

bp = Blueprint("slots", __name__)

CATEGORY_LABELS = {
    "TWO_WHEELER": "Two-Wheeler",
    "CAR": "Car",
    "ACCESSIBLE": "Accessible",
    "EV": "EV",
}
STATUSES = ("VACANT", "OCCUPIED", "RESERVED")


def slot_summary(db, category=None, status=None):
    """Every slot, the vacant count per category, and the grid with each slot's status."""
    slots = [dict(r) for r in db.execute(
        "SELECT slot_id, category, status FROM slots ORDER BY slot_id")]
    by_id = {s["slot_id"]: s for s in slots}

    counts = {key: {"label": label, "total": 0, "vacant": 0}
              for key, label in CATEGORY_LABELS.items()}
    for s in slots:
        counts[s["category"]]["total"] += 1
        counts[s["category"]]["vacant"] += s["status"] == "VACANT"

    grid = []
    for row in load_grid(db):
        cells = []
        for kind, slot_id in row:
            cell = {"type": kind}
            if slot_id:
                cell.update(by_id[slot_id])
            cells.append(cell)
        grid.append(cells)

    if category:
        slots = [s for s in slots if s["category"] == category.upper()]
    if status:
        slots = [s for s in slots if s["status"] == status.upper()]
    return {"slots": slots, "counts": counts, "grid": grid}


def set_reserved(db, slot_id, reserved):
    """Reserve a vacant slot or release a reserved one. Returns (body, http_status)."""
    slot = db.execute("SELECT status FROM slots WHERE slot_id = ?", (slot_id,)).fetchone()
    if slot is None:
        return {"error": "SLOT_NOT_FOUND", "message": f"No slot {slot_id}."}, 404
    old, new = ("VACANT", "RESERVED") if reserved else ("RESERVED", "VACANT")
    changed = db.execute(
        "UPDATE slots SET status = ? WHERE slot_id = ? AND status = ?", (new, slot_id, old)
    ).rowcount
    if not changed:
        return {"error": "SLOT_NOT_" + old,
                "message": f"{slot_id} is {slot['status'].lower()}, not {old.lower()}."}, 409
    record_action(db, f"RESERVE_SLOT {slot_id}", old, new)
    db.commit()
    return {"slot_id": slot_id, "status": new}, 200


@bp.get("/api/slots")
@login_required
def api_slots():
    """Return the slots, counts and grid for the live view."""
    return jsonify(slot_summary(get_db(), request.args.get("category"),
                                request.args.get("status")))


@bp.post("/api/slots/<slot_id>/reserve")
@role_required("ADMIN")
def api_reserve(slot_id):
    """Reserve or release a slot through the API."""
    data = request.get_json(silent=True) or {}
    body, status = set_reserved(get_db(), slot_id.upper(), bool(data.get("reserved", True)))
    return jsonify(body), status


@bp.get("/slots")
@login_required
def slots_page():
    """Show the slot grid page."""
    return render_template("slots.html")
