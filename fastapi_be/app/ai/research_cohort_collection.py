"""Whole bounded recorded families for a finite expressly authorized project.

No clinical body is read until every declared patient has current ACL plus
research permission, including for Super. This is an explicit field-family
snapshot, not a full hospital record, historical replay or automatic export.
"""

import datetime as dt
import decimal
import json

from fastapi import HTTPException
from pydantic import TypeAdapter
from sqlalchemy import or_

from app.ai.research_cohort_contract import ScopeReference, canonical_json
from app.ai.research_cohort_models import AIResearchPatientAuthorization, AIResearchProjectACL
from app.ai.research_cohort_registry import _row, authorize_patient_research, original_proof
from app.ai.research_cohort_sources import _typed, hash_content, scope_proof, scope_row, utc_text, utcnow
from app.ai.research_cohort_write_guard import current_research_rows, lock_research_write

MAX_ROOTS = 8192
MAX_BYTES = 8 * 1024 * 1024
BATCH_SIZE = 32
# These are exact supported recorded columns, deliberately not an assertion
# that all clinical families or every column of the hospital are captured.
FAMILY_COLUMNS = {
    "patient_demographics": ("patient_id", "sex", "birthday"),
    "registrations": ("registration_uuid", "patient_id", "doctor_id", "specialist", "department_id", "schedule_id", "time", "status"),
    "admissions": (
        "admission_id",
        "patient_id",
        "doctor_id",
        "department_id",
        "ward_id",
        "bed_id",
        "admission_type",
        "admission_time",
        "admission_diagnosis",
        "chief_complaint",
        "present_illness",
        "past_history",
        "discharge_time",
        "discharge_diagnosis",
        "status",
        "create_time",
    ),
    "medical_records": ("medical_record_id", "consultation_time", "doctor_id", "patient_id", "symptom", "result", "registration_uuid", "status", "sign_time"),
    "structured_medical_records": (
        "record_id",
        "admission_id",
        "patient_id",
        "doctor_id",
        "record_type",
        "chief_complaint",
        "present_illness",
        "past_history",
        "personal_history",
        "family_history",
        "physical_exam",
        "auxiliary_exam",
        "diagnosis",
        "treatment_plan",
        "status",
        "sign_time",
        "create_time",
        "update_time",
    ),
}
FAMILY_KEYS = {
    "patient_demographics": "patient_id",
    "registrations": "registration_uuid",
    "admissions": "admission_id",
    "medical_records": "medical_record_id",
    "structured_medical_records": "record_id",
}
FAMILY_CLOCKS = {"registrations": "time", "admissions": "admission_time", "medical_records": "consultation_time", "structured_medical_records": "create_time"}


def _models():
    from app.models import Admission, MedicalRecord, Patient, Registration, StructuredMedicalRecord

    return dict(patient_demographics=Patient, registrations=Registration, admissions=Admission, medical_records=MedicalRecord, structured_medical_records=StructuredMedicalRecord)


def _literal(value):
    if isinstance(value, dt.datetime):
        if value.tzinfo is not None:
            raise HTTPException(409, "旧临床时间带有未声明时区，未猜测转换")
        return value.isoformat(timespec="microseconds")
    if isinstance(value, dt.date):
        return value.isoformat()
    if isinstance(value, decimal.Decimal):
        return str(value)
    if value is None or type(value) in {str, int, bool}:
        if type(value) is str:
            value.encode("utf-8", errors="strict")
        return value
    raise HTTPException(409, "研究支持字段包含未声明的原始SQL类型")


class Budget:
    """Count each root and its UTF8 representation before retaining it."""

    def __init__(self):
        self.roots = 0
        self.bytes = 0

    def add(self, value, *, root=True):
        self.roots += int(root)
        self.bytes += len(canonical_json(value).encode("utf-8"))
        if self.roots > MAX_ROOTS or self.bytes > MAX_BYTES:
            raise HTTPException(413, "明确研究来源超过8192根或8MiB完整预算，未截断或选取部分")


def _keyset(db, model, key, where, *, columns, locking):
    """Scan technical IDs, then load one declared original at a time."""
    cursor = None
    while True:
        query = db.query(getattr(model, key)).filter(*where)
        if cursor is not None:
            query = query.filter(getattr(model, key) > cursor)
        ids = current_research_rows(query.order_by(getattr(model, key)), shared=not locking).limit(BATCH_SIZE).all()
        if not ids:
            return
        for item in ids:
            identifier = item[0]
            row = current_research_rows(db.query(*(getattr(model, name) for name in columns)).filter(getattr(model, key) == identifier), shared=not locking).one_or_none()
            if row is None:
                raise HTTPException(409, "研究原始成员在同一次完整捕获期间变化")
            yield dict(zip(columns, (_literal(value) for value in row), strict=True))
            cursor = identifier


