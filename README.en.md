# Hospital Outpatient Information Management System (HIS-OP)

[中文](README.md) | **English**

A hospital outpatient information management system based on Vue 3 + FastAPI, covering the full outpatient workflow including registration, diagnosis, billing, and pharmacy.

---

## Features

### Implemented Modules

| Module | Description | Status |
|:------:|:-----------|:------:|
| Authentication | User registration/login, RSA password encryption, role-based access control | ✅ |
| Patient Management | Patient registration, profile query, registration/appointment | ✅ |
| Doctor Management | Doctor registration, profile query, schedule management | ✅ |
| Department Management | Department creation, query, director assignment | ✅ |
| Registration & Appointment | Walk-in registration, online appointment, cancellation, history | ✅ |
| Prescription Management | Doctor prescription, auto stock deduction, prescription query | ✅ |
| Billing Management | Fee calculation, online payment, billing records | ✅ |
| Pharmacy Management | Drug entry, stock query, stock alert | ✅ |
| Notice & Announcement | Role-targeted push, emergency notification | ✅ |

### Planned Modules

| Module | Description | Status |
|:------:|:-----------|:------:|
| Medical Record | Electronic medical record creation, query | ✅ |
| Lab & Examination | Lab request, result entry, report viewing | ✅ |
| Queue & Calling | Waiting queue, voice calling, pass handling | ✅ |
| Pharmacy Dispensing | Prescription audit, dispensing confirmation, return handling | ✅ |
| Nurse Triage | Vital signs entry, allergy history marking | ✅ |
| Reports & Statistics | Outpatient volume, finance, pharmacy, workload stats | ✅ |
| Follow-up Management | Follow-up plans, revisit reminders | ✅ |
| Satisfaction Review | Post-visit review, rating statistics | ✅ |

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      Frontend Layer                          │
│                   vue3-new-ui                                │
│              Vue 3 + Element-Plus                            │
├─────────────────────────────────────────────────────────────┤
│                      Backend Layer                           │
│                   fastapi_be                                 │
│            FastAPI + SQLAlchemy                              │
├─────────────────────────────────────────────────────────────┤
│                      Data Layer                              │
│                   MySQL / SQLite                             │
└─────────────────────────────────────────────────────────────┘
```

### Tech Stack

| Layer | Technology |
|:-----:|:-----------|
| Frontend | Vue 3, Element-Plus, Axios, Pinia |
| Backend | FastAPI, SQLAlchemy, Pydantic |
| Database | MySQL 8.0, SQLite (development) |
| Security | RSA password encryption, accessToken session auth |

---

## Project Structure

```
hoimsystem/
├── vue3-new-ui/          # Vue 3 frontend (current main branch)
│   ├── src/
│   │   ├── views/        # Page components
│   │   ├── api/          # API wrappers
│   │   ├── router/       # Router config
│   │   └── store/        # Pinia state management
│   └── package.json
│
├── fastapi_be/           # FastAPI backend (current main branch)
│   ├── app/
│   │   ├── routers/      # Route modules
│   │   │   ├── user.py        # Authentication
│   │   │   ├── admin.py       # Admin
│   │   │   ├── patient.py     # Patient
│   │   │   ├── doctor.py      # Doctor
│   │   │   ├── pharmacy.py    # Pharmacy
│   │   │   ├── charge.py      # Billing
│   │   │   ├── queue.py       # Queue & Calling
│   │   │   ├── checkin.py     # Check-in
│   │   │   ├── vitalsign.py   # Nurse Triage
│   │   │   ├── lab.py         # Lab & Examination
│   │   │   ├── followup.py    # Follow-up
│   │   │   ├── report.py      # Reports
│   │   │   └── system.py      # System Management
│   │   ├── models.py     # Database models
│   │   ├── schemas.py    # Pydantic models
│   │   └── main.py       # Application entry
│   └── requirements.txt
│
├── doc/                  # Project documents
│   ├── demandDoc.md      # Requirements document
│   ├── apiDoc.md         # API document (82 endpoints)
│   ├── databaseDoc.md    # Database document (25 tables)
│   └── todos.md          # TODO list
│
├── doc_assets/           # Doc resources (screenshots, diagrams, SQL)
│
├── vue-ui/               # Vue 2.x frontend (deprecated, kept for reference)
├── django_be/            # Django backend (deprecated, kept for reference)
│
└── README.md             # This file
```

---

## Quick Start

### Prerequisites

- Node.js >= 16
- Python >= 3.8
- MySQL >= 8.0 (or SQLite)

### 1. Clone the project

```bash
git clone https://github.com/Palpitate-xus/hoimsystem.git
cd hoimsystem
```

### 2. Start the database

```bash
# Create MySQL database (or use SQLite)
mysql -u root -p -e "CREATE DATABASE hoimsystem CHARACTER SET utf8mb4;"
```

> No need to manually import table schema. SQLAlchemy will auto-create tables on the first FastAPI backend startup.

### 3. Start the backend (FastAPI)

```bash
cd fastapi_be

# Create virtual environment (recommended)
python -m venv venv
source venv/bin/activate  # Linux/Mac
# or venv\Scripts\activate  # Windows

# Install dependencies
pip install -r requirements.txt

# Run (auto-creates tables)
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### 4. Start the frontend (Vue 3)

```bash
cd vue3-new-ui

# Install dependencies
npm install

# Development mode
npm run serve

# Production build
npm run build
```

### 5. Access the system

- Frontend: http://localhost:8080
- Backend API: http://localhost:8000/api
- API Docs: http://localhost:8000/docs (Auto-generated Swagger UI by FastAPI)

---

## User Roles

The system supports four roles with cascading permissions:

| Role | Permission Scope |
|:----:|:----------------|
| Admin | Global management: doctors, patients, departments, drugs, notices, billing |
| Director | Department management: schedule, doctors in department, notices |
| Doctor | Clinical work: medical records, prescriptions, schedule viewing |
| Patient | Self-service: registration/appointment, payment, record viewing |

---

## Documentation

| Document | Description |
|:--------:|:-----------|
| [Requirements](doc/demandDoc.md) | Functional requirements, business flow, data needs, non-functional requirements |
| [API Document](doc/apiDoc.md) | All 82 API endpoints (76 implemented + 6 planned) |
| [Database Document](doc/databaseDoc.md) | 25 table definitions and ER diagram |
| [TODO](doc/todos.md) | Project todo list (categorized by priority) |

---

## Screenshots

![Patient Visit Flow](doc_assets/PatientAccessFlow.png)

More screenshots in [doc_assets/](doc_assets/) directory.

---

## Development Roadmap

See [doc/todos.md](doc/todos.md) for details.

Near-term priorities:
1. Password hashing with bcrypt
2. JWT token replacing plain string accessToken
3. API permission validation refinement
4. Frontend page completion (CRUD, reports)

---

## License

[MIT](LICENSE)

---

## Contributing

Issues and Pull Requests are welcome.

For questions, contact: palpitate.xus@outlook.com
