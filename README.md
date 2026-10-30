# Vehicle Parking System

[![CI](https://github.com/Software-Engineerining-Mini-Project/Vehicle-Parking-System/actions/workflows/ci.yml/badge.svg)](https://github.com/Software-Engineerining-Mini-Project/Vehicle-Parking-System/actions/workflows/ci.yml)

A software-only parking management system that simulates vehicle entry/exit, slot allocation, fee calculation, mock payment and reporting, with two advanced features: **BFS-based smart slot assignment** and **predictive slot availability**.

**Status:** Development frozen after Sprint 2; testing sprint next
**Documentation:** SRS v2.0 · Test Plan v1.0 · Architecture & Design Specification v1.0

## Team 10

| Name | SRN |
|---|---|
| Ananya V | PES1UG24CS061 |
| Amogh Sharma | PES1UG24CS053 |
| Nagaraja Gari Ram Sai Govind | PES1UG24CS912 |

## Getting Started

Requires Python 3.10 or newer. Works on Windows, macOS and Linux.

```bash
git clone https://github.com/Software-Engineerining-Mini-Project/Vehicle-Parking-System.git
cd Vehicle-Parking-System
python -m pip install -r requirements.txt
python run.py
```

Open http://localhost:5000. The first run creates `instance/vps.db` with the demo layout and accounts:

| Role | Username | Password |
|---|---|---|
| Administrator | `admin` | `Admin@123` |
| Attendant | `attendant` | `Attend@123` |

Delete the `instance` folder to start again with a fresh database.

```bash
python -m pytest
```

```bash
python -m flake8 .
```

## Key Features

- **Slot Management:** tracks vacant, occupied and reserved slots in four categories (Two-Wheeler, Car, Accessible, EV).
- **Entry & Exit:** records the plate and vehicle type, timestamps every event and generates a ticket ID with a QR code.
- **Fee & Payment:** calculates the fee per started hour after a grace period, then runs a mock payment and shows a receipt.
- **Reports:** daily, weekly and monthly occupancy and revenue reports with CSV/PDF export and peak-hour analytics.
- **Access Control:** Admin and Attendant roles, hashed passwords, account lockout and an append-only audit log.
- **Smart Slot Assignment:** models the facility as a grid and uses BFS to pick the nearest matching slot and draw the route.
- **Predictive Availability:** estimates when the next slot will free up from average dwell times (a simple heuristic, not ML).

## How It Works

```
Vehicle Entry (plate + type)
     ↓
Slot Availability Check
     ↓
Smart Slot Assignment (BFS) + Route
     ↓
Ticket + QR Generated
     ↓
Vehicle Parked
     ↓
Vehicle Exit (ticket ID)
     ↓
Fee Calculation
     ↓
Mock Payment
     ↓
Receipt + Slot Released
```

## Simulated Hardware

| Real Device | Software Equivalent |
|---|---|
| LPR camera / RFID reader | Manual plate entry or generated ticket/QR |
| Occupancy sensor | Slot status flag |
| Boom barrier | On-screen Open/Closed gate indicator |
| Payment gateway | Mock payment (success, or failure when forced by the admin) |

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend | HTML, CSS, JavaScript |
| Backend | Python 3.10+, Flask |
| Database | SQLite |
| Security | Werkzeug password hashing, Flask-WTF CSRF tokens, parameterised SQL |
| Extras | qrcode (ticket QR codes), ReportLab (PDF export) |
| Testing | pytest, OWASP ZAP baseline scan |

## Demo Setup

- 20 slots on a 6 × 8 grid: S01–S10 Car, S11–S14 Two-Wheeler, S15–S16 Accessible, S17–S20 EV
- Hourly rates: Two-Wheeler Rs. 20, Car Rs. 40, EV Rs. 50 (configurable)
- 5-minute grace period; fees charged per started hour
- Vehicles parked over 24 hours are flagged as overstay
- 200 synthetic parking records over 14 days for the prediction feature
- Admin and Attendant accounts
- Admin-only Demo Clock to simulate elapsed time
- Runs locally on one machine, no internet or hardware needed

## Project Modules

```
Vehicle Parking System
├── User Authentication
├── Slot Management
├── Vehicle Entry / Exit
├── Ticket & Fee Management
├── Mock Payment
├── Smart Slot Assignment
├── Predictive Availability
└── Reports & Analytics
```

## Project Structure

```
run.py                 starts the app
vps/grid.py            facility grid and BFS slot assignment
vps/parking.py         vehicle entry and exit, tickets, QR codes
vps/fees.py            fee and grace-period rules
vps/payment.py         mock payment and receipt
vps/slots.py           categories and the live slot grid
vps/prediction.py      predicted wait from average dwell time
vps/reports.py         occupancy and revenue reports, CSV and PDF
vps/admin.py           settings, layout editor, audit log page
vps/auth.py            login, roles, lockout, sessions
vps/demo.py            synthetic data, Demo Clock, overstay flag
vps/templates, static  screens, CSS and JavaScript
tests/                 pytest suite, including tests/test_plan_cases.py
scripts/perf_check.py  timing measurements
docs/                  documents, results, deviations, demo videos
```

## Testing

The Test Plan (VPS-TP-01) has **17 test cases (TC-01 to TC-17)**, each traced to the SRS through a requirements traceability matrix:

- **9 functional:** slot tracking, entry/exit, fees and payment, reports, BFS assignment, prediction
- **4 non-functional:** performance, concurrency, persistence, usability
- **4 security:** password hashing and lockout, role checks and audit log, SQL injection and XSS, sessions and CSRF

## Documentation

| Document | Description |
|---|---|
| [Software Requirements Specification v2.0](docs/01_Vehicle_Parking_System_SRS.docx) | Functional, non-functional and security requirements, use case diagram (IEEE 830) |
| [Test Plan v1.0](docs/02_Vehicle_Parking_System_Test_Plan.docx) | Test strategy, security validation, 17 test cases and RTM (IEEE 829) |
| [Architecture & Design Specification v1.0](docs/03_Vehicle_Parking_System_Architecture_Design.docx) | Layered architecture, UML diagrams, API design and error handling (IEEE 1016) |
| [Test Results](docs/Test_Results.md) | Actual results of TC-01 to TC-17 on the real build |
| [Deviations](docs/Deviations.md) | Every difference from the SRS, design spec and test plan, with reasons |
| Demo videos | [Sprint 1](docs/Sprint1_Demo.mp4), [Sprint 2](docs/Sprint2_Demo.mp4) |

## Future Scope

- Real LPR/RFID and parking sensors
- Real payment gateway integration
- Machine-learning-based prediction
- Mobile/kiosk application
- Multi-facility support
- Cloud deployment
