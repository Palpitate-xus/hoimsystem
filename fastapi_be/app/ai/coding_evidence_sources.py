"""Current case authorization, full original collection and immutable governance."""

import datetime
import hashlib
import json
import secrets
import uuid
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import inspect

from app.ai.coding_evidence_guard import current_coding_rows, lock_coding_write
from app.ai.coding_evidence_input import (
    SOURCE_ROLES,
    CaptureRequest,
    CaseCreate,
    CaseOriginalProof,
    Collection,
    DiagnosisDictionaryOriginal,
    Governance,
    OperationDictionaryOriginal,
    PackageOriginalProof,
    RulePackageCreate,
    SourceReview,
    SourceRevoke,
)
from app.ai.coding_evidence_models import MAX_BYTES, AICodingCaseSnapshot, AICodingRulePackage
from app.ai.coding_evidence_projection import POLICY, project_snapshot
from app.ai.governance import audit

IDENTITY = ("case_snapshot_id", "home_id", "admission_id", "patient_id", "rule_package_id", "schema_version", "created_at", "created_by", "collection_digest")
PACKAGE_IDENTITY = ("package_id", "package_kind", "schema_version", "created_at", "created_by", "collection_digest")
GOVERNANCE = ("status", "revision", "reviewed_at", "reviewed_by", "review_basis_note", "revoked_at", "revoked_by", "revoke_reason")


def utcnow():
    return datetime.datetime.now(datetime.UTC).replace(tzinfo=None)


def utc_text(v):
    return v.isoformat(timespec="microseconds") + "Z"


