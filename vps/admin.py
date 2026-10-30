"""Admin settings, layout editor and read-only audit log (REQ-USR-02, REQ-NAV-01, SEC-08)."""
import re

from flask import Blueprint, redirect, render_template, request, url_for

from .audit import record_action
from .auth import role_required
from .db import get_db
from .grid import MAX_SIZE, bfs, find_cell
from .slots import CATEGORY_LABELS, STATUSES, set_reserved

bp = Blueprint("admin", __name__, url_prefix="/admin")

# key: (label, smallest value, largest value)
NUMBER_SETTINGS = {
    "rate_two_wheeler": ("Two-Wheeler rate (Rs. per hour)", 1, 10000),
    "rate_car": ("Car rate (Rs. per hour)", 1, 10000),
    "rate_ev": ("EV rate (Rs. per hour)", 1, 10000),
    "grace_minutes": ("Grace period (minutes)", 0, 30),
}
CELL_TOKENS = {"#": "WALL", ".": "ROAD", "N": "ENTRANCE", "X": "EXIT"}
TOKEN_FOR = {kind: token for token, kind in CELL_TOKENS.items()}
SLOT_TOKEN = re.compile(r"^(S\d{2,3})(?::([A-Z_]+))?$")


class AdminError(Exception):
    """A settings or layout change that cannot be accepted."""


def save_settings(db, form):
    """Validate every number first, then store and audit only the changed values."""
    changes = []
    for key, (label, low, high) in NUMBER_SETTINGS.items():
        text = (form.get(key) or "").strip()
        if not re.fullmatch(r"\d{1,5}", text) or not low <= int(text) <= high:
            raise AdminError(f"{label} must be a whole number from {low} to {high}.")
        old = db.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()["value"]
        if old != str(int(text)):
            changes.append((key, old, str(int(text))))
    for key, old, new in changes:
        db.execute("UPDATE settings SET value = ? WHERE key = ?", (new, key))
        record_action(db, f"UPDATE_SETTING {key}", old, new)
    db.commit()
    return len(changes)


def layout_text(db):
    """Write the current grid in the editor's text format."""
    rows = {}
    for row in db.execute("SELECT row_no, col_no, cell_type, slot_id FROM grid_cells"
                          " ORDER BY row_no, col_no"):
        token = row["slot_id"] or TOKEN_FOR[row["cell_type"]]
        rows.setdefault(row["row_no"], []).append(token)
    return "\n".join(" ".join(tokens) for tokens in rows.values())


def parse_layout(text):
    """Turn editor text into rows of tokens, checking the size and required cells."""
    rows = [line.split() for line in text.splitlines() if line.strip()]
    if not rows or len(rows) > MAX_SIZE or any(len(r) > MAX_SIZE for r in rows):
        raise AdminError(f"The grid must be between 1 x 1 and {MAX_SIZE} x {MAX_SIZE}.")
    if len({len(r) for r in rows}) != 1:
        raise AdminError("Every row must have the same number of cells.")
    tokens = [token.upper() for row in rows for token in row]
    for token in tokens:
        if token not in CELL_TOKENS and not SLOT_TOKEN.match(token):
            raise AdminError(f"Unknown cell '{token}'. Use # . N X, S01 or S21:CAR.")
    if tokens.count("N") != 1 or tokens.count("X") != 1:
        raise AdminError("The grid must have exactly one entrance (N) and one exit (X).")
    return [[token.upper() for token in row] for row in rows]


