"""Application time. The admin Demo Clock (OR-04) shifts it by a stored offset."""
from datetime import datetime, timedelta

TIME_FORMAT = "%Y-%m-%d %H:%M:%S"


def now(db):
    """Return the current application time, including the Demo Clock offset."""
    row = db.execute(
        "SELECT value FROM settings WHERE key = 'demo_clock_offset_min'"
    ).fetchone()
    offset = int(row["value"]) if row else 0
    return datetime.now().replace(microsecond=0) + timedelta(minutes=offset)


def to_text(moment):
    """Format a time the way it is stored in the database."""
    return moment.strftime(TIME_FORMAT)


def from_text(text):
    """Read a time stored in the database."""
    return datetime.strptime(text, TIME_FORMAT)
