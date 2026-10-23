# Sprint 1 – Deviations from the SRS and Design Specification

Team 10 – Vehicle Parking System – Sprint 1 (19 to 23 October 2026)

This file lists every place where the Sprint 1 implementation differs from, or adds detail to,
SRS v2.0 and the Architecture & Design Specification v1.0, and the reason for each.

## 1. Design details decided during implementation

| # | Area | Document says | What we built | Reason |
|---|---|---|---|---|
| D-01 | Facility layout | SRS OR-01: a 6 x 8 grid with 20 slots (10 Car, 4 Two-Wheeler, 2 Accessible, 4 EV) | The position of every slot, road, wall, entrance and exit is defined in `vps/seed.py` | The SRS gives only the counts, not the positions |
| D-02 | Database tables | Design Spec 3.9 lists User, Vehicle, ParkingSlot, ParkingTicket, Payment, AuditLog, DwellHistory | Two extra tables: `grid_cells` (the editable layout, REQ-NAV-01) and `settings` (rates, grace period, Demo Clock offset, payment mode) | Needed to make the layout and the rates configurable as the SRS requires |
| D-03 | User table | Design Spec 3.9: user_id, username, password_hash, role | Two extra columns `failed_attempts` and `locked_until` | Prepared for account lockout (SEC-02) in Sprint 2 |
| D-04 | Exit API | Design Spec 4.2: POST /api/parking/exit returns "Fee + receipt" | The exit call returns duration and fee only; the receipt comes from POST /api/payment/mock | Design Spec 4.3: the ticket must not be closed or the slot released until payment succeeds |
| D-05 | Grace boundary | SRS REQ-PAY-01: Rs. 0 "within" the grace period | A stay of exactly 5:00 is free; 5:01 is charged one hour | The SRS does not say which side of the boundary 5:00 falls on |
| D-06 | Error codes | Design Spec 4.3 lists NO_SLOT_AVAILABLE, TICKET_NOT_FOUND, TICKET_CLOSED, SLOT_CONFLICT, PAYMENT_FAILED | Also INVALID_PLATE, INVALID_VEHICLE_TYPE, DUPLICATE_ACTIVE_TICKET, MISSING_TICKET_ID, LOGIN_REQUIRED (401) and FORBIDDEN (403) | Input validation and access control need their own clear error codes |
| D-07 | Mock payment status | Design Spec 4.2 says the mock payment returns 200 for success or failure; 4.3 says PAYMENT_FAILED is 402 | Failure returns HTTP 402 PAYMENT_FAILED | Follows the error-handling table so a failure cannot be mistaken for success |
| D-08 | Slot reservation | Design Spec 4.2: POST /api/admin/slots adds or updates a slot | POST /api/slots/{id}/reserve (admin only) reserves or releases a vacant slot; adding and editing slots stays in Sprint 2 (#25) | Reserving was needed now for the Reserved status in REQ-SLOT-01 |
| D-09 | Payment mode switch | Not in Design Spec 4.2 | Admin-only POST /api/admin/payment-mode and a switch on the dashboard, each change written to the audit log | REQ-PAY-02 needs a way for the admin to force a failure |
| D-10 | Driver access | SRS 2.3: the simulated driver uses entry, exit and availability screens without logging in | All screens need a staff login; the attendant operates entry and exit for the driver | Story #22: only staff may reach the staff screens; one login model is simpler and safer |
| D-11 | Continuous integration | Handout: enable GitHub Actions | flake8 and pytest run on Ubuntu and Windows with Python 3.10 and 3.12 | Also checks the portability requirement QA-POR-01 on every pull request |

## 2. Schedule

| # | Story | Planned | Actual |
|---|---|---|---|
| S-01 | #3 Set up Flask application and SQLite database | Sprint 1 | Built in the dry-run week (12 to 16 Oct) as practice, PR #21 |
| S-02 | All other Sprint 1 stories (#5, #6, #7, #12, #13, #22, #23, #8) | Sprint 1 | Pull requests raised and reviewed in the last days of Sprint 1, so integration happened later than planned |

Any Sprint 1 story that was not merged by the end of 23 October has been moved to Sprint 2 on the project board.
