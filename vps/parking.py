"""Vehicle entry and exit (REQ-LOG-01 to 04, REQ-PAY-01)."""
import re
import sqlite3

import qrcode
import qrcode.image.svg
from flask import Blueprint, Response, abort, jsonify, render_template, request

from . import clock, fees
from .auth import login_required
from .db import get_db
from .grid import assign_slot
from .prediction import next_vacancy_message
from .slots import CATEGORY_LABELS

bp = Blueprint("parking", __name__)

PLATE_PATTERN = re.compile(r"^[A-Z0-9]{4,10}$")
TICKET_PATTERN = re.compile(r"^VPS-\d{8}-\d{4}$")
SLOT_PATTERN = re.compile(r"^S\d{2,3}$")
VEHICLE_TYPES = {"TWO_WHEELER": "Two-Wheeler", "CAR": "Car", "EV": "EV"}
START_POINTS = {"ENTRANCE": "entrance", "EXIT": "exit"}


class ParkingError(Exception):
    """A request that cannot be completed, with the HTTP status and error code to return."""

    def __init__(self, status, code, message):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


def normalise_plate(raw):
    """Remove spaces, upper-case, and check 4 to 10 letters or digits."""
    plate = re.sub(r"\s+", "", raw or "").upper()
    if not PLATE_PATTERN.match(plate):
        raise ParkingError(400, "INVALID_PLATE",
                           "Plate number must be 4 to 10 letters or digits.")
    return plate


def is_checked(value):
    return str(value).lower() in {"1", "true", "on", "yes"}


def validate_vehicle(raw_plate, vehicle_type, start_from):
    """Check the entry fields and return the normalised plate."""
    plate = normalise_plate(raw_plate)
    if vehicle_type not in VEHICLE_TYPES:
        raise ParkingError(400, "INVALID_VEHICLE_TYPE",
                           "Vehicle type must be Two-Wheeler, Car or EV.")
    if start_from not in START_POINTS:
        raise ParkingError(400, "INVALID_START_POINT", "Start point must be Entrance or Exit.")
    return plate


def no_slot_error(db, vehicle_type, accessible):
    """Build the refusal for a full category, with the predicted wait (REQ-SLOT-04)."""
    category = "ACCESSIBLE" if accessible else vehicle_type
    return ParkingError(409, "NO_SLOT_AVAILABLE",
                        f"No {CATEGORY_LABELS[category]} slot available. "
                        f"{next_vacancy_message(db, category)}")


def preview_route(db, raw_plate, vehicle_type, accessible=False, start_from="ENTRANCE"):
    """Show which slot and route would be given, without changing anything (REQ-NAV-03)."""
    validate_vehicle(raw_plate, vehicle_type, start_from)
    assignment = assign_slot(db, vehicle_type, accessible, start_from)
    if assignment is None:
        raise no_slot_error(db, vehicle_type, accessible)
    slot_id, path = assignment
    return {"slot_id": slot_id, "path": [list(cell) for cell in path], "start_from": start_from}


