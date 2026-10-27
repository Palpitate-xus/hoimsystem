# HOIM Hospital Information Management System

[中文](README.md) | **English**

A comprehensive hospital information management system for small and medium-sized hospitals, built with **Vue 3 + FastAPI**, covering core business flows including **outpatient, inpatient, pharmacy, lab, physical examination, and billing**.

The AI platform includes [80 capabilities](doc/ai-capabilities.md): 63 text LLM tasks, plus speech, imaging, ECG, risk assessment, forecasting, optimization and fixed local statistics. It provides a business workbench, individual task prompts, versioned source governance and a super-administrator management center. See the AI platform section below and the [usage guide](doc/ai-guide.md) for setup and delivery scope.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Vue](https://img.shields.io/badge/Vue-3.x-4FC08D)](https://vuejs.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.111+-009688)](https://fastapi.tiangolo.com/)
[![Python](https://img.shields.io/badge/Python-3.10+-blue)](https://www.python.org/)

---

## 📊 Project Scale

| Metric | Count |
|:------:|:-----:|
| Backend Router Modules | **134** mounted modules |
| API Endpoints | **1,087** RBAC route methods; see the [access matrix](doc/api-rbac-matrix.md) |
| Database Table Definitions | **266** ORM table definitions, including AI sources and governance |
| Frontend Pages | **160** Vue page files |
| User Roles | **11**, including super admin, lab technician, and registrar |
| AI Capability Catalog | **80** capabilities, including **63** text LLM tasks |

These counts describe repository source, not a deployed database or enabled AI features. Routes are checked against the statically generated RBAC inventory; pages are counted under `src/views/**/*.vue`.

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
| DICOM Archive | Orders, reports, an external viewer, PACS callbacks and private single-frame DICOM registration/preview are delivered; complete archive, routing and worklist integration remain planned |
| Clinical Knowledge and Deployment Validation | Knowledge version review, pathway import, laboratory/observation sources and independent risk checks are delivered; applicable content, model evaluation and local clinical validation remain deployment work |
| Internet Hospital | Online consultation, follow-up prescription |

> See [doc/todos.md](doc/todos.md) for the full roadmap and [doc/his-feature-gap-analysis.md](doc/his-feature-gap-analysis.md) for the HIS gap analysis and delivery record.

---

## AI Platform

The business workbench is at `/#/ai/workbench`; super-administrator management is at `/#/ai/manage`. Medical records, prescriptions, inpatient, pharmacy, laboratory and operational pages also provide entries bound to the current business record.

| Area | Current Implementation |
| --- | --- |
| Clinical assistance and documents | Patient summaries, differential diagnosis and treatment-pathway candidates, prescription review and record/report drafts; patient relationships, encounters, original records and applicable reviewed knowledge are checked per task |
| Speech, ECG and imaging | Private recordings with listening review, original WFDB files and waveforms, single-frame DICOM images and specialist adapters; optional local research services have separate preparation and verification workflows |
| Risk and fixed calculations | NEWS2, adult AKI, qSOFA, SOFA-1 daily six-axis assessments and change review, plus reviewed scheduling, bed, supply and inventory workflows; fixed calculations and model explanations remain separate |
| Sources and dedicated tasks | Complete billing records, feedback, guideline versions, drug labels, research cohorts/variables, deidentification candidates, incident RCA, finite-case statistics, operational materials and synthetic teaching |
| Document and teaching review | Document body is separate from summary, warnings and missing data; users select sections and review them before copying. Exercises and AI explanations are submitted separately; fixed scores and model feedback remain separate |

Management retains 41 entries with a search across four groups:

| Group | Main Controls |
| --- | --- |
| Features and models | Feature switches, allowed roles, providers, limits, validation status and task-prompt versions |
| Knowledge and data | Knowledge review, source registration, professional review and independent publication |
| Tasks and usage | Global technical tasks, task results and feedback, known usage and unknown values |
| Permissions and audit | Patient-access grants, configuration audits and management history |

AI configuration management requires `super_admin`; ordinary administrators do not inherit that permission. Private source content also requires the relevant purpose authorization. Task prompts are versioned for 79 capabilities; capability 78 uses a reviewed fixed local statistical recipe. Catalog `2026.10.26.1` improves writing instructions for all 63 LLM tasks without replacing stored custom prompts, active versions or configuration states.

For features using default v0, new tasks read the updated default text; older tasks retain their frozen versions.

New feature configurations start disabled. Providers, credentials, sources, knowledge and validation records are required as appropriate. Treatment candidates, documents and analyses require human review; they do not automatically prescribe, sign or change business records. Actual model quality and clinical effects need separate evaluation.

The 2026-10-26 experience update passed 576 backend cases, 232 Node checks and 90 final production-page cases using synthetic engineering boundaries, without real model calls. See the [experience verification record](doc/ai-experience-verification.json) for exact scope and reruns, and the [final integration record](doc/ai-final-integration-verification.json) for the earlier all80 engineering acceptance.

---

## 🏗 Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                  Frontend (Browser)                          │
│        Vue 3 · Element Plus · Vuex · Vue Router · Rspack    │
├─────────────────────────────────────────────────────────────┤
│                  Application (FastAPI)                       │
│       FastAPI · AI Worker · JWT/RBAC · Metrics/Audit          │
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

Prepare database settings and `SECRET_KEY` using `fastapi_be/.env.example` as a template. The API and AI worker must use the same configuration.

```bash
cd fastapi_be

# Create virtualenv
python -m venv venv
source venv/bin/activate    # Linux/Mac
# venv\Scripts\activate     # Windows

# Install dependencies
pip install -r requirements.txt

# Initialize an empty database or upgrade an Alembic-managed database
python -m app.db_migrate

# Start the API
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Visit http://localhost:8000/docs for the auto-generated Swagger UI.

To process queued AI tasks, open another terminal with the same virtual environment and database configuration:

```bash
cd fastapi_be
source venv/bin/activate
python -m app.ai.worker
```

An existing database without Alembic tracking requires backup and schema review before controlled adoption under the [migration entry's requirements](fastapi_be/app/db_migrate.py). That check is not bypassed automatically. See the [deployment manual](doc/installation-guide.md) for environment preparation and the [AI usage guide](doc/ai-guide.md) for provider and feature configuration.


### 3. Start Frontend

```bash
cd vue3-new-ui

# Install dependencies
npm install --legacy-peer-deps

# Dev mode (port 8091)
npm run serve:rspack

# Production build
npm run build

# Dependency audit, production build and asset-budget checks
npm run verify
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
| Admin | `admin` | `admin123` | General administration; no AI configuration permission |
| Super Admin | `super01` | `123456` | AI platform management; source purpose authorization checked separately |
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
| **Admin** | General system administration; excludes AI configuration |
| **Super Admin** | AI configuration, prompts, knowledge, source governance, grants and audit; private source access still requires purpose authorization |
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
| [API Doc](doc/apiDoc.md) | Core definitions; [access matrix](doc/api-rbac-matrix.md) covers 1,087 RBAC route methods |
| [Database Doc](doc/databaseDoc.md) | Core definitions; 266 ORM table definitions are maintained in model source |
| [AI Usage Guide](doc/ai-guide.md) | Workbench, super-admin configuration, sources and activation |
| [AI Capability Catalog](doc/ai-capabilities.md) | All 80 capabilities, inputs, outputs and default roles |
| [Default Prompts](doc/ai-prompts.json) | Task instructions, catalog version and fixed system contracts |
| [AI Experience Verification](doc/ai-experience-verification.json) | Scope and reruns for prompt and interface improvements |
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
- **Engineering checks**: Static RBAC drift detection, lint, tests, dependency audits and bundle budgets, with verification records limited to their actual execution scope
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
