# Vehicle Parking System

A software-only parking management system that simulates vehicle entry/exit, parking slot allocation, fee calculation, payment, reporting, smart slot assignment and predictive slot availability.

**Status:** In Development  
**Documentation:** SRS v1.1 · Test Plan v1.0

## Team Members

**Ananya V**: PES1UG24CS061
**Amogh Sharma**: PES1UG24CS053 
**Nagaraja Gari Ram Sai Govind**: PES1UG24CS912 

## Key Features

- **Slot Management:** Tracks vacant/occupied slots and slot categories.
- **Entry & Exit:** Records vehicle details, timestamps and generates tickets.
- **Fee & Payment:** Calculates parking fees and provides mock payment and receipts.
- **Reports:** Generates occupancy and revenue reports with export support.
- **Access Control:** Supports role-based access and audit logging.
- **Smart Slot Assignment:** Uses BFS-based pathfinding to assign suitable parking slots and display routes.
- **Predictive Availability:** Estimates when occupied slots may become available using historical parking data.

## How It Works

```text
Vehicle Entry
     ↓
Slot Availability Check
     ↓
Smart Slot Assignment
     ↓
Ticket Generation
     ↓
Vehicle Parked
     ↓
Vehicle Exit
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
| LPR/RFID | Manual plate/ticket entry |
| Occupancy Sensor | Slot status flag |
| Boom Barrier | Software gate indicator |
| Payment Gateway | Mock payment |

## System Setup

The demonstration system uses:

- **20 parking slots**
- **4 × 5 grid**
- **200+ synthetic parking records**
- Admin and Attendant roles
- Configurable parking rate and grace period

The system is designed to run locally without physical hardware.

## Project Modules

```text
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

## Testing

Testing covers:

- Functional requirements
- Security requirements
- Performance and reliability
- Slot allocation and pathfinding
- Fee calculation
- Entry/exit processing
- Reporting
- Predictive availability

The Test Plan contains **18 test cases** with requirements traceability.

## Documentation

| Document | Description |
|---|---|
| **SRS v1.1** | Software requirements and system requirements |
| **Test Plan v1.0** | Testing strategy, test cases and RTM |
| **Architecture & Design Specification** | System architecture, UML diagrams, API design and error handling |

## Future Scope

- Real LPR/RFID and parking sensors
- Real payment gateway integration
- Machine-learning-based prediction
- Mobile/kiosk application
- Multi-facility support
- Cloud deployment