def register_entry(db, raw_plate, vehicle_type, accessible=False, start_from="ENTRANCE",
                   target_slot=None):
    """Validate the vehicle, assign the nearest suitable slot and open a ticket.

    target_slot is the slot from the route preview. If it was taken or its path was
    blocked in the meantime, the next best slot is given and reported (REQ-NAV-04).
    """
    plate = validate_vehicle(raw_plate, vehicle_type, start_from)
    if not (isinstance(target_slot, str) and SLOT_PATTERN.match(target_slot)):
        target_slot = None

    # Lock the database for writing so two entries cannot take the same slot
    db.execute("BEGIN IMMEDIATE")
    try:
        active = db.execute(
            "SELECT t.ticket_id FROM tickets t JOIN vehicles v ON v.vehicle_id = t.vehicle_id"
            " WHERE v.plate_number = ? AND t.status = 'ACTIVE'", (plate,)
        ).fetchone()
        if active:
            raise ParkingError(409, "DUPLICATE_ACTIVE_TICKET",
                               f"{plate} is already parked on ticket {active['ticket_id']}.")

        assignment = assign_slot(db, vehicle_type, accessible, start_from, target_slot)
        if assignment is None:
            raise no_slot_error(db, vehicle_type, accessible)
        slot_id, path = assignment

        entered = clock.now(db)
        prefix = entered.strftime("VPS-%Y%m%d-")
        issued_today = db.execute(
            "SELECT COUNT(*) FROM tickets WHERE ticket_id LIKE ?", (prefix + "%",)
        ).fetchone()[0]
        ticket_id = f"{prefix}{issued_today + 1:04d}"

        db.execute(
            "INSERT INTO vehicles (plate_number, vehicle_type) VALUES (?, ?)"
            " ON CONFLICT (plate_number) DO UPDATE SET vehicle_type = excluded.vehicle_type",
            (plate, vehicle_type),
        )
        vehicle_id = db.execute(
            "SELECT vehicle_id FROM vehicles WHERE plate_number = ?", (plate,)
        ).fetchone()[0]
        db.execute(
            "INSERT INTO tickets (ticket_id, vehicle_id, slot_id, entry_time)"
            " VALUES (?, ?, ?, ?)",
            (ticket_id, vehicle_id, slot_id, clock.to_text(entered)),
        )
        db.execute("UPDATE slots SET status = 'OCCUPIED' WHERE slot_id = ?", (slot_id,))
        db.commit()
    except sqlite3.IntegrityError:
        db.rollback()
        raise ParkingError(409, "SLOT_CONFLICT",
                           "That slot was just taken. Please try again.")
    except Exception:
        db.rollback()
        raise

    ticket = get_ticket(db, ticket_id)
    ticket["path"] = [list(cell) for cell in path]
    ticket["start_from"] = start_from
    ticket["reassigned_from"] = target_slot if target_slot not in (None, slot_id) else None
    return ticket


def get_ticket(db, ticket_id):
    ticket_id = str(ticket_id).strip().upper()
    if not TICKET_PATTERN.match(ticket_id):
        raise ParkingError(404, "TICKET_NOT_FOUND", "No ticket found with that ID.")
    row = db.execute(
        "SELECT t.ticket_id, v.plate_number, v.vehicle_type, t.slot_id, s.category,"
        " t.entry_time, t.exit_time, t.status"
        " FROM tickets t"
        " JOIN vehicles v ON v.vehicle_id = t.vehicle_id"
        " JOIN slots s ON s.slot_id = t.slot_id"
        " WHERE t.ticket_id = ?", (ticket_id,)
    ).fetchone()
    if row is None:
        raise ParkingError(404, "TICKET_NOT_FOUND", "No ticket found with that ID.")
    return dict(row)


def quote_exit(db, ticket_id):
    """Work out the parking duration and fee for an active ticket.

    The ticket stays open: it is closed only after the mock payment succeeds
    (Design Spec 4.3, PAYMENT_FAILED rule), using close_ticket().
    """
    if not str(ticket_id).strip():
        raise ParkingError(400, "MISSING_TICKET_ID", "Enter the ticket ID.")
    ticket = get_ticket(db, ticket_id)
    if ticket["status"] != "ACTIVE":
        raise ParkingError(409, "TICKET_CLOSED",
                           f"Ticket {ticket['ticket_id']} has already exited.")
    exit_time = clock.now(db)
    seconds = max(0, (exit_time - clock.from_text(ticket["entry_time"])).total_seconds())
    rate, grace = fees.load_tariff(db, ticket["vehicle_type"])
    hours = fees.billable_hours(seconds, grace)
    ticket.update(
        exit_time=clock.to_text(exit_time),
        duration_seconds=int(seconds),
        duration=fees.format_duration(seconds),
        hourly_rate=rate,
        grace_minutes=grace,
        billable_hours=hours,
        fee=hours * rate,
    )
    return ticket


