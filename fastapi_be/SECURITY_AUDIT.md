# HOIM System FastAPI Backend — Security Audit (PHI / Data Exposure / Business Logic)

**Scope:** `/home/xusheng/workspace/hoimsystem/fastapi_be/app/` (81 router files, 481 endpoints enumerated programmatically; core modules `dependencies.py`, `security.py`, `config.py`, `main.py`, `privacy.py`, `scheduler.py`).
**Context:** Healthcare information system — HIPAA / 个人信息保护法 (PIPL) threat model. PHI = 身份证号 (national ID), name, phone, address, diagnoses, lab/exam/surgery data.
**Method:** Static AST/grep enumeration of every `@router.*` decorator (481 total) checking for `Depends(get_current_user)` / `Depends(require_roles(...))` in decorator or signature (no router-level `dependencies=[...]` exists anywhere — all `APIRouter()` are bare). Then manual review of every hit and of the focus files.

---

## 1. Unauthenticated Endpoint Enumeration (Focus Area 1)

**481 endpoints total; 18 have NO authentication dependency.** Complete list:

| # | file:line | Method & Path | Auth | Verdict |
|---|-----------|---------------|------|---------|
| 1 | `user.py:78` | POST `/api/test` | none | Echo endpoint — **Low** (see F-09) |
| 2 | `user.py:85` | GET `/api/publicKey` | none | By design (RSA public key) — OK |
| 3 | `user.py:97` | POST `/api/login` | none | By design — OK (rate-limited) |
| 4 | `user.py:126` | POST `/api/register` | none | By design (see F-07 enumeration) |
| 5 | `user.py:156` | POST `/api/userInfo` | body token | OK (validates token) |
| 6 | `user.py:182` | POST `/api/logout` | none | No-op — see F-11 |
| 7 | `checkin.py:46` | GET `/api/checkIn/getAppointments` | none | **HIGH — F-02** (PHI lookup by 身份证号) |
| 8 | `checkin.py:78` | POST `/api/checkIn/checkIn` | none | **HIGH — F-02** (unauth state change) |
| 9 | `consumable.py:14` | GET `/api/consumable/getList` | none | **Low/Medium — F-10** (inventory disclosure) |
| 10 | `insurance.py:79` | POST `/api/integration/insurance/settlement` | X-Integration-Key | OK — `secrets.compare_digest`, 503 if key unset (`insurance.py:17-21` via `integration.py:_check_key`) |
| 11 | `integration.py:33` | POST `/api/integration/lis/result` | X-Integration-Key | OK — key-checked, idempotent |
| 12 | `integration.py:70` | POST `/api/integration/pacs/report` | X-Integration-Key | OK — key-checked, idempotent |
| 13 | `integration.py:108` | POST `/api/integration/payment/notify` | X-Integration-Key | OK — key + amount + status re-validated |
| 14 | `surgery.py:101` | GET `/api/surgeryApplication/getList` | none | **CRITICAL — F-01** (身份证号 + diagnoses) |
| 15 | `surgery.py:204` | GET `/api/surgerySchedule/getList` | none | **CRITICAL — F-01** (patient names + surgery data) |
| 16 | `triage.py:319` | POST `/api/triage/suggest` | none | By design (kiosk rule-based triage) — OK |
| 17 | `triage.py:371` | GET `/api/triage/keywords` | none | Static keyword list — OK |
| 18 | `upload.py:54` | GET `/api/uploads/avatars/{filename}` | none | Low — UUID filenames, avatars only (reports route at `upload.py:62` **is** auth-checked; `main.py:485` static mount is shadowed for both subpaths by the earlier-registered router routes) |

Focus files specifically asked about: `patient.py` (all endpoints authed ✓), `queue.py` (✓), `navigation.py` (✓ — public routes use `get_current_user`, admin CRUD gated), `monitor.py` (✓ admin-only), `scheduler.py` (✓ admin-only), `research.py` (✓ role-gated but role set too broad — F-03), `integration.py` (✓ key-based), `report.py` (✓ clinical/cashier roles), `system.py` (✓ admin-only). The unauthenticated exposure is concentrated in `surgery.py`, `checkin.py`, `consumable.py`, plus the by-design auth endpoints in `user.py`.