def _parent_locator(db, family, record, patient_id, *, locking):
    if family not in {"medical_records", "structured_medical_records"}:
        return {"kind": "direct_patient_fk", "status": "patient_bound", "technical_hash": hash_content({"patient_id": record["patient_id"]})}
    from app.models import Admission, Registration

    model, key, field = (Registration, "registration_uuid", "registration_uuid") if family == "medical_records" else (Admission, "admission_id", "admission_id")
    identifier = record[field]
    if identifier is None:
        return {"kind": field, "status": "unknown_parent", "technical_hash": hash_content({field: None})}
    parent = current_research_rows(db.query(getattr(model, key), model.patient_id).filter(getattr(model, key) == identifier), shared=not locking).one_or_none()
    # Only identity columns: never read a foreign parent's clinical body.
    if parent is None:
        status = "missing_parent"
        technical = {field: identifier, "exists": False}
    else:
        status = "patient_bound" if parent.patient_id == patient_id else "patient_mismatch"
        technical = {field: identifier, "exists": True, "patient_id": parent.patient_id}
    return {"kind": field, "status": status, "technical_hash": hash_content(technical)}


def _authorization_manifest(db, scope_id, budget, *, locking):
    result = []
    for kind, model, pk in (("acl", AIResearchProjectACL, "acl_id"), ("authorization", AIResearchPatientAuthorization, "authorization_id")):
        columns = (pk, "content_hash", "status", "revision", "created_at", "reviewed_at", "revoked_at")
        if kind == "acl":
            columns += ("user_id", "permission", "valid_from", "valid_until")
        else:
            columns += ("patient_id", "authorization_kind", "access_basis", "valid_from", "valid_until", "authorization_review_status", "authorization_reviewed_by", "authorization_reviewed_at")
        for raw in _keyset(db, model, pk, [model.scope_id == scope_id], columns=columns, locking=locking):
            # Verify every immutable root, including a revoked/nonwinner. Its
            # free text never goes into the safe manifest/public projection.
            proof = original_proof(kind, _row(db, kind, raw[pk], locking=locking))
            for name in ("created_at", "reviewed_at", "revoked_at", "valid_from", "valid_until", "authorization_reviewed_at"):
                if name in raw and raw[name] is not None:
                    raw[name] = utc_text(dt.datetime.fromisoformat(raw[name]))
            item = {"kind": kind, "source_record_id": raw[pk], "content_hash": proof["content_hash"], "governance_hash": proof["governance_hash"], "metadata": raw}
            budget.add(item)
            result.append(item)
    return result


