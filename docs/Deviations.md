# Deviations from the SRS, Design Specification and Test Plan

Team 10 – Vehicle Parking System – end of Sprint 2 (30 October 2026)

This is the complete list, replacing `docs/Sprint1_Deviations.md`. Each row gives what the document
says, what was built and why.

## 1. Requirements and design

| # | Area | Document says | What we built | Reason |
|---|---|---|---|---|
| D-01 | Facility layout | OR-01 gives a 6 x 8 grid and slot counts | Exact cell positions chosen in `vps/seed.py`, so that the slot numbers and paths match the Test Plan | The documents give counts and some results, not the positions |
| D-02 | Tables | Design Spec 3.9 lists seven tables | Also `grid_cells` (editable layout) and `settings` (rates, grace, Demo Clock, payment mode) | Needed for REQ-NAV-01 and configurable rates |
| D-03 | User table | user_id, username, password_hash, role | Also `failed_attempts`, `locked_until`, `session_token` | Needed for SEC-02 and for refusing a cookie after logout (TC-17) |
| D-04 | Exit API | POST /api/parking/exit returns fee and receipt | Returns duration and fee; the receipt comes from POST /api/payment/mock | Design Spec 4.3: no closing or slot release before payment succeeds |
| D-05 | Grace boundary | Rs. 0 "within" the grace period | Exactly 5:00 is free, 5:01 is charged | Matches TC-06; the SRS does not state the boundary |
| D-06 | Error codes | Design Spec 4.3 lists five | Also INVALID_PLATE, INVALID_VEHICLE_TYPE, INVALID_START_POINT, DUPLICATE_ACTIVE_TICKET, MISSING_TICKET_ID, LOGIN_REQUIRED, FORBIDDEN, CSRF_FAILED and others | Validation and access control need their own codes |
| D-07 | Mock payment status | 4.2 says 200 for success or failure; 4.3 says 402 | Failure returns HTTP 402 | The two sections conflict; 402 cannot be mistaken for success |
| D-08 | Slot admin API | POST /api/admin/slots | POST /api/slots/{id}/reserve, and the layout and reservation forms under /admin | Reserving and editing are separate actions |
| D-09 | Extra endpoints | Not in Design Spec 4.2 | /api/parking/preview, /api/admin/payment-mode, /admin/demo-clock, /admin/demo-data | Needed for REQ-NAV-04, REQ-PAY-02, OR-04, REQ-PRED-04 |
| D-10 | Driver access | SRS 2.3: driver uses entry, exit and availability without login | All screens need a staff login; the attendant operates them for the driver | Story #22: only staff reach staff screens |
| D-11 | Layout editing | REQ-NAV-01: editable grid | A text editor rather than a drag-and-drop grid; a slot with parking history cannot be removed | Tickets must keep pointing at a real slot |
| D-12 | Sessions | SEC-06 | Sessions of one user share a server-side token, so logging out on one device ends all of them | A cookie must stop working after logout (TC-17) |
| D-13 | Module split | QA-MOD-01: UI, business logic and data access in separate modules | UI is in templates and static files. Each feature module (such as `parking.py`) holds its routes, logic and SQL together, not in three layers | Feature modules were simpler at this size. Partly met; can be refactored if required |
| D-14 | Prediction with free slots | REQ-PRED-03 | With no vehicle parked in a category, the estimate shows "Estimate unavailable" | The formula is defined over occupied slots |

## 2. Test Plan

| # | Area | Document says | Actual | Reason |
|---|---|---|---|---|
| D-15 | Results columns | Test Plan v1.0 lists actual results and Pass for all 17 cases | Those values were written before the code existed. Real results are in `docs/Test_Results.md` | Results can only be recorded after running the build |
| D-16 | TC-13 usability | Run with 5 first-time users | Not run yet | Planned for the testing sprint |
| D-17 | TC-12 install | Fresh install on Windows, Ubuntu, macOS | Windows by hand; Ubuntu and macOS through CI test runs | No team access confirmed to those machines |
| D-18 | Test count | 48 automated tests | 211 automated tests | Wider coverage than planned |
| D-19 | Timing checks | Test Plan measures timing on a reference machine | Wall-clock checks run on the developer laptop and are skipped on GitHub Actions | Shared runners vary too much (one Windows run measured 2.5 s) |

## 3. Process

| # | Area | Plan | Actual |
|---|---|---|---|
| P-01 | #3 setup | Sprint 1 | Code written during the dry-run week, merged on 23 October |
| P-02 | Sprint 1 pace | Stories completed across 19 to 23 October | The stories were merged together on 23 October, the last day of the sprint |
| P-03 | Sprint 2 pace | Stories completed across 26 to 30 October | The stories were raised together at the end of the sprint |
| P-04 | Late fix | Not planned | #37 aligned the layout and passwords with the Test Plan in Sprint 2 |
| P-05 | Tools | Handout 2e allows GPTs | Generative AI was used to help implement and document the project. All pull requests were raised and reviewed by team members |

**Learning for the testing sprint:** work is split into small daily pull requests, so that progress
shows across the week and problems such as P-04 surface earlier.