def json_value(v):
    if isinstance(v, (datetime.datetime, datetime.date)):
        return v.isoformat(timespec="microseconds") if isinstance(v, datetime.datetime) else v.isoformat()
    if isinstance(v, Decimal):
        return str(v)
    if isinstance(v, dict):
        return {k: json_value(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [json_value(x) for x in v]
    return v


def canonical_json(v):
    return json.dumps(v, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def hash_content(v):
    return hashlib.sha256(canonical_json(v).encode()).hexdigest()


def bounded(v):
    if len(canonical_json(v).encode()) > MAX_BYTES:
        raise HTTPException(409, "完整编码证据超过8MiB，拒绝截断或部分提交")
    return v


def row_value(row):
    return {c.name: json_value(getattr(row, c.name)) for c in inspect(type(row)).columns}


def typed(model, v):
    return model.model_validate(v.model_dump(mode="json") if hasattr(v, "model_dump") else v)


def current_actor(db, user, allowed_roles=SOURCE_ROLES):
    return lock_coding_write(db, user, allowed_roles=allowed_roles)


def authorize_admission(db, user, patient_id, admission_id):
    """Current case access before any original Home/binding/document body."""
    from app.ai.context import authorize_patient
    from app.ai.models import AIPatientGrant
    from app.models import Admission, Doctor, Patient

    actor = current_actor(db, user)
    admission = current_coding_rows(db.query(Admission).filter_by(admission_id=admission_id), shared=True).one_or_none()
    patient = current_coding_rows(db.query(Patient).filter_by(patient_id=patient_id), shared=True).one_or_none()
    if patient is None or admission is None or admission.patient_id != patient_id:
        raise HTTPException(403, "实际患者与住院作用域不一致")
    doctors = current_coding_rows(db.query(Doctor).filter_by(user_id=actor.user_id), shared=True).all()
    grants = current_coding_rows(db.query(AIPatientGrant).filter_by(user_id=actor.user_id, patient_id=patient_id, category="operations"), shared=True).all()
    if (
        actor.user_role not in {"admin", "super_admin"}
        and not any(g.revoked == 0 and g.expires_at > utcnow() for g in grants)
        and not any(admission.doctor_id == d.doctor_id or actor.user_role == "director" and admission.department_id == d.department_id for d in doctors)
    ):
        raise HTTPException(403, "当前实际病案关系或有效授权已不可用")
    authorize_patient(db, actor, patient_id, "operations", admission_id)
    return actor, admission, patient


def authorize_case(db, user, request):
    from app.models import MedicalRecordHome

    req = typed(CaptureRequest, request)
    actor = lock_coding_write(db, user, allowed_roles=SOURCE_ROLES, home_ids=(req.home_id,))
    locator = current_coding_rows(db.query(MedicalRecordHome.home_id, MedicalRecordHome.patient_id, MedicalRecordHome.admission_id).filter_by(home_id=req.home_id)).one()
    if (locator.patient_id, locator.admission_id) != (req.patient_id, req.admission_id):
        raise HTTPException(403, "实际病案、患者与住院作用域不一致")
    actor, admission, patient = authorize_admission(db, actor, req.patient_id, req.admission_id)
    home = current_coding_rows(db.query(MedicalRecordHome).filter_by(home_id=req.home_id)).one()
    return actor, home, admission, patient


def _rows(db, model, query, primary, cap, charge):
    ids = [r[0] for r in current_coding_rows(query.with_entities(primary).order_by(primary), shared=True).limit(cap + 1).all()]
    if len(ids) > cap:
        raise HTTPException(409, "相关原件超过完整成员上限，不能截断为已完整")
    result = []
    for identifier in ids:
        row = current_coding_rows(db.query(model).filter(primary == identifier), shared=True).one()
        value = row_value(row)
        charge(value)
        result.append(value)
    return result


def member_manifest(c):
    members = []

    def add(kind, record_id, value):
        members.append({"kind": kind, "record_id": str(record_id), "content_hash": hash_content(value)})

    add("home", c["home"]["home_id"], c["home"])
    add("admission_binding", c["admission_binding"]["admission_id"], c["admission_binding"])
    add("minimization_basis", "known_direct_identifiers", c["minimization_basis"])
    for key, kind, pk in [("code_bindings", "code_binding", "binding_id"), ("recorded_groups", "recorded_group", "grouping_id")]:
        for row in c[key]:
            add(kind, row[pk], row)
    for row in c["dictionary_entries"]:
        add("dictionary", str(row["kind"]) + ":" + str(row["code"]), row)
    for row in c["linked_rules"]:
        add("local_rule", row["rule_id"], row)
    if c["rule_package"] is not None:
        add("rule_package", c["rule_package"]["package_id"], c["rule_package"])
    return sorted(members, key=lambda r: (r["kind"], r["record_id"]))


def collection_content(c):
    return {k: v for k, v in c.items() if k not in {"captured_at", "collection_digest"}}


def capture_case(db, user, values):
    from app.models import DrgGrouping, DrgRule, HomeIcdBinding, Icd10Diagnosis, Icd10Operation

    req = typed(CaptureRequest, values)
    actor, home, admission, patient = authorize_case(db, user, req)
    used = 0

    def charge(v):
        nonlocal used
        used += len(canonical_json(v).encode())
        if used > MAX_BYTES:
            raise HTTPException(409, "完整编码资料超过8MiB，未返回部分清单")

    home_value = row_value(home)
    charge(home_value)
    bindings = _rows(db, HomeIcdBinding, db.query(HomeIcdBinding).filter_by(home_id=req.home_id), HomeIcdBinding.binding_id, 4096, charge)
    groups = _rows(db, DrgGrouping, db.query(DrgGrouping).filter_by(home_id=req.home_id), DrgGrouping.grouping_id, 256, charge)
    if any(r["patient_id"] != req.patient_id for r in groups):
        raise HTTPException(409, "已记录分组与实际首页患者存在冲突")
    entries = []
    for kind, code in sorted({(r["kind"], r["icd_code"]) for r in bindings}, key=lambda x: (str(x[0]), str(x[1]))):
        model = Icd10Diagnosis if kind == "diagnosis" else Icd10Operation if kind == "operation" else None
        row = None if model is None else current_coding_rows(db.query(model).filter_by(code=code), shared=True).one_or_none()
        value = {"kind": kind, "code": code, "entry": None if row is None or row.code != code else row_value(row)}
        charge(value)
        entries.append(value)
    rules = []
    for rid in sorted({r["rule_id"] for r in groups if r["rule_id"] is not None}):
        row = current_coding_rows(db.query(DrgRule).filter_by(rule_id=rid), shared=True).one_or_none()
        value = {"rule_id": rid, "entry": None if row is None else row_value(row)}
        charge(value)
        rules.append(value)
    if len(rules) > 4096:
        raise HTTPException(409, "实际关联规则超过完整上限")
    package = None
    if req.rule_package_id is not None:
        wrapper = package_current(db, actor, req.rule_package_id)
        if not wrapper["eligible"] or (wrapper["content_hash"], wrapper["governance_hash"]) != (req.expected_rule_package_content_hash, req.expected_rule_package_governance_hash):
            raise HTTPException(409, "明确规则包已失效或变化")
        package = {**{k: wrapper[k] for k in (*PACKAGE_IDENTITY, *GOVERNANCE, "content_hash", "source_id", "governance_hash")}, "snapshot": wrapper["snapshot"]}
        charge(package)
    result = {
        "schema_version": "coding_case_collection_v1",
        "request": req.model_dump(mode="json"),
        "captured_at": utc_text(utcnow()),
        "home": home_value,
        "admission_binding": {k: getattr(admission, k) for k in ("admission_id", "patient_id", "doctor_id", "department_id")},
        "minimization_basis": {k: getattr(patient, k) for k in ("name", "identity", "phone", "address")},
        "code_bindings": bindings,
        "dictionary_entries": entries,
        "recorded_groups": groups,
        "linked_rules": rules,
        "rule_package": package,
    }
    result["member_manifest"] = member_manifest(result)
    result["manifest_hash"] = hash_content(result["member_manifest"])
    result["collection_digest"] = hash_content(collection_content(result))
    bounded(result)
    if not verify_capture(result):
        raise HTTPException(409, "完整来源自身证明无效")
    return result


def verify_capture(c):
    try:
        typed(Collection, c)
        if member_manifest(c) != c["member_manifest"] or hash_content(c["member_manifest"]) != c["manifest_hash"]:
            return False
        if (
            set(c)
            != set(
                (
                    "schema_version",
                    "request",
                    "captured_at",
                    "home",
                    "admission_binding",
                    "minimization_basis",
                    "code_bindings",
                    "dictionary_entries",
                    "recorded_groups",
                    "linked_rules",
                    "rule_package",
                    "member_manifest",
                    "manifest_hash",
                    "collection_digest",
                )
            )
            or c["schema_version"] != "coding_case_collection_v1"
        ):
            return False
        req = typed(CaptureRequest, c["request"])
        h = c["home"]
        a = c["admission_binding"]
        if (h["home_id"], h["patient_id"], h["admission_id"]) != (req.home_id, req.patient_id, req.admission_id) or (a["patient_id"], a["admission_id"]) != (req.patient_id, req.admission_id):
            return False
        if set(c["minimization_basis"]) != {"name", "identity", "phone", "address"}:
            return False
        if len(c["code_bindings"]) > 4096 or len(c["recorded_groups"]) > 256 or len(c["linked_rules"]) > 4096:
            return False
        for name, key in [("code_bindings", "binding_id"), ("recorded_groups", "grouping_id")]:
            rows = c[name]
            ids = [r[key] for r in rows]
            if ids != sorted(set(ids)) or any(r["home_id"] != req.home_id for r in rows):
                return False
        if any(r["patient_id"] != req.patient_id for r in c["recorded_groups"]):
            return False
        if [(e["kind"], e["code"]) for e in c["dictionary_entries"]] != sorted({(r["kind"], r["icd_code"]) for r in c["code_bindings"]}, key=lambda x: (str(x[0]), str(x[1]))):
            return False
        if [r["rule_id"] for r in c["linked_rules"]] != sorted({r["rule_id"] for r in c["recorded_groups"] if r["rule_id"] is not None}):
            return False
        for item in c["dictionary_entries"]:
            if set(item) != {"kind", "code", "entry"} or item["entry"] is not None and item["entry"]["code"] != item["code"]:
                return False
            if item["entry"] is not None:
                model = DiagnosisDictionaryOriginal if item["kind"] == "diagnosis" else OperationDictionaryOriginal if item["kind"] == "operation" else None
                if model is None:
                    return False
                typed(model, item["entry"])
        for item in c["linked_rules"]:
            if set(item) != {"rule_id", "entry"} or item["entry"] is not None and item["entry"]["rule_id"] != item["rule_id"]:
                return False
        p = c["rule_package"]
        if req.rule_package_id is None:
            if p is not None:
                return False
        elif (
            p is None
            or not verify_original(p, "package")
            or (p["package_id"], p["content_hash"], p["governance_hash"], p["status"])
            != (req.rule_package_id, req.expected_rule_package_content_hash, req.expected_rule_package_governance_hash, "published")
        ):
            return False
        return hash_content(collection_content(c)) == c["collection_digest"] and len(canonical_json(c).encode()) <= MAX_BYTES
    except (Exception,):
        return False


def metadata(row):
    package = isinstance(row, AICodingRulePackage)
    keys = PACKAGE_IDENTITY if package else IDENTITY
    value = {k: json_value(getattr(row, k)) for k in (*keys, *GOVERNANCE, "content_hash")}
    value["created_at"] = utc_text(row.created_at)
    for key in ("reviewed_at", "revoked_at"):
        value[key] = utc_text(getattr(row, key)) if getattr(row, key) is not None else None
    value["source_id"] = ("coding_package:" if package else "coding_case:") + str(row.package_id if package else row.case_snapshot_id) + ":" + row.content_hash[:12]
    value["governance_hash"] = hash_content({k: value[k] for k in GOVERNANCE})
    return value


def governance_valid(v):
    try:
        from app.ai.supply_source_input import check_basis

        typed(Governance, {k: v[k] for k in GOVERNANCE})

        def clock(value):
            return datetime.datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ")

        created = clock(v["created_at"])
        reviewed = v["reviewed_at"] is not None
        revoked = v["revoked_at"] is not None
        if reviewed:
            check_basis(v["review_basis_note"])
            if v["reviewed_by"] is None or clock(v["reviewed_at"]) < created:
                return False
        elif v["reviewed_by"] is not None or v["review_basis_note"] != "":
            return False
        if revoked:
            check_basis(v["revoke_reason"])
            if v["revoked_by"] is None or clock(v["revoked_at"]) < clock(v["reviewed_at"] or v["created_at"]):
                return False
        elif v["revoked_by"] is not None or v["revoke_reason"] != "":
            return False
        return (
            (v["status"] == "draft" and v["revision"] == 1 and not reviewed and not revoked)
            or (v["status"] in {"published", "rejected"} and v["revision"] == 2 and reviewed and not revoked)
            or (v["status"] == "revoked" and revoked and v["revision"] == (3 if reviewed else 2))
        )
    except (ValueError, TypeError, KeyError):
        return False


def verify_original(value, kind="case"):
    try:
        if kind not in {"case", "package"}:
            return False
        typed(PackageOriginalProof if kind == "package" else CaseOriginalProof, value)
        if not governance_valid(value):
            return False
        identity = PACKAGE_IDENTITY if kind == "package" else IDENTITY
        if set(value) != {*identity, *GOVERNANCE, "content_hash", "source_id", "governance_hash", "snapshot"}:
            return False
        snapshot = value["snapshot"]
        if kind == "package":
            if set(snapshot) != {"schema_version", "rule_ids", "rules", "basis_note"} or snapshot["schema_version"] != "coding_local_prefix_package_v1":
                return False
            typed(RulePackageCreate, {"package_kind": "local_prefix_snapshot", "rule_ids": snapshot["rule_ids"], "basis_note": snapshot["basis_note"]})
            if snapshot["rule_ids"] != sorted(set(snapshot["rule_ids"])) or [r["rule_id"] for r in snapshot["rules"]] != snapshot["rule_ids"]:
                return False
            if hash_content(snapshot["rules"]) != value["collection_digest"]:
                return False
        elif (
            set(snapshot) != {"schema_version", "collection", "identity_secret", "note", "projection_policy"}
            or snapshot["schema_version"] != "coding_case_snapshot_v1"
            or snapshot["projection_policy"] != POLICY
            or not verify_capture(snapshot["collection"])
            or value["collection_digest"] != snapshot["collection"]["collection_digest"]
        ):
            return False
        if kind != "package":
            if snapshot["collection"]["captured_at"] > value["created_at"]:
                return False
            req = snapshot["collection"]["request"]
            if any(value[k] != req[k] for k in ("patient_id", "admission_id", "home_id", "rule_package_id")) or len(bytes.fromhex(snapshot["identity_secret"])) != 32:
                return False
        if hash_content({**{k: value[k] for k in identity}, "snapshot": snapshot}) != value["content_hash"] or hash_content({k: value[k] for k in GOVERNANCE}) != value["governance_hash"]:
            return False
        prefix = "coding_package:" if kind == "package" else "coding_case:"
        identifier = value["package_id" if kind == "package" else "case_snapshot_id"]
        if value["source_id"] != prefix + identifier + ":" + value["content_hash"][:12]:
            return False
        return len(canonical_json(value).encode()) <= MAX_BYTES
    except (Exception,):
        return False


def original(row, kind="case"):
    value = {**metadata(row), "snapshot": json.loads(row.snapshot_json)}
    if not verify_original(value, kind):
        raise HTTPException(409, "冻结原件、全集或自身SHA不一致")
    return value


def _rules(db, ids):
    from app.models import DrgRule

    result = []
    for rid in sorted(ids):
        row = current_coding_rows(db.query(DrgRule).filter_by(rule_id=rid), shared=True).one_or_none()
        if row is None:
            raise HTTPException(409, "明确选取的实际本地规则已不存在")
        result.append(row_value(row))
        bounded(result)
    return result


def package_current(db, user, identifier, *, audit_only=False):
    actor = current_actor(db, user, {"super_admin"} if audit_only else SOURCE_ROLES)
    row = current_coding_rows(db.query(AICodingRulePackage).filter_by(package_id=identifier)).one_or_none()
    if row is None:
        raise HTTPException(404, "本地前缀规则包不存在")
    value = original(row, "package")
    try:
        current = _rules(db, value["snapshot"]["rule_ids"])
        parent = hash_content(current) == row.collection_digest
    except HTTPException:
        parent = False
    eligible = parent and row.status == "published"
    visible = audit_only or parent and row.status in {"draft", "published"}
    return bounded(
        {
            **value,
            "snapshot": value["snapshot"] if visible else None,
            "review_basis_note": value["review_basis_note"] if visible else None,
            "revoke_reason": value["revoke_reason"] if visible else None,
            "parent_current": parent,
            "eligible": eligible,
            "exclusion_reasons": ([] if parent else ["local_rule_changed"]) + ([] if row.status == "published" else ["not_published"]),
            "can_record": actor.user_role == "super_admin",
            "can_review": actor.user_role == "super_admin" and parent and row.status == "draft",
            "can_revoke": actor.user_role == "super_admin" and row.status in {"draft", "published"},
            "audit_only": audit_only,
        }
    )


def create_package(db, user, values):
    req = typed(RulePackageCreate, values)
    actor = current_actor(db, user, {"super_admin"})
    rules = _rules(db, req.rule_ids)
    snapshot = {"schema_version": "coding_local_prefix_package_v1", "rule_ids": sorted(req.rule_ids), "rules": rules, "basis_note": req.basis_note}
    row = AICodingRulePackage(
        package_id=str(uuid.uuid4()),
        package_kind=req.package_kind,
        schema_version="coding_rule_package_private_v1",
        created_at=utcnow(),
        created_by=actor.user_id,
        snapshot_json=canonical_json(bounded(snapshot)),
        collection_digest=hash_content(rules),
        content_hash="0" * 64,
        status="draft",
        revision=1,
        review_basis_note="",
        revoke_reason="",
    )
    row.content_hash = hash_content({**{k: metadata(row)[k] for k in PACKAGE_IDENTITY}, "snapshot": snapshot})
    db.add(row)
    db.flush()
    audit(db, actor.user_id, "coding_package_create", "coding_rule_package:" + row.package_id, metadata(row))
    return row


def create_case(db, user, values):
    req = typed(CaseCreate, values)
    collection = capture_case(db, user, req.request)
    if collection["collection_digest"] != req.expected_collection_digest:
        raise HTTPException(409, "已审阅完整集合发生改变，请重新捕获")
    actor = current_actor(db, user)
    snapshot = {"schema_version": "coding_case_snapshot_v1", "collection": collection, "identity_secret": secrets.token_hex(32), "note": req.note, "projection_policy": POLICY.copy()}
    row = AICodingCaseSnapshot(
        case_snapshot_id=str(uuid.uuid4()),
        **req.request.model_dump(include={"patient_id", "home_id", "admission_id", "rule_package_id"}),
        schema_version="coding_case_private_v1",
        created_at=utcnow(),
        created_by=actor.user_id,
        snapshot_json=canonical_json(bounded(snapshot)),
        content_hash="0" * 64,
        collection_digest=collection["collection_digest"],
        status="draft",
        revision=1,
        review_basis_note="",
        revoke_reason="",
    )
    row.content_hash = hash_content({**{k: metadata(row)[k] for k in IDENTITY}, "snapshot": snapshot})
    db.add(row)
    db.flush()
    audit(db, actor.user_id, "coding_case_create", "coding_case_snapshot:" + row.case_snapshot_id, metadata(row))
    return row


def published_metadata(value):
    result = {k: value[k] for k in (*IDENTITY, *GOVERNANCE, "content_hash", "source_id", "governance_hash")}
    if value["reviewed_at"] is None:
        raise HTTPException(409, "本件没有真实原发布依据")
    result.update(status="published", revision=2, revoked_at=None, revoked_by=None, revoke_reason="")
    result["governance_hash"] = hash_content({k: result[k] for k in GOVERNANCE})
    return result


def case_current(db, user, identifier, *, audit_only=False, execution=False):
    actor = current_actor(db, user, {"super_admin"} if audit_only else SOURCE_ROLES)
    locator = current_coding_rows(
        db.query(AICodingCaseSnapshot.home_id, AICodingCaseSnapshot.patient_id, AICodingCaseSnapshot.admission_id).filter_by(case_snapshot_id=identifier), shared=True
    ).one_or_none()
    if locator is None:
        raise HTTPException(404, "编码证据快照不存在")
    if not audit_only:
        authorize_case(
            db,
            actor,
            {
                "home_id": locator.home_id,
                "patient_id": locator.patient_id,
                "admission_id": locator.admission_id,
                "rule_package_id": None,
                "expected_rule_package_content_hash": None,
                "expected_rule_package_governance_hash": None,
            },
        )
    row = current_coding_rows(db.query(AICodingCaseSnapshot).filter_by(case_snapshot_id=identifier)).one()
    value = original(row)
    parent = False
    reason = []
    try:
        current = capture_case(db, actor, value["snapshot"]["collection"]["request"])
        parent = current["collection_digest"] == row.collection_digest
    except HTTPException:
        if not audit_only:
            raise
        reason = ["current_case_unavailable"]
    if not parent and not reason:
        reason = ["case_members_changed"]
    if row.status != "published":
        reason.append("not_published")
    projection = None if row.projection_json is None else json.loads(row.projection_json)
    if projection is not None and (hash_content(projection) != row.projection_hash or project_snapshot(value["snapshot"], published_metadata(value)) != projection):
        raise HTTPException(409, "冻结最小化投影与原件不一致")
    visible = audit_only or parent and row.status in {"draft", "published"}
    if execution and (not parent or row.status != "published"):
        raise HTTPException(409, "当前病案或已发布快照已不可执行")
    return bounded(
        {
            **value,
            "snapshot": value["snapshot"] if visible else None,
            "review_basis_note": value["review_basis_note"] if visible else None,
            "revoke_reason": value["revoke_reason"] if visible else None,
            "public_source": projection if visible else None,
            "projection_hash": row.projection_hash,
            "eligible": parent and row.status == "published",
            "parent_current": parent,
            "exclusion_reasons": reason,
            "can_record": True,
            "can_review": actor.user_role == "super_admin" and parent and row.status == "draft",
            "can_revoke": row.status in {"draft", "published"} and (actor.user_role == "super_admin" or actor.user_id == row.created_by),
            "audit_only": audit_only,
        }
    )


def review(db, user, kind, identifier, values, *, revoke=False):
    if kind not in {"case", "package"}:
        raise ValueError("Closed coding original kind required")
    req = typed(SourceRevoke if revoke else SourceReview, values)
    actor = current_actor(db, user, SOURCE_ROLES if revoke and kind == "case" else {"super_admin"})
    model = AICodingCaseSnapshot if kind == "case" else AICodingRulePackage
    # The ordinary author's current patient/case access precedes loading the
    # immutable private JSON, including on revoke. Super governance is separate.
    value = case_current(db, actor, identifier, audit_only=actor.user_role == "super_admin") if kind == "case" else package_current(db, actor, identifier, audit_only=True)
    row = current_coding_rows(db.query(model).filter_by(**{"case_snapshot_id" if kind == "case" else "package_id": identifier})).one_or_none()
    if row is None:
        raise HTTPException(404, "原件不存在")
    if row.revision != req.expected_revision or row.content_hash != req.expected_content_hash:
        raise HTTPException(409, "原件内容或治理CAS已改变")
    if not (revoke and value["can_revoke"] or not revoke and value["can_review"]):
        raise HTTPException(403, "当前身份或原件状态不允许该治理操作")
    row.status = "revoked" if revoke else "published" if req.decision == "publish" else "rejected"
    row.revision += 1
    if revoke:
        row.revoked_by = actor.user_id
        row.revoked_at = utcnow()
        row.revoke_reason = req.basis_note
    else:
        row.reviewed_by = actor.user_id
        row.reviewed_at = utcnow()
        row.review_basis_note = req.basis_note
    if kind == "case" and row.status == "published":
        projection = bounded(project_snapshot(value["snapshot"], metadata(row)))
        row.projection_json = canonical_json(projection)
        row.projection_hash = hash_content(projection)
    db.flush()
    audit(db, actor.user_id, "coding_" + kind + "_" + row.status, "coding_" + kind + ":" + identifier, metadata(row))
    return row


FROZEN_EXTRA = ("public_source", "projection_hash", "frozen_task_view", "can_record", "can_review", "can_revoke")


def verify_frozen_case(value):
    try:
        proof = {k: v for k, v in value.items() if k not in FROZEN_EXTRA}
        if set(value) != {*IDENTITY, *GOVERNANCE, "content_hash", "source_id", "governance_hash", "snapshot", *FROZEN_EXTRA} or not verify_original(proof):
            return False
        if value["frozen_task_view"] is not True or any(value[k] is not False for k in ("can_record", "can_review", "can_revoke")):
            return False
        if value["status"] not in {"published", "revoked"} or value["reviewed_at"] is None:
            return False
        public = value["public_source"]
        return hash_content(public) == value["projection_hash"] and project_snapshot(value["snapshot"], published_metadata(value)) == public and len(canonical_json(value).encode()) <= MAX_BYTES
    except (ValueError, TypeError, KeyError, AttributeError):
        return False


def frozen_case(db, user, identifier, *, audit_only=False):
    view = case_current(db, user, identifier, audit_only=audit_only, execution=not audit_only)
    if view["snapshot"] is None or view["public_source"] is None:
        raise HTTPException(409, "没有可授权展开的完整已发布快照")
    result = {k: view[k] for k in (*IDENTITY, *GOVERNANCE, "content_hash", "source_id", "governance_hash", "snapshot", "public_source", "projection_hash")}
    result.update(frozen_task_view=True, can_record=False, can_review=False, can_revoke=False)
    if not verify_frozen_case(result):
        raise HTTPException(409, "完整冻结运行来源无法鉴真")
    return result


def frozen_case_proof(db, identifier):
    """INTERNAL: current SQL + immutable proof only; performs NO authorization.

    Caller must authorize the run/case first in this transaction. This function
    intentionally does not treat a current capability flag as historical proof.
    """
    from app.ai.coding_evidence_guard import lock_coding_gate

    lock_coding_gate(db)
    row = current_coding_rows(db.query(AICodingCaseSnapshot).filter_by(case_snapshot_id=identifier)).one_or_none()
    if row is None:
        raise HTTPException(409, "冻结编码证据原件已不存在")
    proof = original(row)
    if row.projection_json is None or row.projection_hash is None:
        raise HTTPException(409, "本件没有完整原发布投影")
    result = {
        **proof,
        "public_source": json.loads(row.projection_json),
        "projection_hash": row.projection_hash,
        "frozen_task_view": True,
        "can_record": False,
        "can_review": False,
        "can_revoke": False,
    }
    if not verify_frozen_case(result):
        raise HTTPException(409, "冻结完整来源与投影无法鉴真")
    return result
