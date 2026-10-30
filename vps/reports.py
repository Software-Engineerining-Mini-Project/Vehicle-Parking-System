"""Occupancy and revenue reports with CSV and PDF export (REQ-REP-01 to 03, NFR-PERF-05)."""
import csv
import io
import re
from datetime import datetime, timedelta

from flask import Blueprint, Response, jsonify, render_template, request
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from . import clock
from .auth import role_required
from .db import get_db
from .slots import CATEGORY_LABELS

bp = Blueprint("reports", __name__)

DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
PERIODS = {"daily": "Daily", "weekly": "Weekly", "monthly": "Monthly"}
MAX_RANGE_DAYS = 366
DEFAULT_RANGE_DAYS = 30


class ReportError(Exception):
    """The requested report parameters are not valid."""


def parse_range(args, today):
    """Read and validate the start date, end date and period from the request."""
    start_text = args.get("start") or (today - timedelta(days=DEFAULT_RANGE_DAYS - 1)).isoformat()
    end_text = args.get("end") or today.isoformat()
    period = args.get("period") or "daily"
    if period not in PERIODS:
        raise ReportError("Period must be daily, weekly or monthly.")
    try:
        if not (DATE_PATTERN.match(start_text) and DATE_PATTERN.match(end_text)):
            raise ValueError
        start = datetime.strptime(start_text, "%Y-%m-%d")
        end = datetime.strptime(end_text, "%Y-%m-%d")
    except ValueError:
        raise ReportError("Dates must be valid and written as YYYY-MM-DD.") from None
    if end < start:
        raise ReportError("The end date cannot be before the start date.")
    if (end - start).days >= MAX_RANGE_DAYS:
        raise ReportError(f"The date range cannot be longer than {MAX_RANGE_DAYS} days.")
    return start, end + timedelta(days=1), period


def period_buckets(start, end, period):
    """Split [start, end) into (label, from, to) buckets."""
    buckets = []
    current = start
    while current < end:
        if period == "daily":
            following = current + timedelta(days=1)
            label = current.strftime("%Y-%m-%d")
        elif period == "weekly":
            following = min(current + timedelta(days=7), end)
            label = f"{current:%Y-%m-%d} to {following - timedelta(days=1):%Y-%m-%d}"
        else:
            following = min((current.replace(day=1) + timedelta(days=32)).replace(day=1), end)
            label = current.strftime("%Y-%m")
        buckets.append((label, current, following))
        current = following
    return buckets


def overlap_seconds(first_start, first_end, second_start, second_end):
    """Return how many seconds two time ranges have in common."""
    latest_start = max(first_start, second_start)
    earliest_end = min(first_end, second_end)
    return max(0.0, (earliest_end - latest_start).total_seconds())


def build_report(db, start, end, period):
    """Calculate the occupancy, revenue, peak hour and utilisation figures."""
    now = clock.now(db)
    slot_totals = {row["category"]: row["total"] for row in db.execute(
        "SELECT category, COUNT(*) AS total FROM slots GROUP BY category")}
    slot_count = sum(slot_totals.values())

    stays = []
    entries_per_hour = [0] * 24
    for row in db.execute(
        "SELECT t.entry_time, t.exit_time, s.category FROM tickets t"
        " JOIN slots s ON s.slot_id = t.slot_id"
        " WHERE t.entry_time < ? AND (t.exit_time IS NULL OR t.exit_time > ?)",
        (clock.to_text(end), clock.to_text(start)),
    ):
        entered = clock.from_text(row["entry_time"])
        left = clock.from_text(row["exit_time"]) if row["exit_time"] else now
        stays.append((entered, left, row["category"]))
        if start <= entered < end:
            entries_per_hour[entered.hour] += 1

    payments = [(clock.from_text(row["paid_at"]), row["amount"]) for row in db.execute(
        "SELECT paid_at, amount FROM payments WHERE status = 'SUCCESS'"
        " AND paid_at >= ? AND paid_at < ?", (clock.to_text(start), clock.to_text(end)))]

    rows = []
    for label, bucket_start, bucket_end in period_buckets(start, end, period):
        # Time that has not happened yet does not count as empty capacity
        elapsed = overlap_seconds(bucket_start, bucket_end, bucket_start, max(now, bucket_start))
        occupied = sum(overlap_seconds(a, b, bucket_start, bucket_end) for a, b, _ in stays)
        capacity = elapsed * slot_count
        rows.append({
            "period": label,
            "occupancy_percent": round(100 * occupied / capacity, 1) if capacity else 0.0,
            "revenue": sum(amount for paid, amount in payments
                           if bucket_start <= paid < bucket_end),
        })

    elapsed = overlap_seconds(start, end, start, max(now, start))
    utilisation = []
    for category, label in CATEGORY_LABELS.items():
        occupied = sum(overlap_seconds(a, b, start, end) for a, b, c in stays if c == category)
        capacity = elapsed * slot_totals.get(category, 0)
        utilisation.append({
            "category": label,
            "utilisation_percent": round(100 * occupied / capacity, 1) if capacity else 0.0,
        })

    busiest = max(range(24), key=lambda hour: entries_per_hour[hour])
    return {
        "start": start.strftime("%Y-%m-%d"),
        "end": (end - timedelta(days=1)).strftime("%Y-%m-%d"),
        "period": period,
        "rows": rows,
        "total_revenue": sum(amount for _, amount in payments),
        "peak_hour": f"{busiest:02d}:00" if entries_per_hour[busiest] else "No entries",
        "utilisation": utilisation,
    }


