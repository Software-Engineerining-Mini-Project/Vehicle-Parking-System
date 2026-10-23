"""Login, logout and role checks (REQ-USR-01, SEC-01, SEC-03)."""
import functools

from flask import (Blueprint, current_app, g, jsonify, redirect, render_template, request,
                   session, url_for)
from werkzeug.security import check_password_hash

from . import clock
from .db import get_db

bp = Blueprint("auth", __name__)

ROLE_LABELS = {"ADMIN": "Administrator", "ATTENDANT": "Attendant"}


@bp.before_app_request
def load_logged_in_user():
    g.user = None
    user_id = session.get("user_id")
    if user_id is not None:
        g.user = get_db().execute(
            "SELECT user_id, username, role FROM users WHERE user_id = ?", (user_id,)
        ).fetchone()


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


@bp.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        username = (request.form.get("username") or "").strip().lower()
        password = request.form.get("password") or ""
        user = get_db().execute(
            "SELECT user_id, password_hash FROM users WHERE username = ?", (username,)
        ).fetchone()
        if user and check_password_hash(user["password_hash"], password):
            session.clear()
            session["user_id"] = user["user_id"]
            return redirect(safe_next(request.args.get("next")))
        error = "Invalid username or password."
    return render_template("login.html", error=error), 401 if error else 200


@bp.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("auth.login"))
