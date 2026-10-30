"""Login, logout, role checks, lockout and sessions (REQ-USR-01, SEC-01 to 03, SEC-06)."""
import functools
import re
import secrets
import time
from datetime import timedelta

from flask import (Blueprint, current_app, g, jsonify, redirect, render_template, request,
                   session, url_for)
from werkzeug.security import check_password_hash

from . import clock
from .db import get_db

bp = Blueprint("auth", __name__)

ROLE_LABELS = {"ADMIN": "Administrator", "ATTENDANT": "Attendant"}
USERNAME_PATTERN = re.compile(r"^[a-z0-9_]{1,30}$")
MAX_FAILED_LOGINS = 5
LOCK_MINUTES = 5
IDLE_MINUTES = 15
BAD_LOGIN = "Invalid username or password."
# The live grid polls every 500 ms; that must not count as the user being active
BACKGROUND_ENDPOINTS = {"slots.api_slots", "static"}


@bp.before_app_request
def load_logged_in_user():
    """Load the user unless the session was logged out or has been idle too long."""
    g.user = None
    user_id = session.get("user_id")
    if user_id is None:
        return
    user = get_db().execute(
        "SELECT user_id, username, role, session_token FROM users WHERE user_id = ?", (user_id,)
    ).fetchone()
    idle = time.time() - session.get("last_seen", 0)
    # The token is cleared on logout, so a copied cookie stops working (TC-17)
    if user is None or user["session_token"] != session.get("token") \
            or idle > IDLE_MINUTES * 60:
        session.clear()
        return
    g.user = user
    if request.endpoint not in BACKGROUND_ENDPOINTS:
        session["last_seen"] = time.time()


@bp.app_context_processor
def inject_user():
    return {"current_user": g.get("user"), "role_labels": ROLE_LABELS}


def _checks_disabled():
    # Lets the tests of other modules call routes without logging in first
    return current_app.config.get("LOGIN_DISABLED", False)


def login_required(view):
    """Send anonymous users to the login page (or HTTP 401 for API calls)."""
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        if g.user is None and not _checks_disabled():
            if request.path.startswith("/api/"):
                return jsonify(error="LOGIN_REQUIRED", message="Please log in first."), 401
            return redirect(url_for("auth.login", next=request.full_path.rstrip("?")))
        return view(*args, **kwargs)
    return wrapped


def role_required(role):
    """Allow only the given role; anyone else gets HTTP 403 and the attempt is audited."""
    def decorator(view):
        @functools.wraps(view)
        @login_required
        def wrapped(*args, **kwargs):
            if not _checks_disabled() and g.user["role"] != role:
                db = get_db()
                db.execute(
                    "INSERT INTO audit_log (user_id, action, new_value, logged_at)"
                    " VALUES (?, 'ACCESS_DENIED', ?, ?)",
                    (g.user["user_id"], f"{request.method} {request.path}",
                     clock.to_text(clock.now(db))),
                )
                db.commit()
                message = "This action needs an administrator."
                if request.path.startswith("/api/"):
                    return jsonify(error="FORBIDDEN", message=message), 403
                return render_template("error.html", message=message), 403
            return view(*args, **kwargs)
        return wrapped
    return decorator


def safe_next(target):
    """Only follow local redirects, never to another site."""
    if target and target.startswith("/") and not target.startswith("//"):
        return target
    return url_for("index")


def attempt_login(db, username, password):
    """Check the credentials and lockout. Returns (user_id, None) or (None, error message)."""
    if not USERNAME_PATTERN.match(username):
        return None, BAD_LOGIN
    user = db.execute(
        "SELECT user_id, password_hash, failed_attempts, locked_until FROM users"
        " WHERE username = ?", (username,)
    ).fetchone()
    if user is None:
        return None, BAD_LOGIN

    now = clock.now(db)
    if user["locked_until"] and clock.from_text(user["locked_until"]) > now:
        return None, f"This account is locked. Try again in up to {LOCK_MINUTES} minutes."

    if check_password_hash(user["password_hash"], password):
        # Sessions of one user share a token, so a second device does not end the first
        db.execute("UPDATE users SET failed_attempts = 0, locked_until = NULL,"
                   " session_token = COALESCE(session_token, ?) WHERE user_id = ?",
                   (secrets.token_hex(16), user["user_id"]))
        db.commit()
        token = db.execute("SELECT session_token FROM users WHERE user_id = ?",
                           (user["user_id"],)).fetchone()["session_token"]
        session.clear()
        session.permanent = True
        session.update(user_id=user["user_id"], token=token, last_seen=time.time())
        return user["user_id"], None

    failures = user["failed_attempts"] + 1
    if failures >= MAX_FAILED_LOGINS:
        db.execute("UPDATE users SET failed_attempts = 0, locked_until = ? WHERE user_id = ?",
                   (clock.to_text(now + timedelta(minutes=LOCK_MINUTES)), user["user_id"]))
        db.execute("INSERT INTO audit_log (user_id, action, new_value, logged_at)"
                   " VALUES (?, 'ACCOUNT_LOCKED', ?, ?)",
                   (user["user_id"], username, clock.to_text(now)))
        db.commit()
        return None, f"This account is locked. Try again in up to {LOCK_MINUTES} minutes."
    db.execute("UPDATE users SET failed_attempts = ? WHERE user_id = ?",
               (failures, user["user_id"]))
    db.commit()
    return None, BAD_LOGIN


@bp.route("/login", methods=["GET", "POST"])
def login():
    """Show the login form and handle a login attempt."""
    error = None
    if request.method == "POST":
        username = (request.form.get("username") or "").strip().lower()
        user_id, error = attempt_login(get_db(), username, request.form.get("password") or "")
        if user_id is not None:
            return redirect(safe_next(request.args.get("next")))
    return render_template("login.html", error=error), 401 if error else 200


@bp.post("/logout")
def logout():
    """End the session on the server as well as in the browser."""
    if g.user is not None:
        db = get_db()
        db.execute("UPDATE users SET session_token = NULL WHERE user_id = ?",
                   (g.user["user_id"],))
        db.commit()
    session.clear()
    return redirect(url_for("auth.login"))
