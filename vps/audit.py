"""Append-only audit log of administrative actions (REQ-USR-02, SEC-08)."""
from flask import g

from . import clock


def record_action(db, action, old_value=None, new_value=None):
    """Add one audit entry for the logged-in user. The caller commits."""
    user = g.get("user")
    db.execute(
        "INSERT INTO audit_log (user_id, action, old_value, new_value, logged_at)"
        " VALUES (?, ?, ?, ?, ?)",
        (user["user_id"] if user else None, action, old_value, new_value,
         clock.to_text(clock.now(db))),
    )
