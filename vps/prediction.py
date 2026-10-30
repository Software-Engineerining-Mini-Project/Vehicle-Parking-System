"""Predicted wait for the next free slot from average dwell time (REQ-PRED-01 to 03).

A simple heuristic, not a machine-learning model.
"""
import math

from flask import Blueprint, jsonify, request

from . import clock
from .auth import login_required
from .db import get_db
from .slots import CATEGORY_LABELS

bp = Blueprint("prediction", __name__)

MIN_RECORDS = 5
UNAVAILABLE = "Estimate unavailable"


def dwell_averages(db):
    """Return {vehicle_type: (average minutes, number of records)}."""
    return {row["vehicle_type"]: (row["average"], row["records"]) for row in db.execute(
        "SELECT vehicle_type, AVG(duration_min) AS average, COUNT(*) AS records"
        " FROM dwell_history GROUP BY vehicle_type")}


def estimate_minutes(db, category):
    """Return min over occupied slots of max(0, average dwell - time parked), rounded up.

    Returns None when there are too few records or nothing is parked in the category.
    """
    averages = dwell_averages(db)
    now = clock.now(db)
    estimates = []
    for row in db.execute(
        "SELECT v.vehicle_type, t.entry_time FROM tickets t"
        " JOIN vehicles v ON v.vehicle_id = t.vehicle_id"
        " JOIN slots s ON s.slot_id = t.slot_id"
        " WHERE t.status = 'ACTIVE' AND s.category = ?", (category,)
    ):
        average, records = averages.get(row["vehicle_type"], (0, 0))
        if records >= MIN_RECORDS:
            parked = (now - clock.from_text(row["entry_time"])).total_seconds() / 60
            estimates.append(max(0, average - parked))
    return math.ceil(min(estimates)) if estimates else None


def next_vacancy_message(db, category):
    """Return the text the entry screen shows for one category (REQ-PRED-03)."""
    minutes = estimate_minutes(db, category)
    if minutes is None:
        return UNAVAILABLE
    return f"Next {CATEGORY_LABELS[category]} slot expected in about {minutes} min"


@bp.app_context_processor
def inject_predictions():
    """Give the entry screen the estimate for every category."""
    return {"predictions": lambda: [
        {"label": label, "message": next_vacancy_message(get_db(), category)}
        for category, label in CATEGORY_LABELS.items()]}


@bp.get("/api/prediction/next-vacancy")
@login_required
def api_next_vacancy():
    """Return the estimate for a category, or for every category (Design Spec 4.2)."""
    db = get_db()
    category = (request.args.get("category") or "").upper()
    if category and category not in CATEGORY_LABELS:
        return jsonify(error="INVALID_CATEGORY", message="Unknown slot category."), 400
    wanted = [category] if category else list(CATEGORY_LABELS)
    return jsonify(estimates=[{"category": c, "minutes": estimate_minutes(db, c),
                               "message": next_vacancy_message(db, c)} for c in wanted])
