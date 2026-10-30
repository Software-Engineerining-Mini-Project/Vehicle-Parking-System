"""Parking fee rules (REQ-PAY-01, BR-01, BR-02).

Rs. 0 within the grace period; after that every started hour is charged at the
hourly rate for the vehicle type.
"""

RATE_KEYS = {"TWO_WHEELER": "rate_two_wheeler", "CAR": "rate_car", "EV": "rate_ev"}


def billable_hours(duration_seconds, grace_minutes):
    """Number of started hours to charge; 0 while still inside the grace period."""
    if duration_seconds <= grace_minutes * 60:
        return 0
    return -(-int(duration_seconds) // 3600)  # ceiling division


def calculate_fee(duration_seconds, hourly_rate, grace_minutes=5):
    """Return the fee in rupees for a stay."""
    return billable_hours(duration_seconds, grace_minutes) * hourly_rate


def load_tariff(db, vehicle_type):
    """Return (hourly_rate, grace_minutes) from the settings table."""
    settings = dict(db.execute("SELECT key, value FROM settings").fetchall())
    return int(settings[RATE_KEYS[vehicle_type]]), int(settings["grace_minutes"])


def format_duration(duration_seconds):
    """Write a duration in words, such as 2 h 10 min."""
    hours, rest = divmod(int(duration_seconds), 3600)
    minutes, seconds = divmod(rest, 60)
    if hours:
        return f"{hours} h {minutes} min"
    if minutes:
        return f"{minutes} min {seconds} s"
    return f"{seconds} s"