def close_ticket(db, ticket_id, exit_time):
    """Close a paid ticket, free its slot and keep the stay for wait-time prediction."""
    ticket = get_ticket(db, ticket_id)
    if ticket["status"] != "ACTIVE":
        raise ParkingError(409, "TICKET_CLOSED",
                           f"Ticket {ticket['ticket_id']} has already exited.")
    entered = clock.from_text(ticket["entry_time"])
    left = clock.from_text(exit_time)
    with db:
        db.execute("UPDATE tickets SET status = 'CLOSED', exit_time = ? WHERE ticket_id = ?",
                   (exit_time, ticket["ticket_id"]))
        db.execute("UPDATE slots SET status = 'VACANT' WHERE slot_id = ?", (ticket["slot_id"],))
        db.execute(
            "INSERT INTO dwell_history (vehicle_type, entry_time, exit_time, duration_min)"
            " VALUES (?, ?, ?, ?)",
            (ticket["vehicle_type"], ticket["entry_time"], exit_time,
             int((left - entered).total_seconds() // 60)),
        )
    return get_ticket(db, ticket_id)


def qr_svg(text):
    image = qrcode.make(text, image_factory=qrcode.image.svg.SvgPathImage, box_size=10)
    return image.to_string(encoding="unicode")


def error_response(err):
    return jsonify(error=err.code, message=err.message), err.status


# ---------- JSON API (Design Spec section 4.2) ----------

@bp.post("/api/parking/entry")
@login_required
def api_entry():
    data = request.get_json(silent=True) or request.form
    try:
        ticket = register_entry(get_db(), data.get("plate"), data.get("vehicle_type"),
                                is_checked(data.get("accessible", False)),
                                data.get("start_from", "ENTRANCE"), data.get("target_slot"))
    except ParkingError as err:
        return error_response(err)
    return jsonify(ticket), 201


@bp.post("/api/parking/preview")
@login_required
def api_preview():
    """Return the slot and route an entry would get, without creating a ticket."""
    data = request.get_json(silent=True) or request.form
    try:
        return jsonify(preview_route(get_db(), data.get("plate"), data.get("vehicle_type"),
                                     is_checked(data.get("accessible", False)),
                                     data.get("start_from", "ENTRANCE")))
    except ParkingError as err:
        return error_response(err)


@bp.post("/api/parking/exit")
@login_required
def api_exit():
    data = request.get_json(silent=True) or request.form
    try:
        return jsonify(quote_exit(get_db(), data.get("ticket_id") or ""))
    except ParkingError as err:
        return error_response(err)


@bp.get("/api/parking/<ticket_id>")
@login_required
def api_ticket(ticket_id):
    try:
        return jsonify(get_ticket(get_db(), ticket_id))
    except ParkingError as err:
        return error_response(err)


@bp.get("/tickets/<ticket_id>/qr.svg")
@login_required
def ticket_qr(ticket_id):
    try:
        ticket = get_ticket(get_db(), ticket_id)
    except ParkingError:
        abort(404)
    return Response(qr_svg(ticket["ticket_id"]), mimetype="image/svg+xml")


# ---------- Attendant screens ----------

@bp.route("/entry", methods=["GET", "POST"])
@login_required
def entry_page():
    ticket = preview = error = None
    status = 200
    form = request.form
    if request.method == "POST":
        fields = (form.get("plate"), form.get("vehicle_type"),
                  is_checked(form.get("accessible")), form.get("start_from", "ENTRANCE"))
        try:
            if form.get("action") == "preview":
                preview = preview_route(get_db(), *fields)
            else:
                ticket = register_entry(get_db(), *fields, form.get("target_slot") or None)
                status = 201
                form = {}  # clear the form so the same vehicle is not submitted twice
        except ParkingError as err:
            error, status = err.message, err.status
    return render_template("entry.html", ticket=ticket, preview=preview, error=error, form=form,
                           vehicle_types=VEHICLE_TYPES, start_points=START_POINTS), status


@bp.route("/exit", methods=["GET", "POST"])
@login_required
def exit_page():
    quote = error = None
    status = 200
    form = request.form
    if request.method == "POST":
        try:
            quote = quote_exit(get_db(), form.get("ticket_id") or "")
        except ParkingError as err:
            error, status = err.message, err.status
    return render_template("exit.html", quote=quote, error=error, form=form,
                           vehicle_types=VEHICLE_TYPES), status