def apply_layout(db, text):
    """Replace the grid. Slots in use or with parking history cannot be removed."""
    rows = parse_layout(text)
    existing = {r["slot_id"]: r["status"] for r in db.execute(
        "SELECT slot_id, status FROM slots")}
    wanted = {}
    for row in rows:
        for token in row:
            match = SLOT_TOKEN.match(token)
            if match:
                slot_id, category = match.groups()
                if slot_id in wanted:
                    raise AdminError(f"{slot_id} appears more than once.")
                if category and category not in CATEGORY_LABELS:
                    raise AdminError(f"Unknown category {category}.")
                if not category and slot_id not in existing:
                    raise AdminError(f"New slot {slot_id} needs a category, e.g. {slot_id}:CAR.")
                wanted[slot_id] = category

    for slot_id in set(existing) - set(wanted):
        used = db.execute("SELECT 1 FROM tickets WHERE slot_id = ? LIMIT 1", (slot_id,)).fetchone()
        if used:
            raise AdminError(f"{slot_id} has parking history and cannot be removed.")

    old_text = layout_text(db)
    db.execute("DELETE FROM grid_cells")
    for slot_id in set(existing) - set(wanted):
        db.execute("DELETE FROM slots WHERE slot_id = ?", (slot_id,))
    for slot_id, category in wanted.items():
        if slot_id not in existing:
            db.execute("INSERT INTO slots (slot_id, category) VALUES (?, ?)", (slot_id, category))
        elif category:
            if existing[slot_id] == "OCCUPIED":
                db.rollback()
                raise AdminError(f"{slot_id} is occupied, so its category cannot change.")
            db.execute("UPDATE slots SET category = ? WHERE slot_id = ?", (category, slot_id))
    grid = []
    for row_no, row in enumerate(rows):
        cells = []
        for col_no, token in enumerate(row):
            match = SLOT_TOKEN.match(token)
            kind, slot_id = ("SLOT", match.group(1)) if match else (CELL_TOKENS[token], None)
            db.execute("INSERT INTO grid_cells (row_no, col_no, cell_type, slot_id)"
                       " VALUES (?, ?, ?, ?)", (row_no, col_no, kind, slot_id))
            cells.append((kind, slot_id))
        grid.append(cells)
    record_action(db, "UPDATE_LAYOUT", old_text, layout_text(db))
    db.commit()

    reached, _ = bfs(grid, find_cell(grid, "ENTRANCE"))
    return sorted(cell[1] for r, row in enumerate(grid) for c, cell in enumerate(row)
                  if cell[0] == "SLOT" and (r, c) not in reached)


def _render_settings(error=None, message=None, status=200, layout=None):
    """Render the settings page with the current values."""
    db = get_db()
    values = dict(db.execute("SELECT key, value FROM settings").fetchall())
    fields = [{"key": k, "label": v[0], "low": v[1], "high": v[2], "value": values[k]}
              for k, v in NUMBER_SETTINGS.items()]
    slots = db.execute("SELECT slot_id, status FROM slots ORDER BY slot_id").fetchall()
    return render_template("settings.html", fields=fields, layout=layout or layout_text(db),
                           slots=slots, statuses=STATUSES, error=error, message=message), status


@bp.get("/settings")
@role_required("ADMIN")
def settings_page():
    """Show rates, grace period, layout editor and slot reservation."""
    return _render_settings()


@bp.post("/settings")
@role_required("ADMIN")
def update_settings():
    """Save rates and the grace period."""
    db = get_db()
    try:
        changed = save_settings(db, request.form)
    except AdminError as err:
        db.rollback()
        return _render_settings(error=str(err), status=400)
    return _render_settings(message=f"Saved. {changed} value(s) changed.")


@bp.post("/layout")
@role_required("ADMIN")
def update_layout():
    """Save the facility grid."""
    db = get_db()
    text = request.form.get("layout") or ""
    try:
        unreachable = apply_layout(db, text)
    except AdminError as err:
        db.rollback()
        return _render_settings(error=str(err), status=400, layout=text)
    message = "Layout saved."
    if unreachable:
        message += " Warning: no route reaches " + ", ".join(unreachable) + "."
    return _render_settings(message=message)


@bp.post("/reserve")
@role_required("ADMIN")
def reserve_slot():
    """Reserve a vacant slot or release a reserved one."""
    body, status = set_reserved(get_db(), (request.form.get("slot_id") or "").upper(),
                                request.form.get("reserved") == "1")
    if status != 200:
        return _render_settings(error=body["message"], status=status)
    return redirect(url_for("admin.settings_page"))


@bp.get("/audit")
@role_required("ADMIN")
def audit_page():
    """Show the audit log. There is deliberately no route that edits or deletes it."""
    rows = get_db().execute(
        "SELECT a.logged_at, u.username, a.action, a.old_value, a.new_value FROM audit_log a"
        " LEFT JOIN users u ON u.user_id = a.user_id ORDER BY a.log_id DESC"
    ).fetchall()
    return render_template("audit.html", rows=rows)
