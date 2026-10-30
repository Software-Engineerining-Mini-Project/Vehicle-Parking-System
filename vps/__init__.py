"""Vehicle Parking System - Flask application factory."""
import os
import secrets
from datetime import timedelta

from flask import Flask, jsonify, render_template, request
from flask_wtf.csrf import CSRFError, CSRFProtect

from . import admin, auth, db, demo, parking, payment, prediction, reports, slots


def load_secret_key(instance_path):
    """Use VPS_SECRET_KEY, or a random key created once and kept in the instance folder."""
    key = os.environ.get("VPS_SECRET_KEY")
    if key:
        return key
    path = os.path.join(instance_path, "secret_key")
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(secrets.token_hex(32))
    with open(path, encoding="utf-8") as handle:
        return handle.read().strip()


def create_app(test_config=None):
    """Create and configure the Flask application."""
    app = Flask(__name__, instance_relative_config=True)
    os.makedirs(app.instance_path, exist_ok=True)
    test_config = test_config or {}
    app.config.from_mapping(
        SECRET_KEY=load_secret_key(app.instance_path),
        DATABASE=os.path.join(app.instance_path, "vps.db"),
        # SEC-06: cookie flags and idle limit
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        PERMANENT_SESSION_LIFETIME=timedelta(minutes=auth.IDLE_MINUTES),
        # SEC-07: on everywhere; the unit tests of other modules switch it off
        WTF_CSRF_ENABLED=not test_config.get("TESTING", False),
        WTF_CSRF_TIME_LIMIT=None,
    )
    app.config.update(test_config)

    CSRFProtect(app)

    @app.errorhandler(CSRFError)
    def csrf_failed(error):
        """Answer a missing or invalid CSRF token with HTTP 400."""
        message = "Your session form has expired or is not valid. Please try again."
        if request.path.startswith("/api/"):
            return jsonify(error="CSRF_FAILED", message=message), 400
        return render_template("error.html", message=message), 400

    db.init_app(app)
    app.register_blueprint(auth.bp)
    app.register_blueprint(parking.bp)
    app.register_blueprint(slots.bp)
    app.register_blueprint(payment.bp)
    app.register_blueprint(demo.bp)
    app.register_blueprint(reports.bp)
    app.register_blueprint(prediction.bp)
    app.register_blueprint(admin.bp)

    @app.route("/")
    @auth.login_required
    def index():
        """Show the dashboard."""
        return render_template("index.html")

    return app