def capture_sources(db, user, values, *, locking=False):
    request = _typed(ScopeReference, values)
    # All captures use current locks. The flag requests exclusive original
    # member reads for a same-transaction Case write; it never permits old RR.
    actor = lock_research_write(db, user)
    scope = scope_proof(scope_row(db, request.scope_id))
    if (scope["content_hash"], scope["governance_hash"]) != (request.scope_content_hash, request.scope_governance_hash):
        raise HTTPException(409, "明确研究项目三锚已变化，请重新核对原件")
    patient_ids = scope["payload"]["patient_ids"]
    permissions = []
    acl = None
    # Authorize ALL patients before even the first patient clinical body read.
    for patient_id in patient_ids:
        actor, current_acl, permission = authorize_patient_research(db, actor, request.scope_id, patient_id, capture=True)
        if acl is not None and current_acl != acl:
            raise HTTPException(409, "项目ACL在完整患者逐项核验期间变化")
        acl = current_acl
        permissions.append(permission)
    lock_research_write(db, actor, scope_ids=(request.scope_id,), patient_ids=patient_ids)
    # Fresh own proofs after all canonical parent locks, not an earlier RR view.
    if scope_proof(scope_row(db, request.scope_id)) != scope:
        raise HTTPException(409, "研究项目在当前父锁后变化")
    for index, patient_id in enumerate(patient_ids):
        _, fresh_acl, fresh_permission = authorize_patient_research(db, actor, request.scope_id, patient_id, capture=True)
        if fresh_acl != acl or fresh_permission != permissions[index]:
            raise HTTPException(409, "逐患者研究授权在当前父锁后变化")
    budget = Budget()
    budget.add(scope)
    budget.add(acl, root=False)
    for permission in permissions:
        budget.add(permission, root=False)
    authorizations = _authorization_manifest(db, request.scope_id, budget, locking=locking)
    start = dt.datetime.fromisoformat(scope["payload"]["record_window"]["date_from"])
    end = dt.datetime.fromisoformat(scope["payload"]["record_window"]["date_to"]) + dt.timedelta(days=1)
    records, manifest = [], []
    models = _models()
    for patient_id in patient_ids:
        for family in scope["payload"]["data_families"]:
            model, key = models[family], FAMILY_KEYS[family]
            conditions = [model.patient_id == patient_id]
            if family in FAMILY_CLOCKS:
                clock = getattr(model, FAMILY_CLOCKS[family])
                conditions.append(or_(clock.is_(None), (clock >= start) & (clock < end)))
            for raw in _keyset(db, model, key, conditions, columns=FAMILY_COLUMNS[family], locking=locking):
                parent = _parent_locator(db, family, raw, patient_id, locking=locking)
                clock_unknown = family in FAMILY_CLOCKS and raw[FAMILY_CLOCKS[family]] is None
                entry = {
                    "family": family,
                    "patient_id": patient_id,
                    "record_id": raw[key],
                    "original": raw,
                    "parent_binding": parent,
                    "window_status": "unknown_clock" if clock_unknown else "recorded_calendar_in_scope",
                }
                budget.add(entry)
                records.append(entry)
                manifest.append(
                    {
                        "family": family,
                        "patient_id": patient_id,
                        "record_id": raw[key],
                        "content_hash": hash_content(raw),
                        "parent_binding_hash": hash_content(parent),
                        "window_status": entry["window_status"],
                    }
                )
    body = {
        "schema_version": "research_cohort_capture_v1",
        "request": request.model_dump(),
        "actor_id": actor.user_id,
        "scope_original": scope,
        "actor_acl": acl,
        "patient_authorizations": permissions,
        "authorization_manifest": authorizations,
        "supported_columns": {family: list(FAMILY_COLUMNS[family]) for family in scope["payload"]["data_families"]},
        "records": records,
        "member_manifest": manifest,
        "manifest_hash": hash_content(manifest),
    }
    # Single actual wire budget as well as cumulative construction budget.
    encoded = canonical_json(body).encode("utf-8")
    if len(encoded) > MAX_BYTES:
        raise HTTPException(413, "完整研究捕获原件超过8MiB，未截断")
    result = {**body, "captured_at": utc_text(utcnow()), "collection_digest": hash_content(body)}
    if len(canonical_json(result).encode("utf-8")) > MAX_BYTES:
        raise HTTPException(413, "完整研究捕获连同技术时钟超过8MiB，未截断")
    return result


