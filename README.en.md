# HOIM Hospital Information Management System

[中文](README.md) | **English**

A comprehensive hospital information management system for small and medium-sized hospitals, built with **Vue 3 + FastAPI**, covering core business flows including **outpatient, inpatient, pharmacy, lab, physical examination, and billing**.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Vue](https://img.shields.io/badge/Vue-3.x-4FC08D)](https://vuejs.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.111+-009688)](https://fastapi.tiangolo.com/)
[![Python](https://img.shields.io/badge/Python-3.10+-blue)](https://www.python.org/)

---

## 📊 Project Scale

| Metric | Count |
|:------:|:-----:|
| Business Modules | **80** backend routers |
| API Endpoints | **560** route methods (authoritative count: generated RBAC matrix) |
| Database Tables | **145** business tables |
| Frontend Pages | **154** Vue pages |
| User Roles | **11**, including super admin, lab technician, and registrar |

---

## 🌟 Features

### Implemented Core Business (9 Domains / 40+ Modules)

- **Outpatient Management** — Smart Triage, Appointment, Walk-in Registration, Check-in, Queue Management, Triage Desk, Patrol Records, Breach Records, Billing, Invoice, Daily Settlement
- **Doctor Workstation** — Scheduling, EMR, Prescription, context-aware CDSS, Lab Orders, Attendance, MDT Consultation, Clinical Pathway
- **Pharmacy** — Drug Management, Consumables, Audit & Dispense, Stock Alert, Stock Check, Purchase, Prescription Review, ADR Monitoring
- **Inpatient Management** — Ward & Bed, Admission, Inpatient Orders, barcode-verified eMAR, Nursing Station, Inpatient Charges, Discharge Settlement
- **Electronic Medical Record (EMR)** — Templates, Structured Records, Progress Notes, Ward Rounds, Quality Control, CA Digital Signature
- **Lab & Physical Exam** — Lab Orders, Results, Exam Packages, Appointments, Records, Reports
- **Surgery** — Surgery Application, Scheduling, Anesthesia Records
- **Patient Services** — Health Records, EMR Query, Prescription Query, Prepaid Account, Two-way Referral, Follow-up, Satisfaction Survey
- **System Platform** — User & Permissions, Operation Logs (auto-recorded by middleware), Dictionary, Parameters, Messages, Notices, Backup, Adverse Events (with RCA root-cause analysis), Slot Pool, Reports, Department Performance

### HIS Completion Modules (4 batches delivered 2026-08, zero seed data — all user-entered)

- **Prescription Review Rule Engine** — 5 rule types (interaction / contraindication / dose / duplicate / allergy-keyword); severity-3 rules **block both prescribing and dispensing**
- **Insurance Catalog Mapping** — local items ↔ insurance codes with category/self-pay ratio/price limit; template download + batch import
- **CSSD** — full instrument-pack state machine (0-6) with BD-test and biological-monitor gates
- **PIVAS** — batch flow with mandatory **dual-person check** (dispenser cannot verify own batch)
- **ICU/PACU Scoring** — server-side APACHE II / SOFA / GCS / Aldrete / Steward with discharge criteria
- **Clinical Pathway Enrollment** — enroll / progress / 4-type variation / completion-gated exit
- **MDRO Isolation / Hand Hygiene / Notifiable Disease Reporting / HQMS Indicators** — infection-control suite with auto disease-class inference and report state machine
- **Archive Borrow Approval** — request → approve/reject → return-and-reset workflow with approval desk
- **ICD Coding Workbench** — dictionary-validated binding of diagnoses/operations, single primary code, coverage stats
- **Department Performance** — (workload − cost) × coefficient computed server-side; draft → submit → audit
- **Perioperative Antibiotic Compliance / Green-channel Billing Closure / Pay-date Settlement / Scrap Batch Ledger**
- **Versioned DRG/DIP Auto-grouping / Daily Operational Aggregates / Durable Integration Outbox**

### Planned Modules

| Module | Description |
|:------:|:------------|
| National Insurance Adapter | Catalogs, callbacks, and versioned DRG/DIP rules are delivered; platform signatures, e-credentials, and official grouper releases require local integration |
| DICOM Archive | Imaging orders, reports, an external viewer, and PACS callbacks are delivered; native DICOM storage/routing remains planned |
| Professional CDSS Knowledge Base | Structured clinical context and local rules are delivered; validated reference content, lab trends, and renal-dose algorithms remain planned |
| Internet Hospital | Online consultation, follow-up prescription |

> See [doc/todos.md](doc/todos.md) for the full roadmap and [doc/his-feature-gap-analysis.md](doc/his-feature-gap-analysis.md) for the HIS gap analysis and delivery record.

---

## 🏗 Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                  Frontend (Browser)                          │
│        Vue 3 · Element Plus · Vuex · Vue Router · Rspack    │
├─────────────────────────────────────────────────────────────┤
│                  Application (FastAPI)                       │
│   80 routers · 560 route methods · JWT/RBAC · Metrics/Audit  │
├─────────────────────────────────────────────────────────────┤
│                  Data Layer                                  │
│             SQLite (dev) / PostgreSQL (prod)                 │
│                   SQLAlchemy ORM · Alembic                   │
└─────────────────────────────────────────────────────────────┘
```

### Tech Stack

| Layer | Technologies |
|:-----:|:-------------|
| Frontend | Vue 3.5+ / Element Plus 2.x / Vuex 4 / Vue Router 5 / Axios / Rspack 2 |
| Backend | FastAPI 0.111+ / SQLAlchemy 2.x / Pydantic 2.x / Alembic |
| Database | SQLite (development only) / PostgreSQL (required in production) |
| Containerization | Docker / Docker Compose |
| Code Quality | ruff (Python) / Prettier (JavaScript) |
| Testing | pytest (backend API testing) |
| Security | bcrypt password hashing, JWT sessions, operation log auditing |

---

## 🚀 Quick Start

### Requirements

| Component | Version |
|:---------:|:-------:|
| Node.js | 20.19+ or 22.12+ |
| Python | ≥ 3.10 |
| Database | SQLite included (no install needed) |

### 1. Clone

```bash
git clone https://github.com/Palpitate-xus/hoimsystem.git
cd hoimsystem
```

### 2. Start Backend

```bash
cd fastapi_be

# Create virtualenv
python -m venv venv
source venv/bin/activate    # Linux/Mac
# venv\Scripts\activate     # Windows

# Install dependencies
pip install -r requirements.txt

# Run (auto-creates tables on first launch)
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Visit http://localhost:8000/docs for the auto-generated Swagger UI.

### 3. Start Frontend

```bash
cd vue3-new-ui

# Install dependencies
npm install --legacy-peer-deps

# Dev mode (port 8091)
npm run serve:rspack

# Production build
npm run build
```

### 4. Access

- Frontend: http://localhost:8091
- Backend API: http://localhost:8000/api
- API Docs: http://localhost:8000/docs

### 5. Docker (recommended for production)

```bash
export POSTGRES_PASSWORD='replace-with-a-strong-database-password'
export SECRET_KEY="$(openssl rand -base64 48)"
export ALLOWED_ORIGINS='https://his.example.com'
docker compose up -d
```

See [doc/deployDoc.md](doc/deployDoc.md) for detailed deployment instructions (Nginx, HTTPS, Systemd).

---

## 🔑 Default Accounts

These accounts are written only when the development initializer `fastapi_be/init_database.py` is run. Normal application startup and production migrations do not create them.

| Role | Username | Password | Note |
|:----:|:--------:|:--------:|:----:|
| Admin | `admin` | `admin123` | Full permissions |
| Super Admin | `super01` | `123456` | Highest permissions |
| Director | `director01` | `123456` | Department management |
| Doctor | `doctor1` | `doctor123` | Regular doctor |
| Nurse | `nurse01` | `123456` | Nursing work |
| Cashier | `cashier01` | `123456` | Cashier desk |
| Pharmacist | `pharmacist01` | `123456` | Pharmacy work |
| Guide | `guide01` | `123456` | Guidance desk |
| Lab Technician | `lab01` | `123456` | Laboratory work |
| Registrar | `registrar01` | `123456` | Registration service |
| Patient | `patient1` | `123456` | Patient self-service |

> ⚠️ Never run the demo initializer against production. Provision production users through a controlled process and use an independent strong random `SECRET_KEY`.

---

## 👥 Roles

| Role | Permissions |
|:----:|:------------|
| **Admin** | Full system management |
| **Super Admin** | Highest-privilege global administration account |
| **Director** | Department management, scheduling, prescription review |
| **Doctor** | EMR writing, prescription, lab orders |
| **Nurse** | Triage, vital signs, nursing, follow-up |
| **Cashier** | Walk-in registration, billing, daily settlement |
| **Pharmacist** | Prescription audit, dispense, inventory |
| **Guide** | Triage desk, smart triage, queue |
| **Lab Technician** | Samples, results, critical values, and laboratory quality control |
| **Registrar** | Window appointment confirmation, cancellation, and patient cards |
| **Patient** | Self-service: appointments, billing, records |

---

## 📚 Documentation

| Document | Description |
|:--------:|:------------|
| [Doc Index](doc/README.md) | Navigation for all docs |
| [Architecture](doc/architecture.md) | System architecture & design decisions |
| [Requirements](doc/demandDoc.md) | Functional & non-functional requirements |
| [API Doc](doc/apiDoc.md) | core API definitions (560 total in the RBAC matrix) |
| [Database Doc](doc/databaseDoc.md) | core table definitions; all 145 tables are authoritative in the models |
| [Deployment](doc/deployDoc.md) | Dev/prod/Docker deployment guide |
| [User Manual](doc/user-manual.md) | Role-based operation guide |
| [Roadmap](doc/todos.md) | Completed & planned modules |
| [Security](SECURITY.md) | Security policy |
| [Contributing](CONTRIBUTING.md) | Code style & PR workflow |
| [Changelog](CHANGELOG.md) | Version history |

---

<a id="performance-benchmark"></a>

## ⚡ Performance Benchmark

### Reproducible PostgreSQL Harness

The benchmark uses an isolated PostgreSQL container, four Gunicorn workers, and an ephemeral data volume. Destructive initialization accepts only a database named `hoimsystem_benchmark` and requires `BENCHMARK_RESET_CONFIRM` to match it. The `smoke`, `small`, `medium`, and `large` profiles scale up to 100,000 patients and 500,000 history rows.

```bash
cd fastapi_benchmark

# small is the default; smoke, medium, and large are also available
BENCHMARK_PROFILE=small docker compose up --build -d

# Tokens are generated by live logins; writes use valid patient and doctor roles
locust -f locust_final.py --headless -u 50 -r 10 -t 5m \
  --host http://localhost:18000 --csv=benchmark_results/mixed_50u \
  --exit-code-on-error 1

docker compose down -v
```

Every Locust request validates both the HTTP status and response-body `code == 200`. Run metadata records the commit, data profile, load parameters, and redacted database target. Historical CSV files came from an older harness and are not a capacity or SLA baseline; rerun the workload on target hardware and record P95/P99, errors, pool waits, and PostgreSQL slow queries.

---

## ✨ Highlights

- **Broad coverage**: Outpatient + Inpatient + Pharmacy + Lab + Exam + Surgery, 9 domains 40+ modules
- **Clean code**: 560 route methods organized by module, frontend/backend separation, and CI-enforced lint, tests, audits, and bundle budgets
- **Great DX**: FastAPI auto docs, hot reload, zero-config SQLite startup
- **Observable**: Liveness/readiness probes, Prometheus metrics, request IDs, operation auditing, and daily operational aggregates
- **Secure**: JWT auth, bcrypt passwords, ID masking, operation auditing
- **Good UX**: Element Plus components, unified style utilities, full empty/loading states

---

## 📷 Screenshots

![Patient Access Flow](doc_assets/PatientAccessFlow.png)

More screenshots in [doc_assets/](doc_assets/).

---

## 📄 License

[MIT](LICENSE)

---

## 🤝 Contributing

Issues and Pull Requests are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md) for details.

**Contact**: palpitate.xus@outlook.com
