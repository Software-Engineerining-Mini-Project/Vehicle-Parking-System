"""Vehicle Parking System - Flask application factory."""
import os

from flask import Flask, render_template

from . import admin, auth, db, demo, parking, payment, prediction, reports, slots


def create_app(test_config=None):
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_mapping(
        SECRET_KEY=os.environ.get("VPS_SECRET_KEY", "dev-only-change-me"),
        DATABASE=os.path.join(app.instance_path, "vps.db"),
    )
    if test_config:
        app.config.update(test_config)

    os.makedirs(app.instance_path, exist_ok=True)
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
        return render_template("index.html")

    return app
