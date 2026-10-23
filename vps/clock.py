"""Application time. The admin Demo Clock (OR-04) shifts it by a stored offset."""
from datetime import datetime, timedelta

TIME_FORMAT = "%Y-%m-%d %H:%M:%S"


def now(db):
    row = db.execute(
        "SELECT value FROM settings WHERE key = 'demo_clock_offset_min'"
    ).fetchone()
    offset = int(row["value"]) if row else 0
    return datetime.now().replace(microsecond=0) + timedelta(minutes=offset)


def to_text(moment):
    return moment.strftime(TIME_FORMAT)


def from_text(text):
    return datetime.strptime(text, TIME_FORMAT)
