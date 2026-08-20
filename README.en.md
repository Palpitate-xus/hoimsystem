# Hospital Outpatient Information Management System (HIS-OP)

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
| Business Modules | **75** backend routers |
| API Endpoints | **540** RESTful APIs |
| Database Tables | **139** business tables |
| Frontend Pages | **143** Vue pages |
| User Roles | **8** (admin/director/doctor/nurse/cashier/pharmacist/guide/patient) |
| Peak Throughput | **~67 req/s** (SQLite single-worker) / **500-2 000 req/s** (PostgreSQL est.) |
| Recommended Concurrency | **≤ 50 users** (SQLite) / **200-500 users** (PostgreSQL) |

---

## 🌟 Features

### Implemented Core Business (9 Domains / 40+ Modules)

- **Outpatient Management** — Smart Triage, Appointment, Walk-in Registration, Check-in, Queue Management, Triage Desk, Patrol Records, Breach Records, Billing, Invoice, Daily Settlement
- **Doctor Workstation** — Scheduling, EMR, Prescription, Lab Orders, Attendance, MDT Consultation, Clinical Pathway
- **Pharmacy** — Drug Management, Consumables, Audit & Dispense, Stock Alert, Stock Check, Purchase, Prescription Review, ADR Monitoring
- **Inpatient Management** — Ward & Bed, Admission, Inpatient Orders, Nursing Station, Inpatient Charges, Discharge Settlement
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

### Planned Modules

| Module | Description |
|:------:|:------------|
| Medical Insurance Gateway | Real-time settlement uplink, e-credentials (catalog mapping already delivered) |
| PACS/RIS | Medical imaging storage, viewing, reports |
| Closed-loop Orders | Order → Dispense → Execute → Bill loop |
| CDSS Deep Integration | Rule engine delivered; plan expert knowledge base + renal dose adjustment |
| DRG/DIP Auto-grouper | Manual grouping & profit analysis delivered; plan CHS-DRG grouper |
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
│   34 routers · 247 APIs · JWT Auth · Operation Log MW        │
├─────────────────────────────────────────────────────────────┤
│                  Data Layer                                  │
│             SQLite (dev) / PostgreSQL (prod)                 │
│                   SQLAlchemy ORM · Alembic                   │
└─────────────────────────────────────────────────────────────┘
```

### Tech Stack

| Layer | Technologies |
|:-----:|:-------------|
| Frontend | Vue 3.4+ / Element Plus 2.x / Vuex 4 / Vue Router 4 / Axios / Rspack |
| Backend | FastAPI 0.111+ / SQLAlchemy 2.x / Pydantic 2.x / Alembic |
| Database | SQLite (dev) / PostgreSQL (prod recommended) |
| Containerization | Docker / Docker Compose |
| Code Quality | ruff (Python) / Prettier (JavaScript) |
| Testing | pytest (backend API testing) |
| Security | bcrypt password hashing, JWT sessions, operation log auditing |

---

## 🚀 Quick Start

### Requirements

| Component | Version |
|:---------:|:-------:|
| Node.js | ≥ 16 |
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
docker-compose up -d
```

See [doc/deployDoc.md](doc/deployDoc.md) for detailed deployment instructions (Nginx, HTTPS, Systemd).

---

## 🔑 Default Accounts

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

> ⚠️ **Production deployment**: change default passwords and set a strong random `SECRET_KEY` in `.env` (use `openssl rand -base64 32`).

---

## 👥 Roles

| Role | Permissions |
|:----:|:------------|
| **Admin** | Full system management |
| **Director** | Department management, scheduling, prescription review |
| **Doctor** | EMR writing, prescription, lab orders |
| **Nurse** | Triage, vital signs, nursing, follow-up |
| **Cashier** | Walk-in registration, billing, daily settlement |
| **Pharmacist** | Prescription audit, dispense, inventory |
| **Guide** | Triage desk, smart triage, queue |
| **Patient** | Self-service: appointments, billing, records |

---

## 📚 Documentation

| Document | Description |
|:--------:|:------------|
| [Doc Index](doc/README.md) | Navigation for all docs |
| [Architecture](doc/architecture.md) | System architecture & design decisions |
| [Requirements](doc/demandDoc.md) | Functional & non-functional requirements |
| [API Doc](doc/apiDoc.md) | core API definitions (540 total in RBAC matrix) |
| [Database Doc](doc/databaseDoc.md) | 61 tables and ER relationships |
| [Deployment](doc/deployDoc.md) | Dev/prod/Docker deployment guide |
| [User Manual](doc/user-manual.md) | Role-based operation guide |
| [Roadmap](doc/todos.md) | Completed & planned modules |
| [Security](SECURITY.md) | Security policy |
| [Contributing](CONTRIBUTING.md) | Code style & PR workflow |
| [Changelog](CHANGELOG.md) | Version history |

---

## ⚡ Performance Benchmark

### Test Environment

| Item | Configuration |
|:----:|:-------------|
| Server | FastAPI + Uvicorn (1 worker) |
| Database | SQLite (StaticPool single-connection mode) |
| Tool | Locust 2.44.4 (headless) |
| Target | Localhost (loopback) |
| Duration | 30 seconds per run |

> ⚠️ Current tests use SQLite. Production deployment with PostgreSQL will achieve orders-of-magnitude higher concurrency (see theoretical analysis below).

---

### Measured Results (Mixed Read/Write)

Simulates real hospital traffic, ~80% reads / 20% writes across all core APIs:

| Users | Requests | Throughput (req/s) | Avg Latency | P50 | P95 | Failure |
|:-----:|:--------:|:------------------:|:-----------:|:---:|:---:|:-------:|
| 10 | 573 | **19.2** | 23 ms | 19 ms | 53 ms | 1.6% |
| 20 | 1 102 | **37.0** | 30 ms | 24 ms | 82 ms | 2.6% |
| 50 | 2 002 | **67.1** | 238 ms | 220 ms | 470 ms | 6.2% |
| 100 | 1 967 | **65.9** | 975 ms | 970 ms | 1 300 ms | 5.8% |

**Key Findings**:
- 📈 **Peak throughput**: ~67 req/s at 50 concurrent users
- 📉 **Inflection point**: Beyond 50 users, SQLite write-lock contention dominates — throughput plateaus, latency spikes
- 🔒 **Bottleneck**: SQLite global write lock serializes all writes and blocks reads
- ❌ **Failures**: SQLite lock timeouts (500) and connection exhaustion (401) under high concurrency

---

### Measured Results (Read-Only)

All GET queries, no write operations:

| Users | Requests | Throughput (req/s) | Avg Latency | P50 | P95 | Failure |
|:-----:|:--------:|:------------------:|:-----------:|:---:|:---:|:-------:|
| 20 | 1 881 | **63.0** | 113 ms | 100 ms | 250 ms | 6.9% |
| 50 | 1 886 | **63.2** | 574 ms | 560 ms | 840 ms | 6.7% |
| 100 | 1 765 | **59.3** | 1 423 ms | 1 400 ms | 1 900 ms | 6.2% |
| 200 | 1 823 | **61.0** | 2 848 ms | 2 900 ms | 4 300 ms | 7.1% |

**Key Findings**:
- 📊 **Throughput ceiling**: Even read-only workloads cap at ~63 req/s with StaticPool
- ⏱️ **Latency growth**: P95 reaches 1.9s at 100 users, 4.3s at 200 users
- 🔑 **Root cause**: StaticPool forces all requests through a single database connection

---

### Theoretical Analysis

#### Current Architecture Bottleneck

```
Request → Uvicorn (async) → FastAPI → SQLAlchemy → SQLite (StaticPool)
                                                    ↑
                                            Global write lock + single connection
                                            Max throughput ≈ 60-70 req/s
```

| Layer | Current Limit | Production (PostgreSQL) |
|:-----:|:-------------|:------------------------|
| **Web Server** | Uvicorn 1 worker (single process) | Multi-worker (CPU cores × 2) + Gunicorn |
| **Framework** | FastAPI async (no bottleneck) | Same (non-blocking I/O) |
| **ORM** | SQLAlchemy + StaticPool (1 connection) | QueuePool (10-20 connections) |
| **Database** | SQLite (file-level lock, write-serial) | PostgreSQL (MVCC, row-level lock) |

#### Production Estimate

After switching to PostgreSQL:

| Metric | SQLite (Current) | PostgreSQL (Estimated) |
|:------:|:-----------------|:-----------------------|
| **Max throughput** | ~67 req/s | **500-2 000 req/s** |
| **Recommended concurrency** | ≤ 50 users | **200-500 users** |
| **P95 latency (50 users)** | 470 ms | **< 50 ms** |
| **P95 latency (200 users)** | 4 300 ms | **< 200 ms** |

**Rationale**:
1. **PostgreSQL MVCC**: Readers never block writers, writers only lock modified rows
2. **Connection pooling**: QueuePool default 5 + 10 overflow, configurable to 20+
3. **Multi-worker Uvicorn**: 4 workers ≈ 4× throughput (~280 req/s)
4. **FastAPI async**: Single worker handles hundreds of concurrent I/O-bound connections
5. **Reference**: Similar FastAPI + PostgreSQL systems on 4-core/8GB typically achieve 1 000-3 000 req/s

#### Optimization Recommendations

| Priority | Item | Expected Gain |
|:--------:|:-----|:--------------|
| 🔴 High | Switch to PostgreSQL | 5-10× throughput |
| 🔴 High | Multi-worker Uvicorn (`--workers 4`) | 3-4× throughput |
| 🟡 Medium | Connection pool tuning (`pool_size=20`) | 3× concurrency |
| 🟡 Medium | Redis cache for hot queries | 5-10× read throughput |
| 🟢 Low | Database index optimization | 50% lower per-query latency |
| 🟢 Low | Pagination max page_size limit | Prevent large result sets |

---

### Reproducing the Tests

```bash
# 1. Start benchmark server
cd fastapi_benchmark
python init_benchmark_data.py          # seed test data
SECRET_KEY="your-secret" uvicorn run_benchmark:app --host 0.0.0.0 --port 8000

# 2. Run mixed read/write benchmark
locust -f locust_final.py --headless -u 50 -r 25 -t 30s \
    --host http://localhost:8000 --csv=results/50u

# 3. Run read-only benchmark
locust -f locust_readonly_pool.py --headless -u 50 -r 25 -t 30s \
    --host http://localhost:8000 --csv=results/readonly_50u
```

Test scripts are in the [fastapi_benchmark/](fastapi_benchmark/) directory.

---

## ✨ Highlights

- **Broad coverage**: Outpatient + Inpatient + Pharmacy + Lab + Exam + Surgery, 9 domains 40+ modules
- **Clean code**: 247 APIs organized by module, frontend/backend separation, component reuse
- **Great DX**: FastAPI auto docs, hot reload, zero-config SQLite startup
- **Observable**: Operation log middleware auto-records, datetime precision to seconds
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