def report_to_csv(report):
    """Write the report as CSV text with the same figures as the screen."""
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["Vehicle Parking System report", report["start"], report["end"],
                     PERIODS[report["period"]]])
    writer.writerow(["Period", "Occupancy (%)", "Revenue (Rs.)"])
    for row in report["rows"]:
        writer.writerow([row["period"], row["occupancy_percent"], row["revenue"]])
    writer.writerow(["Total revenue (Rs.)", "", report["total_revenue"]])
    writer.writerow(["Peak hour", report["peak_hour"]])
    writer.writerow(["Category", "Average utilisation (%)"])
    for row in report["utilisation"]:
        writer.writerow([row["category"], row["utilisation_percent"]])
    return out.getvalue()


def report_to_pdf(report):
    """Render the report as a PDF with the same figures as the screen."""
    styles = getSampleStyleSheet()
    grid = TableStyle([("GRID", (0, 0), (-1, -1), 0.5, colors.black),
                       ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold")])
    period_rows = [["Period", "Occupancy (%)", "Revenue (Rs.)"]] + [
        [r["period"], r["occupancy_percent"], r["revenue"]] for r in report["rows"]]
    category_rows = [["Category", "Average utilisation (%)"]] + [
        [r["category"], r["utilisation_percent"]] for r in report["utilisation"]]
    story = [
        Paragraph("Vehicle Parking System report", styles["Title"]),
        Paragraph(f"{report['start']} to {report['end']} ({PERIODS[report['period']]})",
                  styles["Normal"]),
        Spacer(1, 12),
        Table(period_rows, style=grid, repeatRows=1),
        Spacer(1, 12),
        Paragraph(f"Total revenue: Rs. {report['total_revenue']}", styles["Normal"]),
        Paragraph(f"Peak hour: {report['peak_hour']}", styles["Normal"]),
        Spacer(1, 12),
        Table(category_rows, style=grid),
    ]
    buffer = io.BytesIO()
    SimpleDocTemplate(buffer, pagesize=A4, title="Vehicle Parking System report").build(story)
    return buffer.getvalue()


def _load_report():
    """Build the report for the current request's parameters."""
    db = get_db()
    return build_report(db, *parse_range(request.args, clock.now(db).date()))


@bp.get("/reports")
@role_required("ADMIN")
def reports_page():
    """Show the report form and results."""
    report = error = None
    status = 200
    try:
        report = _load_report()
    except ReportError as err:
        error, status = str(err), 400
    return render_template("reports.html", report=report, error=error, periods=PERIODS,
                           args=request.args), status


@bp.get("/reports/export.csv")
@role_required("ADMIN")
def export_csv():
    """Download the report as CSV."""
    try:
        body = report_to_csv(_load_report())
    except ReportError as err:
        return jsonify(error="INVALID_REPORT", message=str(err)), 400
    return Response(body, mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=vps_report.csv"})


@bp.get("/reports/export.pdf")
@role_required("ADMIN")
def export_pdf():
    """Download the report as PDF."""
    try:
        body = report_to_pdf(_load_report())
    except ReportError as err:
        return jsonify(error="INVALID_REPORT", message=str(err)), 400
    return Response(body, mimetype="application/pdf",
                    headers={"Content-Disposition": "attachment; filename=vps_report.pdf"})


@bp.get("/api/reports/occupancy")
@role_required("ADMIN")
def api_occupancy():
    """Return occupancy per period as JSON (Design Spec 4.2)."""
    try:
        report = _load_report()
    except ReportError as err:
        return jsonify(error="INVALID_REPORT", message=str(err)), 400
    return jsonify(rows=[{"period": r["period"], "occupancy_percent": r["occupancy_percent"]}
                         for r in report["rows"]],
                   peak_hour=report["peak_hour"], utilisation=report["utilisation"])


@bp.get("/api/reports/revenue")
@role_required("ADMIN")
def api_revenue():
    """Return revenue per period as JSON (Design Spec 4.2)."""
    try:
        report = _load_report()
    except ReportError as err:
        return jsonify(error="INVALID_REPORT", message=str(err)), 400
    return jsonify(rows=[{"period": r["period"], "revenue": r["revenue"]}
                         for r in report["rows"]],
                   total_revenue=report["total_revenue"])