---

## Findings

### F-01 — CRITICAL: Unauthenticated surgery lists leak full PHI including 身份证号
**Location:** `app/routers/surgery.py:101` (`/surgeryApplication/getList`) and `surgery.py:204` (`/surgerySchedule/getList`)

```python
@router.get("/surgeryApplication/getList")
def get_surgery_application_list(
    status: int | None = None,
    keyword: str | None = None,
    db: Session = Depends(get_db),          # <-- no current_user dependency at all
):
    ...
    "patient_id": item.patient_id,
    "patient_name": item.patient.name if item.patient else "",
    "patient_identity": item.patient.identity if item.patient else "",   # line 122: raw 身份证号
    ...
    "preop_diagnosis": item.preop_diagnosis or "",
```

**Exploit:** `curl http://host/api/surgeryApplication/getList` — no token → full table: every surgical patient's name, **national ID number**, attending doctor, surgery name/level, anesthesia type, pre-op diagnosis, scheduled date, approver. `/surgerySchedule/getList` adds OR, surgeon names, surgery date/times for every patient. Under PIPL/HIPAA this is a reportable breach class; diagnosis + identity is high-sensitivity PHI.

**Fix:** Add `current_user: User = Depends(require_roles(*CLINICAL_ROLES))` (or NURSING ∪ CLINICAL) to both endpoints; mask `patient_identity` with `mask_identity()` unless the caller is in `FULL_PATIENT_IDENTITY_ROLES` (pattern already implemented in `triage_desk.py:57-61` — reuse it).

---

### F-02 — HIGH: Unauthenticated check-in kiosk — PHI lookup by 身份证号 + unauthenticated state change
**Location:** `app/routers/checkin.py:46` and `checkin.py:78`

```python
@router.get("/checkIn/getAppointments")
def get_appointments_for_checkin(identity: str, db: Session = Depends(get_db)):
    """根据身份证号查询可报到的预约列表(患者自助 kiosk 模式,凭身份证查询)"""
    patient = db.query(Patient).filter(Patient.identity == identity).first()
```
```python
@router.post("/checkIn/checkIn")
def check_in(req: CheckInRequest, db: Session = Depends(get_db)):
    """患者自助报到(凭身份证+预约UUID,无需登录)"""
```

**Exploit:** The GET endpoint is an unauthenticated **oracle**: it confirms whether any given 18-digit ID belongs to a registered patient with a same-day appointment (`500 病人信息不存在` vs `200` + doctor name, department, appointment time). CN identity numbers are sequential/derivable (region+birthdate+sequence), so this is scriptable mass enumeration. Worse, the response returns the `registration_uuid` which is the only other credential `checkIn` requires — so an attacker who knows a victim's ID can **check the victim in and consume their queue slot** (state change without authentication), and can spam queue entries for arbitrary patients.

**Fix:** Require at least a second factor for kiosk flows (就诊卡号 + ID, or SMS OTP to the phone on file), rate-limit per source IP, never return the appointment `uuid` to unauthenticated callers (return only a masked count), and make `check_in` conditional-update guarded (it also has a queue-number race — see F-12).

---

### F-03 — HIGH: Research export — `doctor` role can bulk-export EVERY patient's cleartext identity/phone and ALL medical records
**Location:** `app/routers/research.py:69` (role set), `research.py:82-95` (`_export_patients`), `research.py:98-114` (`_export_medical_records`), `research.py:291` (export), `research.py:326` (package)

```python
_RESEARCH_ROLES = {*ADMIN_ROLES, *CLINICAL_ROLES}   # CLINICAL_ROLES includes ROLE_DOCTOR
...
def _export_patients(db, from_date, to_date, anonymize):
    q = db.query(Patient)                            # ALL patients, unscoped
    rows.append({
        "name": _hash_pii(p.name) if anonymize else p.name,
        "identity": _hash_pii(p.identity) if anonymize else p.identity,   # anonymize defaults True...
        "phone": _hash_pii(p.phone) if anonymize else p.phone,
```
```python
anonymize = bool(req.get("anonymize", True))   # ...but caller passes {"anonymize": false}
```

