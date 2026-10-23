"""Vehicle entry: validation, slot assignment and ticket creation (REQ-LOG-01 to 04)."""
import re
import sqlite3

import qrcode
import qrcode.image.svg
from flask import Blueprint, Response, abort, jsonify, render_template, request

from . import clock
from .db import get_db
from .grid import assign_slot

bp = Blueprint("parking", __name__)

PLATE_PATTERN = re.compile(r"^[A-Z0-9]{4,10}$")
VEHICLE_TYPES = {"TWO_WHEELER": "Two-Wheeler", "CAR": "Car", "EV": "EV"}


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


def register_entry(db, raw_plate, vehicle_type, accessible=False):
    """Validate the vehicle, assign the nearest suitable slot and open a ticket."""
    plate = normalise_plate(raw_plate)
    if vehicle_type not in VEHICLE_TYPES:
        raise ParkingError(400, "INVALID_VEHICLE_TYPE",
                           "Vehicle type must be Two-Wheeler, Car or EV.")

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

        assignment = assign_slot(db, vehicle_type, accessible)
        if assignment is None:
            wanted = "accessible" if accessible else VEHICLE_TYPES[vehicle_type]
            raise ParkingError(409, "NO_SLOT_AVAILABLE",
                               f"No {wanted} slot is free right now.")
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
    return ticket


def get_ticket(db, ticket_id):
    row = db.execute(
        "SELECT t.ticket_id, v.plate_number, v.vehicle_type, t.slot_id, s.category,"
        " t.entry_time, t.exit_time, t.status"
        " FROM tickets t"
        " JOIN vehicles v ON v.vehicle_id = t.vehicle_id"
        " JOIN slots s ON s.slot_id = t.slot_id"
        " WHERE t.ticket_id = ?", (ticket_id.strip().upper(),)
    ).fetchone()
    if row is None:
        raise ParkingError(404, "TICKET_NOT_FOUND", f"No ticket found with ID {ticket_id}.")
    return dict(row)


def qr_svg(text):
    image = qrcode.make(text, image_factory=qrcode.image.svg.SvgPathImage, box_size=10)
    return image.to_string(encoding="unicode")


def error_response(err):
    return jsonify(error=err.code, message=err.message), err.status


# ---------- JSON API (Design Spec section 4.2) ----------

@bp.post("/api/parking/entry")
def api_entry():
    data = request.get_json(silent=True) or request.form
    try:
        ticket = register_entry(get_db(), data.get("plate"), data.get("vehicle_type"),
                                is_checked(data.get("accessible", False)))
    except ParkingError as err:
        return error_response(err)
    return jsonify(ticket), 201


@bp.get("/api/parking/<ticket_id>")
def api_ticket(ticket_id):
    try:
        return jsonify(get_ticket(get_db(), ticket_id))
    except ParkingError as err:
        return error_response(err)


@bp.get("/tickets/<ticket_id>/qr.svg")
def ticket_qr(ticket_id):
    try:
        ticket = get_ticket(get_db(), ticket_id)
    except ParkingError:
        abort(404)
    return Response(qr_svg(ticket["ticket_id"]), mimetype="image/svg+xml")


# ---------- Attendant screens ----------

@bp.route("/entry", methods=["GET", "POST"])
def entry_page():
    ticket = error = None
    status = 200
    form = request.form
    if request.method == "POST":
        try:
            ticket = register_entry(get_db(), form.get("plate"), form.get("vehicle_type"),
                                    is_checked(form.get("accessible")))
            status = 201
            form = {}  # clear the form so the same vehicle is not submitted twice
        except ParkingError as err:
            error, status = err.message, err.status
    return render_template("entry.html", ticket=ticket, error=error, form=form,
                           vehicle_types=VEHICLE_TYPES), status
