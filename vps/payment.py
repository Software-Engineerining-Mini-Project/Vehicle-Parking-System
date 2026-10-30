"""Mock payment, admin force-failure toggle and receipt (REQ-PAY-02, REQ-PAY-03, NFR-REL-04).

No real payment details are ever asked for or stored (Design Spec: mock payment isolation).
"""
from flask import (Blueprint, g, jsonify, redirect, render_template, request, session,
                   url_for)

from . import clock
from .auth import login_required, role_required
from .db import get_db
from .parking import VEHICLE_TYPES, ParkingError, close_ticket, quote_exit

bp = Blueprint("payment", __name__)

FORCE_FAILURE_KEY = "mock_payment_force_failure"


def force_failure_on(db):
    """Return True if the admin has forced failures on."""
    row = db.execute("SELECT value FROM settings WHERE key = ?", (FORCE_FAILURE_KEY,)).fetchone()
    return bool(row and row["value"] == "1")


def set_force_failure(db, enabled, user_id):
    """Turn forced payment failure on or off and record the change in the audit log."""
    old = "1" if force_failure_on(db) else "0"
    new = "1" if enabled else "0"
    with db:
        db.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?)"
            " ON CONFLICT (key) DO UPDATE SET value = excluded.value",
            (FORCE_FAILURE_KEY, new),
        )
        db.execute(
            "INSERT INTO audit_log (user_id, action, old_value, new_value, logged_at)"
            " VALUES (?, 'SET_PAYMENT_FORCE_FAILURE', ?, ?, ?)",
            (user_id, old, new, clock.to_text(clock.now(db))),
        )


def process_payment(db, ticket_id):
    """Charge the exit fee through the mock gateway.

    On success the ticket is closed and the slot freed; on failure nothing changes
    except that the failed attempt is recorded.
    """
    db.execute("BEGIN IMMEDIATE")
    try:
        quote = quote_exit(db, ticket_id)
        failed = force_failure_on(db)
        cursor = db.execute(
            "INSERT INTO payments (ticket_id, amount, status, paid_at) VALUES (?, ?, ?, ?)",
            (quote["ticket_id"], quote["fee"], "FAILED" if failed else "SUCCESS",
             quote["exit_time"]),
        )
        if failed:
            db.commit()
            raise ParkingError(402, "PAYMENT_FAILED",
                               "Mock payment failed. The ticket is still open; please try again.")
        close_ticket(db, quote["ticket_id"], quote["exit_time"])  # commits with the payment
    except ParkingError as err:
        if err.code != "PAYMENT_FAILED":
            db.rollback()
        raise
    except Exception:
        db.rollback()
        raise

    receipt = dict(quote)
    receipt.update(reference=f"PAY-{cursor.lastrowid:06d}", amount=quote["fee"],
                   payment_status="SUCCESS", status="CLOSED", gate="OPEN")
    return receipt


@bp.app_context_processor
def inject_payment_mode():
    """Give the dashboard the current payment mode."""
    return {"payment_force_failure": lambda: force_failure_on(get_db())}


# ---------- JSON API ----------

@bp.post("/api/payment/mock")
@login_required
def api_pay():
    """Take a mock payment through the JSON API."""
    data = request.get_json(silent=True) or request.form
    try:
        return jsonify(process_payment(get_db(), data.get("ticket_id") or ""))
    except ParkingError as err:
        return jsonify(error=err.code, message=err.message), err.status


@bp.post("/api/admin/payment-mode")
@role_required("ADMIN")
def api_payment_mode():
    """Switch forced failure on or off through the API."""
    data = request.get_json(silent=True) or {}
    db = get_db()
    set_force_failure(db, bool(data.get("force_failure")), g.user["user_id"] if g.user else None)
    return jsonify(force_failure=force_failure_on(db))


# ---------- screens ----------

@bp.post("/pay")
@login_required
def pay_page():
    """Take a mock payment and show the receipt."""
    ticket_id = request.form.get("ticket_id") or ""
    try:
        receipt = process_payment(get_db(), ticket_id)
    except ParkingError as err:
        quote = None
        if err.code == "PAYMENT_FAILED":
            quote = quote_exit(get_db(), ticket_id)
        return render_template("exit.html", quote=quote, error=err.message,
                               form={"ticket_id": ticket_id},
                               vehicle_types=VEHICLE_TYPES), err.status
    return render_template("receipt.html", receipt=receipt, vehicle_types=VEHICLE_TYPES)


@bp.post("/admin/payment-mode")
@role_required("ADMIN")
def payment_mode_page():
    """Switch forced failure on or off from the dashboard."""
    set_force_failure(get_db(), request.form.get("force_failure") == "1", session.get("user_id"))
    return redirect(url_for("index"))
