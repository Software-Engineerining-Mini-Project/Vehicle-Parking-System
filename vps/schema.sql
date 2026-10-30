-- Vehicle Parking System database schema (Design Spec section 3.9)

CREATE TABLE IF NOT EXISTS users (
    user_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    username        TEXT NOT NULL UNIQUE,
    password_hash   TEXT NOT NULL,
    role            TEXT NOT NULL CHECK (role IN ('ADMIN', 'ATTENDANT')),
    failed_attempts INTEGER NOT NULL DEFAULT 0,
    locked_until    TEXT
);

CREATE TABLE IF NOT EXISTS vehicles (
    vehicle_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    plate_number TEXT NOT NULL UNIQUE,
    vehicle_type TEXT NOT NULL CHECK (vehicle_type IN ('TWO_WHEELER', 'CAR', 'EV'))
);

CREATE TABLE IF NOT EXISTS slots (
    slot_id  TEXT PRIMARY KEY,
    category TEXT NOT NULL CHECK (category IN ('TWO_WHEELER', 'CAR', 'ACCESSIBLE', 'EV')),
    status   TEXT NOT NULL DEFAULT 'VACANT' CHECK (status IN ('VACANT', 'OCCUPIED', 'RESERVED'))
);

-- Facility layout, one row per grid cell (REQ-NAV-01)
CREATE TABLE IF NOT EXISTS grid_cells (
    row_no    INTEGER NOT NULL,
    col_no    INTEGER NOT NULL,
    cell_type TEXT NOT NULL CHECK (cell_type IN ('ROAD', 'SLOT', 'WALL', 'ENTRANCE', 'EXIT')),
    slot_id   TEXT REFERENCES slots (slot_id),
    PRIMARY KEY (row_no, col_no)
);

CREATE TABLE IF NOT EXISTS tickets (
    ticket_id  TEXT PRIMARY KEY,
    vehicle_id INTEGER NOT NULL REFERENCES vehicles (vehicle_id),
    slot_id    TEXT NOT NULL REFERENCES slots (slot_id),
    entry_time TEXT NOT NULL,
    exit_time  TEXT,
    status     TEXT NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE', 'CLOSED'))
);

-- A slot can hold only one open ticket at a time (NFR-REL-02)
CREATE UNIQUE INDEX IF NOT EXISTS idx_one_active_ticket_per_slot
    ON tickets (slot_id) WHERE status = 'ACTIVE';

CREATE TABLE IF NOT EXISTS payments (
    payment_id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_id  TEXT NOT NULL REFERENCES tickets (ticket_id),
    amount     INTEGER NOT NULL,
    status     TEXT NOT NULL CHECK (status IN ('SUCCESS', 'FAILED')),
    paid_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_log (
    log_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id   INTEGER REFERENCES users (user_id),
    action    TEXT NOT NULL,
    old_value TEXT,
    new_value TEXT,
    logged_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS dwell_history (
    record_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    vehicle_type TEXT NOT NULL,
    entry_time   TEXT NOT NULL,
    exit_time    TEXT NOT NULL,
    duration_min INTEGER NOT NULL
);

-- Configurable values such as hourly rates and the grace period
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- The audit log is append-only, even for code that reaches the database directly (SEC-08)
CREATE TRIGGER IF NOT EXISTS audit_log_no_update BEFORE UPDATE ON audit_log
BEGIN
    SELECT RAISE(ABORT, 'audit_log is append-only');
END;

CREATE TRIGGER IF NOT EXISTS audit_log_no_delete BEFORE DELETE ON audit_log
BEGIN
    SELECT RAISE(ABORT, 'audit_log is append-only');
END;
