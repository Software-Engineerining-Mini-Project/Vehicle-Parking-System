"""Demo support: synthetic history, the Demo Clock and overstay flags.

REQ-PRED-04, OR-04, BR-03.
"""
import random
from datetime import timedelta

from flask import Blueprint, jsonify, redirect, request, url_for

from . import clock, fees
from .audit import record_action
from .auth import role_required
from .db import get_db

bp = Blueprint("demo", __name__)

SYNTHETIC_RECORDS = 200
HISTORY_DAYS = 14
CLOCK_STEPS = {"5min": 5, "1h": 60, "1day": 1440}
OFFSET_KEY = "demo_clock_offset_min"
SYNTHETIC_PREFIX = "SYN"

# Busier in the morning and evening so the reports show a clear peak hour
HOUR_WEIGHTS = {8: 6, 9: 12, 10: 9, 11: 6, 12: 5, 13: 5, 14: 4, 15: 4, 16: 5, 17: 8, 18: 10, 19: 5}
VEHICLE_MIX = [("CAR", "CAR", 60), ("TWO_WHEELER", "TWO_WHEELER", 20), ("EV", "EV", 15),
               ("CAR", "ACCESSIBLE", 5)]


class AlreadySeeded(Exception):
    """The synthetic history has already been loaded."""


def history_is_seeded(db):
    """Return True if the synthetic records are already in the database."""
    return db.execute("SELECT 1 FROM vehicles WHERE plate_number LIKE ? LIMIT 1",
                      (SYNTHETIC_PREFIX + "%",)).fetchone() is not None


def _free_slot(free_at, slots, entry):
    """Return a slot that is free at the entry time, or the one that frees up first."""
    for slot_id in slots:
        if free_at[slot_id] <= entry:
            return slot_id, entry
    slot_id = min(slots, key=lambda s: free_at[s])
    return slot_id, free_at[slot_id]


def seed_history(db, count=SYNTHETIC_RECORDS, days=HISTORY_DAYS):
    """Insert closed tickets, payments and dwell records over the previous days.

    A fixed random seed keeps the demo figures the same on every machine. Slots
    are never double-booked in the generated history.
    """
    if history_is_seeded(db):
        raise AlreadySeeded()

    rng = random.Random(42)
    today = clock.now(db).replace(hour=0, minute=0, second=0)
    hours = list(HOUR_WEIGHTS)
    entries = sorted(
        today - timedelta(days=rng.randint(1, days))
        + timedelta(hours=rng.choices(hours, list(HOUR_WEIGHTS.values()))[0],
                    minutes=rng.randint(0, 59), seconds=rng.randint(0, 59))
        for _ in range(count)
    )

    by_category = {}
    for row in db.execute("SELECT slot_id, category FROM slots ORDER BY slot_id"):
        by_category.setdefault(row["category"], []).append(row["slot_id"])
    free_at = {s: entries[0] for slots in by_category.values() for s in slots}
    issued = {}

    for n, wanted_entry in enumerate(entries, start=1):
        vehicle_type, category, _ = rng.choices(VEHICLE_MIX, [m[2] for m in VEHICLE_MIX])[0]
        slot_id, entered = _free_slot(free_at, by_category[category], wanted_entry)
        minutes = rng.randint(20, 240)
        left = entered + timedelta(minutes=minutes, seconds=rng.randint(0, 59))
        free_at[slot_id] = left

        day = entered.strftime("%Y%m%d")
        issued[day] = issued.get(day, 0) + 1
        ticket_id = f"VPS-{day}-{issued[day]:04d}"
        vehicle_id = db.execute(
            "INSERT INTO vehicles (plate_number, vehicle_type) VALUES (?, ?)",
            (f"{SYNTHETIC_PREFIX}{n:04d}", vehicle_type),
        ).lastrowid
        db.execute(
            "INSERT INTO tickets (ticket_id, vehicle_id, slot_id, entry_time, exit_time, status)"
            " VALUES (?, ?, ?, ?, ?, 'CLOSED')",
            (ticket_id, vehicle_id, slot_id, clock.to_text(entered), clock.to_text(left)),
        )
        rate, grace = fees.load_tariff(db, vehicle_type)
        db.execute(
            "INSERT INTO payments (ticket_id, amount, status, paid_at)"
            " VALUES (?, ?, 'SUCCESS', ?)",
            (ticket_id, fees.calculate_fee((left - entered).total_seconds(), rate, grace),
             clock.to_text(left)),
        )
        db.execute(
            "INSERT INTO dwell_history (vehicle_type, entry_time, exit_time, duration_min)"
            " VALUES (?, ?, ?, ?)",
            (vehicle_type, clock.to_text(entered), clock.to_text(left), minutes),
        )
    record_action(db, "SEED_DEMO_DATA", None, f"{count} records over {days} days")
    db.commit()
    return count


def advance_clock(db, minutes):
    """Move application time forward and return the new offset in minutes."""
    row = db.execute("SELECT value FROM settings WHERE key = ?", (OFFSET_KEY,)).fetchone()
    old = int(row["value"]) if row else 0
    new = old + minutes
    db.execute(
        "INSERT INTO settings (key, value) VALUES (?, ?)"
        " ON CONFLICT (key) DO UPDATE SET value = excluded.value",
        (OFFSET_KEY, str(new)),
    )
    record_action(db, "ADVANCE_DEMO_CLOCK", str(old), str(new))
    db.commit()
    return new


def overstay_tickets(db):
    """Active tickets parked for longer than the overstay limit (BR-03, informational)."""
    limit = int(db.execute(
        "SELECT value FROM settings WHERE key = 'overstay_hours'").fetchone()["value"])
    now = clock.now(db)
    flagged = []
    for row in db.execute(
        "SELECT t.ticket_id, v.plate_number, t.slot_id, t.entry_time FROM tickets t"
        " JOIN vehicles v ON v.vehicle_id = t.vehicle_id WHERE t.status = 'ACTIVE'"
        " ORDER BY t.entry_time"
    ):
        parked = now - clock.from_text(row["entry_time"])
        if parked > timedelta(hours=limit):
            flagged.append({**dict(row), "parked": fees.format_duration(parked.total_seconds())})
    return flagged


@bp.app_context_processor
def inject_demo_helpers():
    """Give the dashboard template the app time, seed state and overstay list."""
    return {
        "app_time": lambda: clock.to_text(clock.now(get_db())),
        "history_seeded": lambda: history_is_seeded(get_db()),
        "overstays": lambda: overstay_tickets(get_db()),
    }


@bp.post("/admin/demo-data")
@role_required("ADMIN")
def seed_page():
    """Load the synthetic history; loading it twice is refused."""
    try:
        count = seed_history(get_db())
    except AlreadySeeded:
        if request.is_json:
            return jsonify(error="ALREADY_SEEDED", message="Demo data is already loaded."), 409
        return redirect(url_for("index"))
    if request.is_json:
        return jsonify(seeded=count), 201
    return redirect(url_for("index"))


@bp.post("/admin/demo-clock")
@role_required("ADMIN")
def clock_page():
    """Advance the Demo Clock by one of the allowed steps."""
    data = request.get_json(silent=True) or request.form
    minutes = CLOCK_STEPS.get(data.get("step"))
    if minutes is None:
        return jsonify(error="INVALID_STEP", message="Step must be 5min, 1h or 1day."), 400
    offset = advance_clock(get_db(), minutes)
    if request.is_json:
        return jsonify(offset_minutes=offset, app_time=clock.to_text(clock.now(get_db())))
    return redirect(url_for("index"))