**Exploit:** Any `doctor` account (also the weakest-privileged clinical role, and default seeded `doctor1/doctor123` exists in `seed_default_accounts.py`) can POST `{"table":"patients","anonymize":false}` and receive a CSV of **every patient's name + 身份证号 + phone + birthday + allergy history**, then `{"table":"medical_records","anonymize":false}` for **all patients'** symptoms/diagnoses (the query is unscoped — not limited to the doctor's own patients). `/research/export/package` does the whole database in one ZIP. This defeats the entire masking architecture in `privacy.py` and is a textbook PIPL Article 51/ HIPAA minimum-necessary violation. Note also the in-memory `_audit_log` (research.py:259) resets on restart — the documented "100 exports / 30 days" limit stated in the module docstring is **not implemented anywhere**.

**Fix:** Restrict non-anonymized export to `ADMIN_ROLES` only; force `anonymize=True` for `doctor`; scope medical-record export to `doctor_id IN (requester's doctor ids)`; persist export audit records in the DB (`OperationLog`) instead of a module-level list; implement the rate limit.

---

### F-04 — HIGH: Exam module — any authenticated user (incl. `patient` role) reads every patient's exam records and reports
**Location:** `app/routers/exam.py:347` (`/examRecord/getList`), `exam.py:461` (`/examResult/getList`), `exam.py:541` (`/examReport/getDetail`)

```python
@router.get("/examRecord/getList")
def get_exam_record_list(keyword=None, current_user: User = Depends(get_current_user), db=...):
    records = db.query(ExamRecord).order_by(ExamRecord.create_time.desc()).all()  # no role/patient scoping
    ...
    "patient_name": item.patient.name if item.patient else "",
    "overall_result": item.overall_result,   # 总检结论 (diagnosis-level PHI)
```
```python
@router.get("/examReport/getDetail")
def get_exam_report_detail(record_id: str, current_user: User = Depends(get_current_user), db=...):
    record = db.query(ExamRecord).filter(ExamRecord.record_id == record_id).first()
    # no ownership check — returns patient_name, overall_result/advice, all item results
```

**Exploit:** Patient-role token → `GET /api/examRecord/getList` harvests `record_id` + patient name + overall result for **all** examinees; then `GET /api/examReport/getDetail?record_id=<each>` returns the full report (every item value, abnormal flags, advice). UUID record ids are not secret — they are handed out by the first endpoint. Same pattern for `/examResult/getList`. (Contrast: `examAppointment/getList` at `exam.py:242` *does* scope patients correctly — the scoping was simply never applied to records/results.)

**Fix:** Replicate the `examAppointment` scoping: if `current_user.user_role == ROLE_PATIENT`, filter `ExamRecord.patient_id` to the caller's patient id; require clinical roles for staff access.

---

### F-05 — HIGH: Cross-patient PHI via "any authenticated user" list endpoints (triage desk, patrol, vitals, MDT, referral, chronic disease, exam appointments)
**Locations (all `Depends(get_current_user)` with **no** role restriction or patient scoping):**

| file:line | Endpoint | Leaked PHI |
|---|---|---|
| `triage_desk.py:41` | GET `/triageDesk/getList` | all patients' names, symptoms, temperature/BP/pulse, level, notes (identity *is* masked here) |
| `queue.py:157` | GET `/patrol/getList` | all patients' names + free-text nursing patrol content (`item.content`) |
| `vitalsign.py:61` | GET `/vitalSign/getList` | all patients' names + vital signs |
| `mdt.py:43` | GET `/mdt/getList` | all patients' names + diagnosis + MDT results/review notes |
| `referral.py:31` | GET `/referral/getList` | all patients' names + referral reason (clinical) |
| `insurance.py:112` | GET `/insurance/chronic/list` | **non-patient roles unscoped**: all patients' names + chronic disease name + 医保卡号 `card_no` (only `ROLE_PATIENT` is filtered) |
| `exam.py:242` | GET `/examAppointment/getList` | non-patient roles see all appointments incl. free-text `note` |

**Exploit:** A single low-privilege account (e.g. `patient1` or `guide01`) dumps ward-level clinical data for the entire hospital in one request each. `insurance/chronic/list` leaks chronic-disease registrations (sensitive-category health data under PIPL Art. 28) for every patient to e.g. a `pharmacist` token.

**Fix:** Gate these list endpoints to appropriate staff role sets (`NURSING_ROLES | CLINICAL_ROLES` etc. — the codebase already has these constants) and scope to the caller's patients where applicable.

---

### F-06 — HIGH: Family-member binding lets any patient link an arbitrary victim record and read their data
**Location:** `app/routers/family_member.py:59-92` (`create`), `_serialize` at `family_member.py:30-46`; consumed by `patient.py:55-71` (`_patient_scope`)

```python
existing_patient = db.query(Patient).filter(Patient.identity == req.identity).first()
...
if existing_patient:
    if existing_patient.name != req.name or existing_patient.sex != req.sex:
        return {"code": 500, "msg": "身份证号与已有患者资料不一致"}
# binds existing victim record to attacker's family list
```

**Exploit:** An attacker with a normal patient account who knows a victim's 身份证号 + name + sex (all obtainable from F-01/F-02 leaks, or public data) calls `POST /api/familyMember/create` — the existing patient record gets bound to the attacker's account (the "already bound" check at line 71 only fires if *another family already linked them*; a registered-but-unlinked victim passes). `_patient_scope` (`patient.py:60`) then grants the attacker the victim's `patient_id`, exposing the victim's appointments/registrations lists (`patient.py:74-100, 239-264`), and `_serialize` returns the victim's **phone, address, allergy_history, birthday** in cleartext to the attacker.

**Fix:** Require verification of the victim (SMS OTP to phone on file, or in-person registrar binding); never return member phone/address/allergy via `_serialize` to the owner; allow binding only to records with `permission == "family"` created by the owner, not pre-existing independent patients.

---

### F-07 — MEDIUM: Account/PHI enumeration via registration messages + login timing side channel
**Location:** `app/routers/user.py:132-135` (register), `user.py:103-106` (login), `app/security.py:21-30`

```python
if db.query(Patient).filter(Patient.identity == req.identity).first():
    return {"code": 500, "msg": "身份证号已注册"}      # confirms ID is registered
if db.query(User).filter(User.username == req.identity).first():
    return {"code": 500, "msg": "用户已注册"}
```
Login itself is uniform (`账户或密码不正确` for both unknown-user and wrong-password, and rate-limited 5/5min per IP+username at `user.py:41-59` — good), **but** `verify_password` (bcrypt) is only executed when the user exists, so unknown-username requests return measurably faster (~0ms vs ~100-300ms) — a timing oracle that distinguishes "registered ID" from "not registered". Combined with register's explicit messages, an attacker can enumerate which 身份证号 the hospital has on file.

**Fix:** Return one generic message from register (`注册信息无效或已存在`); equalize login timing by running `bcrypt.checkpw` against a dummy hash when the user is absent.

---

### F-08 — MEDIUM: Weak password policy
**Location:** `app/routers/user.py:130` (register 6-20), `user.py:242` (admin reset 6-128), `doctor.py:50` (doctor create 6-128), `app/security.py:30` (legacy plaintext fallback)

```python
if not password or not 6 <= len(password) <= 20:
    return {"code": 500, "msg": "密码长度必须为6至20位"}     # no complexity, no blocklist
```
```python
    # legacy plaintext fallback — caller is expected to upgrade on success
    return plain == stored          # security.py:30 — plaintext comparison still honored
```
6-char minimum with no complexity/blocklist, no forced rotation, and JWTs live **24h** (`user.py:63`). `verify_password` still accepts legacy plaintext hashes (auto-upgraded only on successful login — dormant accounts with plaintext hashes remain). Out-of-scope-but-critical: `seed_default_accounts.py:20-31` ships `admin/admin123`, `super01/123456`, `nurse01/123456` … — if run against a production DB every finding above becomes one-factor trivial.

**Fix:** Minimum 8-10 chars with complexity + breached-password blocklist; migrate/expire remaining plaintext hashes (a migration script exists — enforce it as a hard fail instead of fallback); force password change on seeded accounts; shorten token TTL (≤2h) with refresh.

---

### F-09 — LOW: `/api/test` unauthenticated echo endpoint
**Location:** `app/routers/user.py:78-82`

```python
@router.post("/test")
async def test(request: Request, db: Session = Depends(get_db)):
    body = json.loads(await request.body())
    temp = body.get("data")
    return {"code": 200, "msg": "success", "data": temp}
```
Reflects arbitrary `data` back (JSON-encoded, so no direct XSS; no DB write). Main risks: unauthenticated `json.loads` on raw body returns 500 traces to unauth users, and the endpoint is pure attack surface. It is in the audit-skip list (`main.py:174`) so it is also never logged.

**Fix:** Remove the endpoint (or gate behind admin + non-production).

---

### F-10 — LOW: Unauthenticated consumable inventory disclosure
**Location:** `app/routers/consumable.py:14-40`

`GET /api/consumable/getList` without auth returns name/category/**stock/unit-price/supplier/remark** for every consumable. All sibling endpoints (`create/update/delete`) correctly require `PHARMACY_ROLES` — only the list was left open. Supplier names + stock levels are business-sensitive (procurement intelligence), not PHI.

**Fix:** Add `Depends(require_roles(*PHARMACY_ROLES))` (or at minimum `get_current_user`).

---

### F-11 — MEDIUM: Token lifecycle — 24h JWT, logout is a no-op, no revocation
**Location:** `app/routers/user.py:62-65` (token), `user.py:182-184` (logout), `app/dependencies.py:46-53`

```python
def create_access_token(username: str) -> str:
    expire = datetime.datetime.utcnow() + datetime.timedelta(hours=24)
    payload = {"sub": username, "exp": expire, ...}

@router.post("/logout")
def logout():
    return {"code": 200, "msg": "success"}       # nothing is invalidated
```
No `jti`, no server-side session state, no blacklist. A stolen/kiosk-left token (and note the kiosk flows in F-02 share this backend) is valid for 24h regardless of logout/password change (password change does not rotate `SECRET_KEY`). Role changes via `/user/updateRole` also do not invalidate old tokens — a demoted admin keeps admin rights until expiry.

**Fix:** Short-lived access token (15-30 min) + refresh token with server-side revocation table keyed by `jti`; on password change / role change / logout, revoke outstanding tokens.

---

### F-12 — MEDIUM: Business-logic races (discharge, queue numbering, schedule stock restore)
**Location:** `app/routers/discharge.py:23-95` (`doDischarge`), `checkin.py:98-99`, `patient.py:234`, `charge.py:279`

```python
# discharge.py — status read, then written later without a conditional UPDATE
if admission.status != 1:
    return {"code": 500, ...}
...  # long non-atomic section: settles charges, stops orders, frees bed, creates summary
admission.status = 2
```
```python
# checkin.py — classic read-then-increment race
max_queue = db.query(Queue).order_by(Queue.queue_number.desc()).first()
queue_number = (max_queue.queue_number + 1) if max_queue else 1
```
```python
# patient.py:234 / charge.py:279 — non-atomic stock restore
schedule.number += 1        # ORM read-modify-write; lost updates under concurrency
```
Two concurrent `doDischarge` calls for the same admission both observe `status == 1` and both proceed → double auto-settlement pass, duplicate order-stop writes, and the **refund amount is computed and returned twice** (deposit − total), which a cashier could pay out twice. Concurrent self-service check-ins produce duplicate queue numbers (two patients called as #N). Schedule restores via `+= 1` can be lost, corrupting slot inventory.

The refund/settlement **money paths themselves are well defended** (see §4 below) — the residual races are the unguarded ones above.

**Fix:** Convert `doDischarge` to a guarded transition (`UPDATE admission SET status=2 WHERE admission_id=? AND status=1`, check `rowcount == 1`, else abort) exactly like `charge_refund` already does; allocate queue numbers via a `RegistrationCounter`-style row with `with_for_update()` (the pattern already exists in `app/registration.py`); replace `schedule.number += 1` with `UPDATE ... SET number = number + 1`.

---

### F-13 — MEDIUM: Internal error details returned to clients
**Location:** `app/routers/backup.py:60,82,112`, `app/routers/purchase.py:70`, `app/routers/research.py:312`

```python
except Exception as e:
    return {"code": 500, "msg": f"备份失败: {str(e)}"}          # backup.py:60 (also :82, :112)
```
```python
return {"code": 500, "msg": str(exc) or "采购明细格式错误"}      # purchase.py:70
```
```python
raise HTTPException(status_code=500, detail=f"查询失败: {type(e).__name__}: {e}")   # research.py:312
```
`str(e)` from filesystem/DB/decimal operations surfaces absolute paths (`/home/.../test.db`, backup dir), DB driver errors, and query fragments to clients. All are role-gated (admin / pharmacy / clinical), which caps severity, but backup paths + the SQLite file layout aid an insider aiming at F-14's download endpoint. Elsewhere the codebase consistently logs via `traceback.print_exc()` and returns generic messages — these five are the outliers.

**Fix:** Log the exception server-side, return a generic message + correlation id.

---

### F-14 — MEDIUM: Inconsistent 身份证号 masking — nursing endpoints return raw identity contrary to the system's own policy
**Location:** `app/privacy.py:5` defines `FULL_PATIENT_IDENTITY_ROLES = ADMIN ∪ CASHIER ∪ CLINICAL ∪ REGISTRAR` (nurse/pharmacist/guide/lab **excluded**), but:

| file:line | Endpoint (role gated to) | Leak |
|---|---|---|
| `admission.py:58, 167, 276` | admission list/detail/inpatient list (NURSING_ROLES) | `patient_identity` raw; detail (167) also raw phone + address |
| `discharge.py:121, 199` | discharge summary / discharged list (NURSING_ROLES) | `patient_identity` raw |
| `surgery.py:122` | surgery list (currently **no auth** — F-01) | `patient_identity` raw |
| `patient_card.py:25` | card list (REGISTRAR ∪ PATIENT) | raw identity — OK for registrar; patient branch is self-only ✓ |
| `admin.py:155-185` | `/patientManagement/getList` | identity/phone masked ✓ **but** `address` and `allergy_history` unmasked for roles as low as `guide`/`pharmacist`/`lab_technician`, who see the **full patient table** (only `patient` role is row-scoped, line 159-160) |

Contrast the correct pattern at `triage_desk.py:57-61` (mask unless `can_view_full_patient_identity`). The privacy policy exists but is applied in only 2 of ~10 identity-returning surfaces.

**Fix:** Route every `patient_identity`/`phone`/`address` serialization through `mask_identity`/`mask_phone` + `can_view_full_patient_identity`; decide explicitly whether nursing needs full identity (if yes, add NURSING to the policy once — not endpoint-by-endpoint); scope `/patientManagement/getList` rows to staff roles and drop `address`/`allergy_history` from non-clinical views.

---

## Verified-secure answers to the specific focus questions

**4. Refund / settlement business logic** (`charge.py`, `inpatient_charge.py`, `discharge.py`, `user.py` prepaid) — **largely sound; no negative-amount or double-refund path found:**
- `charge_refund` (`charge.py:114-146`): amount is taken from the charge record itself (client cannot supply one), `math.isfinite` + `> 0` guarded, and the state transition is a **conditional `UPDATE ... WHERE status=1` with `rowcount != 1` rollback** — concurrent double refund is correctly prevented.
- `prepaid_recharge/deduct/refund` (`user.py:283-369`): `_parse_prepaid_amount` rejects `<= 0`, NaN/Infinity (`amount.is_finite()`), and quantizes to 0.01; deduct/refund use guarded atomic SQL updates (`func.coalesce(balance) >= amount`) — **no negative-balance or race path**.
- `inpatient_charge.py:136` refund: reason required, guarded conditional UPDATE, `rowcount` checked — idempotent-safe.
- `integration.py:108` payment notify: key + amount equality (`Decimal` compare) + `status==0` precondition + `integration_status=="synced"` idempotency — well built.
- `charge.py:587` `payment/mockNotify` is cashier/admin **and hard-blocked in production** (`settings.is_production` check, line 590) — good.
- Residual races are F-12 (discharge TOCTOU, queue numbering, `schedule.number += 1` restores).

**3. Mass assignment** — **none found.** `register` (`user.py:147`) hardcodes `user_role="patient"`; `/user/updateRole` (`user.py:208-230`) validates `new_role in VALID_USER_ROLES` and has a super-admin escalation guard; doctor creation (`doctor.py:45-63`) derives role from `permission` field but is admin-only and only maps to `doctor`/`director`; `data_import_export.py` hardcodes roles. Pydantic schemas use explicit fields (no `**req.dict()` into models anywhere).

**6. `monitor.py` / `scheduler.py`** — `monitor.py:14-15` `/monitor/summary` requires `ADMIN_ROLES` ✓ (exposes only aggregated request stats + error paths + usernames of failing actors — admin-appropriate). `routers/scheduler.py:9,14` `/scheduler/status` and `/scheduler/run/{job}` require `ADMIN_ROLES` ✓; the scheduler itself (`app/scheduler.py`) only counts low-stock/breaches and delegates backup — no system metrics (CPU/memory/env) are exposed anywhere.

**7. `system.py`** — operation-log endpoints `/log/getList` (`system.py:21`) and `/log/stats` (`system.py:78`) require `ADMIN_ROLES` ✓ — non-admins **cannot** read audit logs. Dict CRUD and config get/update are all admin-only ✓. `/message/getList` correctly filters `recipient_id == current_user.user_id` ✓. Note: the audit middleware itself (`main.py:174-191`) skips logging `/api/login`, `/api/register`, `/api/test`, `/api/publicKey` and never logs failed-auth 401/403 attempts — brute-force and F-02/F-01 unauthenticated access leave **no audit trail**; consider logging auth failures with source IP.

**8. Password policy / login uniformity** — see F-07 (enumeration + timing) and F-08 (6-char policy, plaintext fallback, seeded defaults). Message uniformity on login is correct; rate limiting is correct; the residual issues are the register oracle and the timing side channel.

---

## Severity summary

| ID | Severity | One-line summary | Location |
|----|----------|------------------|----------|
| F-01 | **Critical** | Unauth surgery lists expose all patients' 身份证号 + diagnoses + schedules | `surgery.py:101,204` |
| F-02 | High | Unauth kiosk: ID-number patient oracle + unauth check-in state change | `checkin.py:46,78` |
| F-03 | High | `doctor` role bulk-exports full DB incl. cleartext identity/phone (`anonymize:false`) | `research.py:69,82,291` |
| F-04 | High | Any authenticated user (incl. patients) reads all exam records/reports | `exam.py:347,461,541` |
| F-05 | High | Cross-patient PHI on 7 "any-auth" list endpoints (triage/patrol/vitals/MDT/referral/chronic/exam-appt) | `triage_desk.py:41`, `queue.py:157`, `vitalsign.py:61`, `mdt.py:43`, `referral.py:31`, `insurance.py:112`, `exam.py:242` |
| F-06 | High | Patient can bind arbitrary victim record as "family member" and read phone/address/allergies | `family_member.py:59`, `patient.py:55` |
| F-07 | Medium | Identity-number enumeration via register messages + login timing oracle | `user.py:132`, `security.py:21` |
| F-08 | Medium | 6-char password policy, plaintext-hash fallback, 24h token, weak seeded accounts | `user.py:130,63`, `security.py:30` |
| F-09 | Low | Unauthenticated `/api/test` echo | `user.py:78` |
| F-10 | Low | Unauth consumable inventory (stock/price/supplier) | `consumable.py:14` |
| F-11 | Medium | No token revocation; logout no-op; role change doesn't invalidate tokens | `user.py:62,182` |
| F-12 | Medium | Discharge TOCTOU (double refund output), queue-number and stock-restore races | `discharge.py:23`, `checkin.py:98`, `patient.py:234` |
| F-13 | Medium | `str(e)` internals leaked in 5 handlers | `backup.py:60,82,112`, `purchase.py:70`, `research.py:312` |
| F-14 | Medium | Identity/phone/address masking policy applied inconsistently (nursing endpoints raw) | `admission.py:58,167,276`, `discharge.py:121,199`, `admin.py:155` |

**Remediation priority:** F-01 → F-02 (add auth, hours of work, removes unauthenticated PHI) → F-03/F-04/F-05/F-06 (scope by role/patient) → F-12 races → F-07/F-08/F-11 (auth hardening) → F-13/F-14/F-09/F-10.