def verify_capture(value):
    """Pure own integrity only, never an authorization/currentness assertion."""
    from app.ai.research_cohort_registry import verify_registry_proof
    from app.ai.research_cohort_sources import verify_scope_proof

    try:
        keys = {
            "schema_version",
            "request",
            "actor_id",
            "scope_original",
            "actor_acl",
            "patient_authorizations",
            "authorization_manifest",
            "supported_columns",
            "records",
            "member_manifest",
            "manifest_hash",
            "captured_at",
            "collection_digest",
        }
        if type(value) is not dict or set(value) != keys or value["schema_version"] != "research_cohort_capture_v1":
            raise ValueError("Closed capture required")
        if len(canonical_json(value).encode("utf-8")) > MAX_BYTES:
            raise ValueError("Whole wire budget")
        from app.ai.research_cohort_contract import UTC, Positive

        TypeAdapter(Positive).validate_python(value["actor_id"], strict=True)
        TypeAdapter(UTC).validate_python(value["captured_at"], strict=True)
        request = ScopeReference.model_validate(value["request"])
        scope = verify_scope_proof(value["scope_original"])
        if (request.scope_id, request.scope_content_hash, request.scope_governance_hash) != (scope["identity"]["scope_id"], scope["content_hash"], scope["governance_hash"]):
            raise ValueError("Whole project anchors differ")
        acl = verify_registry_proof("acl", value["actor_acl"])
        if acl["identity"]["user_id"] != value["actor_id"] or acl["identity"]["permission"] != "read_capture" or acl["parent_binding"]["scope"] != scope:
            raise ValueError("Exact actor ACL differs")
        permissions = value["patient_authorizations"]
        if [p["identity"]["patient_id"] for p in permissions] != scope["payload"]["patient_ids"]:
            raise ValueError("Whole declared patient authorization set required")
        for permission in permissions:
            checked = verify_registry_proof("authorization", permission)
            if (
                checked["parent_binding"]["scope"] != scope
                or checked["identity"]["authorization_kind"] not in {"permission_recorded", "waiver_recorded"}
                or checked["authorization_review"]["authorization_review_status"] != "recorded_reviewed"
            ):
                raise ValueError("Own literal patient permission differs")
        for proof in (scope, acl, *permissions):
            identity = proof["identity"]
            if identity["valid_from"] is None or not identity["valid_from"] <= value["captured_at"] < identity["valid_until"]:
                raise ValueError("Recorded authorization period did not cover capture")
            if proof["governance"]["status"] != "published" or proof["governance"]["reviewed_at"] > value["captured_at"]:
                raise ValueError("Captured publication required")
        if value["supported_columns"] != {family: list(FAMILY_COLUMNS[family]) for family in scope["payload"]["data_families"]}:
            raise ValueError("Declared exact recorded family columns differ")
        manifest = []
        seen = set()
        previous_record = None
        for entry in value["records"]:
            if type(entry) is not dict or set(entry) != {"family", "patient_id", "record_id", "original", "parent_binding", "window_status"}:
                raise ValueError("Closed record")
            family = entry["family"]
            raw, parent = entry["original"], entry["parent_binding"]
            if (
                family not in value["supported_columns"]
                or set(raw) != set(FAMILY_COLUMNS[family])
                or entry["patient_id"] not in scope["payload"]["patient_ids"]
                or raw["patient_id"] != entry["patient_id"]
                or raw[FAMILY_KEYS[family]] != entry["record_id"]
            ):
                raise ValueError("Whole original member differs")
            _validate_raw(family, raw)
            if type(parent) is not dict or set(parent) != {"kind", "status", "technical_hash"} or parent["status"] not in {"patient_bound", "unknown_parent", "missing_parent", "patient_mismatch"}:
                raise ValueError("Closed actual parent evidence")
            from app.ai.research_cohort_contract import SHA

            TypeAdapter(SHA).validate_python(parent["technical_hash"], strict=True)
            expected_kind = "registration_uuid" if family == "medical_records" else "admission_id" if family == "structured_medical_records" else "direct_patient_fk"
            if parent["kind"] != expected_kind or entry["window_status"] not in {"unknown_clock", "recorded_calendar_in_scope"}:
                raise ValueError("Parent/window types differ")
            if expected_kind == "direct_patient_fk" and parent != {"kind": expected_kind, "status": "patient_bound", "technical_hash": hash_content({"patient_id": entry["patient_id"]})}:
                raise ValueError("Direct patient parent differs")
            if (
                expected_kind != "direct_patient_fk"
                and raw[expected_kind] is None
                and parent != {"kind": expected_kind, "status": "unknown_parent", "technical_hash": hash_content({expected_kind: None})}
            ):
                raise ValueError("Null parent cannot be invented known")
            if family in FAMILY_CLOCKS:
                clock = raw[FAMILY_CLOCKS[family]]
                expected = "unknown_clock" if clock is None else "recorded_calendar_in_scope"
                if entry["window_status"] != expected or clock is not None and not scope["payload"]["record_window"]["date_from"] <= clock[:10] <= scope["payload"]["record_window"]["date_to"]:
                    raise ValueError("Recorded calendar window differs")
            elif entry["window_status"] != "recorded_calendar_in_scope":
                raise ValueError("Demographics has no encounter clock")
            locator = (entry["patient_id"], family, str(entry["record_id"]))
            if locator in seen or previous_record is not None and locator <= previous_record:
                raise ValueError("Sorted distinct originals required")
            seen.add(locator)
            previous_record = locator
            manifest.append(
                {
                    "family": family,
                    "patient_id": entry["patient_id"],
                    "record_id": entry["record_id"],
                    "content_hash": hash_content(raw),
                    "parent_binding_hash": hash_content(parent),
                    "window_status": entry["window_status"],
                }
            )
        if value["member_manifest"] != manifest or value["manifest_hash"] != hash_content(manifest):
            raise ValueError("All original manifest binding")
        _verify_authorization_manifest(value, scope, acl, permissions)
        if len(value["records"]) + len(value["authorization_manifest"]) + 1 > MAX_ROOTS:
            raise ValueError("Whole root budget")
        body = {k: v for k, v in value.items() if k not in {"captured_at", "collection_digest"}}
        if hash_content(body) != value["collection_digest"]:
            raise ValueError("Whole collection hash")
        return json.loads(canonical_json(value))
    except (HTTPException, ValueError, TypeError, KeyError, AttributeError, UnicodeError) as exc:
        raise HTTPException(409, "研究完整捕获原件、授权三锚或成员集合证明已损坏") from exc


