"""SQLite connection handling and first-run setup."""
import sqlite3
from pathlib import Path

from flask import current_app, g

from .seed import seed_demo_data

SCHEMA_FILE = Path(__file__).with_name("schema.sql")


def get_db():
    """Return the connection for the current request, opening it if needed."""
    if "db" not in g:
        # Waits for a concurrent writer instead of failing (NFR-PERF-03)
        g.db = sqlite3.connect(current_app.config["DATABASE"], timeout=15)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def close_db(exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    """Create the tables and load the demo data if the database is empty."""
    db = get_db()
    db.execute("PRAGMA journal_mode = WAL")  # the live grid can read while an entry writes
    db.executescript(SCHEMA_FILE.read_text(encoding="utf-8"))
    if db.execute("SELECT COUNT(*) FROM slots").fetchone()[0] == 0:
        seed_demo_data(db)
    db.commit()


def init_app(app):
    app.teardown_appcontext(close_db)
    with app.app_context():
        init_db()
