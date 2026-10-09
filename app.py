import os
import sqlite3
from pathlib import Path

from flask import Flask, current_app, g


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('Administrator', 'Attendant'))
);

CREATE TABLE IF NOT EXISTS parking_slots (
    id INTEGER PRIMARY KEY,
    slot_number TEXT NOT NULL UNIQUE,
    category TEXT NOT NULL CHECK (category IN ('Two-Wheeler', 'Car', 'Accessible', 'EV')),
    status TEXT NOT NULL DEFAULT 'Vacant' CHECK (status IN ('Vacant', 'Occupied', 'Reserved'))
);

CREATE TABLE IF NOT EXISTS tickets (
    id INTEGER PRIMARY KEY,
    ticket_id TEXT NOT NULL UNIQUE,
    plate TEXT NOT NULL,
    vehicle_type TEXT NOT NULL,
    slot_id INTEGER NOT NULL REFERENCES parking_slots(id),
    entered_at TEXT NOT NULL,
    exited_at TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS one_active_ticket_per_plate
    ON tickets(plate) WHERE exited_at IS NULL;

CREATE TABLE IF NOT EXISTS payments (
    id INTEGER PRIMARY KEY,
    ticket_id TEXT NOT NULL REFERENCES tickets(ticket_id),
    amount REAL NOT NULL CHECK (amount >= 0),
    status TEXT NOT NULL CHECK (status IN ('Success', 'Failure')),
    reference TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY,
    user_id INTEGER REFERENCES users(id),
    action TEXT NOT NULL,
    old_values TEXT,
    new_values TEXT,
    created_at TEXT NOT NULL
);
"""


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(current_app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def close_db(_error=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = get_db()
    db.executescript(SCHEMA)
    db.commit()


def create_app(test_config=None):
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_mapping(
        SECRET_KEY=os.environ.get("SECRET_KEY", "development-only-change-me"),
        DATABASE=os.path.join(app.instance_path, "parking.sqlite"),
    )
    if test_config:
        app.config.update(test_config)

    Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    app.teardown_appcontext(close_db)

    with app.app_context():
        init_db()

    @app.get("/")
    def index():
        return {"name": "Vehicle Parking System", "status": "ready"}

    return app


app = create_app()

if __name__ == "__main__":
    app.run(debug=os.environ.get("FLASK_DEBUG") == "1")
