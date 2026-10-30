# Test Results – Test Plan VPS-TP-01

Actual results from running the Test Plan against the real build at the end of Sprint 2.
They replace the "Actual" and "Pass" columns in Test Plan v1.0, which were written before the
code existed (see `docs/Deviations.md`, D-15).

**How to repeat:** `python -m pytest tests/test_plan_cases.py -v` and `python -m scripts.perf_check`.
GitHub Actions runs the same tests on every pull request on Ubuntu, Windows and macOS with Python
3.10 and 3.12.

| TC | Requirements | What was checked | Actual result | Status |
|---|---|---|---|---|
| TC-01 | LOG-01..03, SLOT-01, NAV-02 | "TN 09 AB 1234", Car, all slots vacant | Stored as TN09AB1234, ticket VPS-YYYYMMDD-NNNN, QR served, S01 Occupied, entry time to the second | Pass |
| TC-02 | LOG-01, LOG-04, REL-01 | "", "AB1", 12 characters, "TN-09@AB"; repeat active plate | HTTP 400 with a clear message and no ticket; duplicate HTTP 409; no stack trace | Pass |
| TC-03 | SLOT-03 | EV, Two-Wheeler, Car with Accessible | S17, S11, S15 | Pass |
| TC-04 | NAV-01..04 | S01, S02 occupied; route; exit mode; target taken | S03 with path 4; S10 in exit mode; next best slot assigned in under 500 ms | Pass |
| TC-05 | SLOT-04, PRED-01..03 | Car slots full, average 90 min, longest parked 86 min | Refused: "No Car slot available", "expected in about 4 min" | Pass |
| TC-06 | PAY-01, BR-01, BR-02 | Car 2 h 10 min; EV 1 h 0 min 1 s; Car 4:59, 5:00, 5:01 | Rs. 120; Rs. 100; Rs. 0, Rs. 0, Rs. 40 | Pass |
| TC-07 | PAY-02, 03, REL-04 | Pay with force failure on, then off | HTTP 402, ticket active, slot occupied; then receipt, slot Vacant, gate OPEN | Pass |
| TC-08 | REP-01..03, PERF-05 | Daily, weekly, monthly over 30 days; CSV; PDF | Totals equal SQL SUM; peak hour shown; exports generated; report in 41 ms | Pass |
| TC-09 | PRED-04, OR-01, BR-03, OR-04 | Fresh DB; seed; clock to 23 h 55 m, then 24 h 5 m | 20 slots, 2 accounts, 200 records; Overstay only after 24 h | Pass |
| TC-10 | PERF-01, 02, 04, SLOT-02 | 20 entries and exits; BFS 100 runs on 100 cells | P95 23 ms; BFS max 0.33 ms; grid polls every 500 ms | Pass |
| TC-11 | PERF-03, REL-02 | Parallel entries, then 5 for 1 free slot | All distinct slots; exactly 1 success, 4 refused; no duplicate active slot | Pass |
| TC-12 | REL-03, OR-02, QA-POR-01 | Restart with active ticket; other operating systems | No data lost. Windows run by hand; Ubuntu and macOS covered by the CI test run, not by a manual install | Pass (CI for Ubuntu and macOS) |
| TC-13 | QA-USE-01 | 5 first-time users, entry to receipt, unaided | Needs real users; planned for the testing sprint | **Not run** |
| TC-14 | SEC-01, 02 | Users table; 5 wrong passwords; correct one; 5 min later | Distinct scrypt hashes; locked and logged; unlocks after 5 min (Demo Clock) | Pass |
| TC-15 | SEC-03, 08, USR-01, 02 | Attendant on admin routes; admin rate change; audit DELETE | 403 and logged; old and new values audited; DELETE returns 405 | Pass |
| TC-16 | SEC-04, 05 | SQL injection strings in plate, ticket, login; script tag | No bypass or database change; script shown as escaped text | Pass |
| TC-17 | SEC-06, 07 | Cookie flags; idle 16 min; replay after logout; bad CSRF tokens | HttpOnly and SameSite=Lax; redirected to login; old cookie refused; HTTP 400 | Pass |

**Timing checks:** the figures above come from `scripts/perf_check.py` on a developer laptop, as
the Test Plan measures timing on a reference machine. Automated timing checks are switched off on
GitHub Actions, because shared runners vary too much: one Windows run measured a P95 of 2.5 s for
entry plus paid exit while the other five jobs passed. No target is checked on those machines.

**Summary:** 16 of 17 run and passing, TC-13 not yet run. Timings were measured on one developer
laptop with Python 3.14. Defect found while testing: a second login ended the first session
(fixed in #26), and the layout and passwords differed from the Test Plan (fixed in #37).