def _validate_raw(family, raw):
    from app.ai.research_cohort_contract import DATE_FIELDS, SCALAR_FIELDS, TEXT_FIELDS, UUID, Date, Positive

    for field, value in raw.items():
        if field in SCALAR_FIELDS.get(family, set()) and value is not None and type(value) is not int:
            raise ValueError("Literal recorded integer required")
        if field in TEXT_FIELDS.get(family, set()) and value is not None and type(value) is not str:
            raise ValueError("Literal recorded text required")
        if field in DATE_FIELDS.get(family, set()) and value is not None:
            if field == "birthday":
                TypeAdapter(Date).validate_python(value, strict=True)
            elif dt.datetime.fromisoformat(value).isoformat(timespec="microseconds") != value or dt.datetime.fromisoformat(value).tzinfo is not None:
                raise ValueError("Literal naive calendar clock required")
        if field.endswith("_id") and field not in {"medical_record_id", "record_id", "admission_id"} and value is not None:
            TypeAdapter(Positive).validate_python(value, strict=True)
        if field in {"registration_uuid", "medical_record_id", "record_id", "admission_id"} and value is not None:
            TypeAdapter(UUID).validate_python(value, strict=True)


def _verify_authorization_manifest(value, scope, acl, permissions):
    from app.ai.research_cohort_contract import SHA, UTC, UUID

    roots = value["authorization_manifest"]
    if type(roots) is not list:
        raise ValueError("Complete authorization roots required")
    by_id = {}
    previous = None
    for item in roots:
        if type(item) is not dict or set(item) != {"kind", "source_record_id", "content_hash", "governance_hash", "metadata"} or item["kind"] not in {"acl", "authorization"}:
            raise ValueError("Closed authorization manifest")
        TypeAdapter(UUID).validate_python(item["source_record_id"], strict=True)
        for key in ("content_hash", "governance_hash"):
            TypeAdapter(SHA).validate_python(item[key], strict=True)
        locator = (item["kind"], item["source_record_id"])
        if locator in by_id or previous is not None and locator <= previous:
            raise ValueError("Sorted distinct complete authorization roots required")
        meta = item["metadata"]
        common = {"acl_id" if item["kind"] == "acl" else "authorization_id", "content_hash", "status", "revision", "created_at", "reviewed_at", "revoked_at", "valid_from", "valid_until"}
        expected = common | (
            {"user_id", "permission"}
            if item["kind"] == "acl"
            else {"patient_id", "authorization_kind", "access_basis", "authorization_review_status", "authorization_reviewed_by", "authorization_reviewed_at"}
        )
        if (
            type(meta) is not dict
            or set(meta) != expected
            or meta["content_hash"] != item["content_hash"]
            or meta["acl_id" if item["kind"] == "acl" else "authorization_id"] != item["source_record_id"]
        ):
            raise ValueError("Closed root technical metadata differs")
        if (
            meta["status"] not in {"draft", "published", "rejected", "revoked"}
            or type(meta["revision"]) is not int
            or meta["revision"] != (1 if meta["status"] == "draft" else 2 if meta["status"] in {"published", "rejected"} else 3 if meta["reviewed_at"] is not None else 2)
        ):
            raise ValueError("Root governance metadata differs")
        for key in ("created_at", "reviewed_at", "revoked_at", "valid_from", "valid_until", "authorization_reviewed_at"):
            if key in meta and meta[key] is not None:
                TypeAdapter(UTC).validate_python(meta[key], strict=True)
                if key not in {"valid_from", "valid_until"} and meta[key] > value["captured_at"]:
                    raise ValueError("Root available clock is after capture")
        by_id[locator] = item
        previous = locator
    for proof in (acl, *permissions):
        identity = proof["identity"]
        item = by_id.get((identity["source_kind"], identity["source_record_id"]))
        if item is None or (item["content_hash"], item["governance_hash"]) != (proof["content_hash"], proof["governance_hash"]):
            raise ValueError("Selected research permission absent from whole manifest")
        meta = item["metadata"]
        for key in ("status", "revision", "reviewed_at", "revoked_at"):
            if meta[key] != proof["governance"][key]:
                raise ValueError("Selected governance differs from complete roots")
        for key in ("created_at", "valid_from", "valid_until", "user_id" if identity["source_kind"] == "acl" else "patient_id"):
            if meta[key] != identity[key]:
                raise ValueError("Selected actual identity differs from root metadata")
