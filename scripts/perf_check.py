"""Measure the timing targets of the Test Plan (TC-04, TC-08, TC-10).

Run from the project folder: python -m scripts.perf_check
Uses a temporary database, so the demo data is not touched.
"""
import tempfile
import time
from pathlib import Path

from vps import create_app
from vps.grid import nearest_slot


def p95(values):
    """Return the 95th percentile of the measured values."""
    return sorted(values)[max(0, round(len(values) * 0.95) - 1)]


def main():
    """Print the measured figures."""
    with tempfile.TemporaryDirectory() as folder:
        app = create_app({"TESTING": True, "DATABASE": str(Path(folder) / "perf.db")})
        client = app.test_client()
        client.post("/login", data={"username": "admin", "password": "Admin@123"})

        timings = []
        for n in range(20):
            started = time.perf_counter()
            ticket = client.post("/api/parking/entry",
                                 json={"plate": f"PERF{n:04d}", "vehicle_type": "CAR"}).get_json()
            client.post("/api/payment/mock", json={"ticket_id": ticket["ticket_id"]})
            timings.append(time.perf_counter() - started)
        print(f"Entry to paid exit, 20 trials: P95 {p95(timings) * 1000:.0f} ms")

        grid = [[("ROAD", None)] * 10 for _ in range(10)]
        grid[0][0] = ("ENTRANCE", None)
        grid[9][9] = ("SLOT", "S01")
        runs = []
        for _ in range(100):
            started = time.perf_counter()
            nearest_slot(grid, {"S01"})
            runs.append(time.perf_counter() - started)
        print(f"BFS on a 100-cell grid, 100 runs: max {max(runs) * 1000:.2f} ms")

        client.post("/admin/demo-data", json={})
        started = time.perf_counter()
        client.get("/reports")
        print(f"30-day report: {(time.perf_counter() - started) * 1000:.0f} ms")


if __name__ == "__main__":
    main()
