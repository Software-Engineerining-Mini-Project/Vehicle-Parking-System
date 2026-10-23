"""Vehicle Parking System - Flask application factory."""
import os

from flask import Flask, render_template

from . import db, parking


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
    app.register_blueprint(parking.bp)

    @app.route("/")
    def index():
        rows = db.get_db().execute(
            "SELECT category, COUNT(*) AS total,"
            " SUM(status = 'VACANT') AS vacant"
            " FROM slots GROUP BY category ORDER BY category"
        ).fetchall()
        return render_template("index.html", rows=rows)

    return app
