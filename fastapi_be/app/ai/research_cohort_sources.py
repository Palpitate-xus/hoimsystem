"""Immutable research registry originals before any clinical cohort collection.

A technically published Scope is never itself patient data permission, IRB
certification or a complete authorized cohort. Project ACL and every reviewed
patient authorization are separate prerequisites for the later collector.
"""

import datetime as dt
import hashlib
import json
import uuid

from fastapi import HTTPException
from pydantic import TypeAdapter, ValidationError

from app.ai.research_cohort_contract import UTC, UUID, AuthorizationReview, Basis, ScopeCreate, SourceReview, SourceRevoke, canonical_json
from app.ai.research_cohort_models import PARENT_BYTES, SOURCE_BYTES, AIResearchStudyScope
from app.ai.research_cohort_write_guard import RESEARCH_SOURCE_ROLES, current_actor, current_research_rows, lock_research_write

GOVERNANCE_FIELDS = ("status", "revision", "reviewed_by", "reviewed_at", "review_basis_note", "revoked_by", "revoked_at", "revoke_reason")
MANUAL_FIELDS = ("authorization_review_status", "authorization_reviewed_by", "authorization_reviewed_at", "authorization_review_basis")


def utcnow():
    return dt.datetime.now(dt.UTC).replace(tzinfo=None)


def utc_text(value):
    if value is None:
        return None
    if not isinstance(value, dt.datetime) or value.tzinfo is not None:
        raise ValueError("A server UTC6 value must be a retained naive SQL datetime")
    return value.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def hash_content(value):
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _typed(model, value):
    try:
        return value if isinstance(value, model) else model.model_validate(value)
    except (ValidationError, ValueError, TypeError, UnicodeError) as exc:
        raise HTTPException(422, "科研来源请求须符合完整闭集、规范日期和UTF8边界") from exc


def _bounded(value, cap):
    raw = canonical_json(value)
    if not 0 < len(raw.encode("utf-8")) <= cap:
        raise HTTPException(422, "科研整件来源或父件超过明确字节边界，未截断保存")
    return raw


def _original_json(raw, cap):
    if type(raw) is not str or not 0 < len(raw.encode("utf-8", errors="strict")) <= cap:
        raise ValueError("Invalid whole original byte boundary")
    value = json.loads(raw)
    if canonical_json(value) != raw:
        raise ValueError("Original JSON must be canonical, finite and duplicate-free")
    return value


def _identity(row):
    return {
        "source_kind": "study_scope",
        "source_record_id": row.scope_id,
        "scope_id": row.scope_id,
        "schema_version": row.schema_version,
        "created_by": row.created_by,
        "created_at": utc_text(row.created_at),
        "valid_from": utc_text(row.valid_from),
        "valid_until": utc_text(row.valid_until),
    }


def _governance(row):
    return {key: utc_text(getattr(row, key)) if key.endswith("_at") else getattr(row, key) for key in GOVERNANCE_FIELDS}


def _manual(row):
    return {key: utc_text(getattr(row, key)) if key.endswith("_at") else getattr(row, key) for key in MANUAL_FIELDS}


def _verify_governance(identity, governance, manual):
    if set(governance) != set(GOVERNANCE_FIELDS) or set(manual) != set(MANUAL_FIELDS):
        raise ValueError("Closed actual governance required")
    status, revision = governance["status"], governance["revision"]
    if type(revision) is not int or status not in {"draft", "published", "rejected", "revoked"}:
        raise ValueError("The exact technical status differs")
    reviewed = governance["reviewed_by"] is not None
    revoked = governance["revoked_by"] is not None
    if (
        status == "draft"
        and (revision != 1 or reviewed or revoked)
        or status in {"published", "rejected"}
        and (revision != 2 or not reviewed or revoked)
        or status == "revoked"
        and (not revoked or revision != (3 if reviewed else 2))
    ):
        raise ValueError("Invalid immutable technical lineage")
    for prefix, present in (("reviewed", reviewed), ("revoked", revoked)):
        by, at = governance[prefix + "_by"], governance[prefix + "_at"]
        note = governance["review_basis_note" if prefix == "reviewed" else "revoke_reason"]
        if present:
            if type(by) is not int or by < 1 or type(note) is not str or not note.strip() or not 20 <= len(note) <= (1000 if prefix == "revoked" else 4000) or len(note.encode("utf-8")) > 4000:
                raise ValueError("Incomplete actual governance signature")
            TypeAdapter(UTC).validate_python(at, strict=True)
            if at < identity["created_at"]:
                raise ValueError("Review predates server source")
        elif at is not None or note != "":
            raise ValueError("Unsigned governance must remain empty")
    if reviewed and revoked and governance["revoked_at"] < governance["reviewed_at"]:
        raise ValueError("Revoke predates review")
    state = manual["authorization_review_status"]
    if state == "unknown":
        if any(manual[key] is not None for key in ("authorization_reviewed_by", "authorization_reviewed_at")) or manual["authorization_review_basis"] != "":
            raise ValueError("Unknown manual review cannot invent a signature")
    elif state in {"recorded_reviewed", "not_confirmed"}:
        by, at, note = (manual[key] for key in ("authorization_reviewed_by", "authorization_reviewed_at", "authorization_review_basis"))
        if type(by) is not int or by < 1 or by == identity["created_by"] or type(note) is not str or not note.strip() or len(note.encode("utf-8")) > 4000:
            raise ValueError("Actual independent manual signature required")
        TypeAdapter(Basis).validate_python(note, strict=True)
        TypeAdapter(UTC).validate_python(at, strict=True)
        if at < identity["created_at"] or reviewed and at > governance["reviewed_at"]:
            raise ValueError("Manual review clock differs")
    else:
        raise ValueError("Manual review status is not a legal/IRB certification")


def scope_proof(row):
    """Full registry own original. It contains no queried clinical record body."""
    try:
        payload = _original_json(row.scope_json, SOURCE_BYTES)
        parent = _original_json(row.parent_binding_json, PARENT_BYTES)
        request = ScopeCreate.model_validate(payload)
        if request.model_dump() != payload:
            raise ValueError("Original scalar fields differ")
        identity = _identity(row)
        TypeAdapter(UUID).validate_python(identity["scope_id"], strict=True)
        if identity["schema_version"] != "research_study_scope_v1" or type(identity["created_by"]) is not int or identity["created_by"] < 1:
            raise ValueError("Invalid current source identity")
        for field in ("created_at", "valid_from", "valid_until"):
            TypeAdapter(UTC).validate_python(identity[field], strict=True)
        if identity["valid_from"] != request.valid_from or identity["valid_until"] != request.valid_until:
            raise ValueError("Original explicit validity differs")
        expected_parent = {"declared_patients": [{"patient_id": value} for value in request.patient_ids], "declared_users": [{"user_id": value} for value in request.proposed_user_ids]}
        if parent != expected_parent or hash_content({"identity": identity, "payload": payload, "parent_binding": parent}) != row.content_hash:
            raise ValueError("Whole immutable original or declared parents differ")
        governance, manual = _governance(row), _manual(row)
        _verify_governance(identity, governance, manual)
        return {
            "schema_version": "research_scope_original_proof_v1",
            "identity": identity,
            "payload": payload,
            "parent_binding": parent,
            "content_hash": row.content_hash,
            "governance": governance,
            "authorization_review": manual,
            "governance_hash": hash_content({"governance": governance, "authorization_review": manual}),
        }
    except (ValueError, TypeError, KeyError, AttributeError, UnicodeError, RecursionError) as exc:
        raise HTTPException(409, "科研项目原件自身完整SHA、真实身份、签署或时钟损坏") from exc


def scope_metadata(row, *, include_notes=False):
    proof = scope_proof(row)
    governance, manual = dict(proof["governance"]), dict(proof["authorization_review"])
    if not include_notes:
        governance["review_basis_note"] = governance["revoke_reason"] = None
        manual["authorization_review_basis"] = None
    return {
        **proof["identity"],
        "source_id": f"research_scope:{row.scope_id}:{row.content_hash[:12]}",
        "content_hash": proof["content_hash"],
        **governance,
        **manual,
        "governance_hash": proof["governance_hash"],
    }


def scope_row(db, identifier, *, locking=False):
    try:
        TypeAdapter(UUID).validate_python(identifier, strict=True)
    except (ValueError, TypeError) as exc:
        raise HTTPException(422, "科研项目原件标识须为规范UUID") from exc
    with db.no_autoflush:
        row = current_research_rows(db.query(AIResearchStudyScope).filter_by(scope_id=identifier), shared=not locking).one_or_none()
    if row is None:
        raise HTTPException(404, "科研项目登记原件不存在")
    return row


def _registry_authority(db, actor, identifier):
    # Only the author's supplied registry text or explicit Super technical audit
    # is exposed at this stage. This is not a patient data access authorizer.
    header = current_research_rows(db.query(AIResearchStudyScope.scope_id, AIResearchStudyScope.created_by).filter_by(scope_id=identifier), shared=True).one_or_none()
    if header is None:
        raise HTTPException(404, "科研项目登记原件不存在")
    if actor.user_role != "super_admin" and actor.user_id != header.created_by:
        raise HTTPException(403, "未授予读取该项目登记原件的权限")


def _declared_parents_current(db, payload):
    from app.models import Patient, User

    patients = current_research_rows(db.query(Patient.patient_id).filter(Patient.patient_id.in_(payload["patient_ids"])), shared=True).all()
    users = current_research_rows(db.query(User.user_id).filter(User.user_id.in_(payload["proposed_user_ids"])), shared=True).all()
    return sorted(row.patient_id for row in patients) == payload["patient_ids"] and sorted(row.user_id for row in users) == payload["proposed_user_ids"]


def actual_care_or_grant(db, actor, patient_id):
    """Current technical care/grant predicates, with no admin/Super bypass.

    This is only an access basis. It never establishes research permission.
    """
    from app.ai.models import AIPatientGrant
    from app.models import Admission, Doctor, LabOrder, MedicalRecord, Prescription, Registration

    grant = current_research_rows(
        db.query(AIPatientGrant.grant_id).filter(
            AIPatientGrant.user_id == actor.user_id, AIPatientGrant.patient_id == patient_id, AIPatientGrant.category == "knowledge", AIPatientGrant.revoked == 0, AIPatientGrant.expires_at > utcnow()
        ),
        shared=True,
    ).first()
    if grant is not None:
        return True
    doctors = current_research_rows(db.query(Doctor.doctor_id, Doctor.department_id).filter_by(user_id=actor.user_id), shared=True).limit(4097).all()
    if len(doctors) > 4096:
        raise HTTPException(409, "本账户实际Doctor父件超明确边界，未截断授权")
    ids = [row.doctor_id for row in doctors]
    if ids:
        for model in (Registration, MedicalRecord, Prescription, Admission, LabOrder):
            if current_research_rows(db.query(model.patient_id).filter(model.patient_id == patient_id, model.doctor_id.in_(ids)), shared=True).first() is not None:
                return True
    departments = sorted({row.department_id for row in doctors if row.department_id is not None})
    if actor.user_role == "director" and departments:
        for model in (Registration, Admission):
            if current_research_rows(db.query(model.patient_id).filter(model.patient_id == patient_id, model.department_id.in_(departments)), shared=True).first() is not None:
                return True
    return False


def _audit_and_readback(db, actor, row, action):
    from app.ai.models import AIAuditEvent

    expected = scope_proof(row)
    event = AIAuditEvent(
        actor_id=actor.user_id,
        action=action,
        target=row.scope_id,
        detail_json=canonical_json({"source_kind": "study_scope", "content_hash": row.content_hash, "governance_hash": expected["governance_hash"]}),
    )
    db.add(event)
    db.flush()
    fresh_actor = current_actor(db, actor)
    actual = current_research_rows(db.query(AIAuditEvent).filter_by(event_id=event.event_id), shared=True).one()
    if (
        actual.actor_id != fresh_actor.user_id
        or actual.action != action
        or actual.target != row.scope_id
        or actual.detail_json != canonical_json({"source_kind": "study_scope", "content_hash": expected["content_hash"], "governance_hash": expected["governance_hash"]})
    ):
        raise HTTPException(409, "具体科研来源审核回执或原操作身份已变化")
    if scope_proof(scope_row(db, row.scope_id, locking=True)) != expected or not _declared_parents_current(db, expected["payload"]):
        raise HTTPException(409, "科研登记原件或真实声明成员在同事务已变化，未提交")
    return fresh_actor


def _manual_reviewer_current(db, row):
    from app.models import User

    if row.authorization_reviewed_by is None:
        return None
    reviewer = current_research_rows(db.query(User.user_id, User.user_role).filter_by(user_id=row.authorization_reviewed_by), shared=True).one_or_none()
    return reviewer is not None and reviewer.user_role == "super_admin"


def scope_current(db, user, identifier, *, audit_only=False):
    actor = lock_research_write(db, user)
    if audit_only and actor.user_role != "super_admin":
        raise HTTPException(403, "完整技术冻结审计仅限当前超级管理员")
    _registry_authority(db, actor, identifier)
    row = scope_row(db, identifier)
    proof = scope_proof(row)
    reasons = []
    if row.status != "published":
        reasons.append("scope_not_published")
    if row.authorization_review_status != "recorded_reviewed":
        reasons.append("independent_authorization_review_unknown_or_not_confirmed")
    if not row.valid_from <= utcnow() < row.valid_until:
        reasons.append("project_authorization_period_not_current")
    reviewer_current = _manual_reviewer_current(db, row)
    if reviewer_current is False:
        reasons.append("authorization_reviewer_not_current")
    parent_current = _declared_parents_current(db, proof["payload"])
    if not parent_current:
        reasons.append("declared_parent_missing")
    visible = audit_only or row.status in {"draft", "published"} and parent_current
    return {
        **scope_metadata(row, include_notes=visible),
        "original": proof if visible else None,
        "parent_current": parent_current,
        "authorization_reviewer_current": reviewer_current,
        "eligible": not reasons,
        "exclusion_reasons": reasons,
        "can_record": False,
        "can_authorization_review": actor.user_role == "super_admin" and actor.user_id != row.created_by and row.status == "draft" and row.authorization_review_status == "unknown" and parent_current,
        "can_review": actor.user_role == "super_admin" and row.status == "draft" and parent_current,
        "can_revoke": (actor.user_role == "super_admin" or actor.user_id == row.created_by and parent_current) and row.status in {"draft", "published"},
        "audit_only": audit_only,
        "eligibility_basis": "project_registry_only_not_patient_collection_permission",
    }


def create_scope(db, user, values):
    request = _typed(ScopeCreate, values)
    try:
        actor = lock_research_write(db, user)
        # Admin clinical bypass is intentionally excluded. Super may register
        # supplied project originals, but cannot collect clinical rows by role.
        if actor.user_role != "super_admin" and not all(actual_care_or_grant(db, actor, patient) for patient in request.patient_ids):
            raise HTTPException(403, "登记所列患者须有实际care或限时grant访问依据；管理员角色不替代该依据")
        payload = request.model_dump()
        if not _declared_parents_current(db, payload):
            raise HTTPException(404, "明确声明的真实患者或项目用户父件不存在")
        now = utcnow()
        row = AIResearchStudyScope(
            scope_id=str(uuid.uuid4()),
            schema_version="research_study_scope_v1",
            scope_json=_bounded(payload, SOURCE_BYTES),
            parent_binding_json=_bounded(
                {"declared_patients": [{"patient_id": value} for value in request.patient_ids], "declared_users": [{"user_id": value} for value in request.proposed_user_ids]}, PARENT_BYTES
            ),
            content_hash="0" * 64,
            valid_from=dt.datetime.strptime(request.valid_from, "%Y-%m-%dT%H:%M:%S.%fZ"),
            valid_until=dt.datetime.strptime(request.valid_until, "%Y-%m-%dT%H:%M:%S.%fZ"),
            created_by=actor.user_id,
            created_at=now,
            status="draft",
            revision=1,
            reviewed_by=None,
            reviewed_at=None,
            review_basis_note="",
            revoked_by=None,
            revoked_at=None,
            revoke_reason="",
            authorization_review_status="unknown",
            authorization_reviewed_by=None,
            authorization_reviewed_at=None,
            authorization_review_basis="",
        )
        row.content_hash = hash_content({"identity": _identity(row), "payload": payload, "parent_binding": json.loads(row.parent_binding_json)})
        db.add(row)
        db.flush()
        actor = _audit_and_readback(db, actor, row, "research.scope.create")
        db.commit()
        return scope_current(db, actor, row.scope_id)
    except Exception:
        db.rollback()
        raise


def review_scope_authorization(db, user, identifier, values):
    request = _typed(AuthorizationReview, values)
    try:
        actor = lock_research_write(db, user, allowed_roles={"super_admin"}, scope_ids=(identifier,))
        row = scope_row(db, identifier, locking=True)
        scope_proof(row)
        if (
            actor.user_id == row.created_by
            or row.status != "draft"
            or row.revision != request.expected_revision
            or row.content_hash != request.expected_content_hash
            or row.authorization_review_status != "unknown"
        ):
            raise HTTPException(409, "独立人工核查须基于明确完整原件且不能由原创建人代签")
        changed = (
            db.query(AIResearchStudyScope)
            .filter_by(scope_id=identifier, status="draft", revision=1, content_hash=request.expected_content_hash, authorization_review_status="unknown")
            .update(
                dict(authorization_review_status=request.decision, authorization_reviewed_by=actor.user_id, authorization_reviewed_at=utcnow(), authorization_review_basis=request.basis_note),
                synchronize_session=False,
            )
        )
        if changed != 1:
            raise HTTPException(409, "原件或人工核查状态已变化")
        row = scope_row(db, identifier, locking=True)
        actor = _audit_and_readback(db, actor, row, "research.scope.authorization_review")
        db.commit()
        return scope_current(db, actor, identifier, audit_only=True)
    except Exception:
        db.rollback()
        raise


def review_scope(db, user, identifier, values, *, revoke=False):
    request = _typed(SourceRevoke if revoke else SourceReview, values)
    try:
        actor = lock_research_write(db, user, allowed_roles=RESEARCH_SOURCE_ROLES if revoke else {"super_admin"}, scope_ids=(identifier,))
        _registry_authority(db, actor, identifier)
        row = scope_row(db, identifier, locking=True)
        scope_proof(row)
        if row.revision != request.expected_revision or row.status not in ({"draft", "published"} if revoke else {"draft"}):
            raise HTTPException(409, "项目登记原件审核版本或状态已变化")
        if revoke:
            update = dict(status="revoked", revision=row.revision + 1, revoked_by=actor.user_id, revoked_at=utcnow(), revoke_reason=request.basis_note)
        else:
            update = dict(status="published" if request.decision == "publish" else "rejected", revision=2, reviewed_by=actor.user_id, reviewed_at=utcnow(), review_basis_note=request.basis_note)
        changed = db.query(AIResearchStudyScope).filter_by(scope_id=identifier, status=row.status, revision=request.expected_revision).update(update, synchronize_session=False)
        if changed != 1:
            raise HTTPException(409, "原审核CAS未命中，未覆盖新状态")
        row = scope_row(db, identifier, locking=True)
        actor = _audit_and_readback(db, actor, row, "research.scope.revoke" if revoke else "research.scope.review")
        db.commit()
        return scope_current(db, actor, identifier, audit_only=actor.user_role == "super_admin")
    except Exception:
        db.rollback()
        raise


def verify_scope_proof(value):
    """Pure own-proof reconstruction; it grants no current project access."""
    from types import SimpleNamespace

    try:
        if (
            type(value) is not dict
            or set(value) != {"schema_version", "identity", "payload", "parent_binding", "content_hash", "governance", "authorization_review", "governance_hash"}
            or value["schema_version"] != "research_scope_original_proof_v1"
        ):
            raise ValueError("Closed complete project original required")
        identity = value["identity"]
        if type(identity) is not dict or set(identity) != {"source_kind", "source_record_id", "scope_id", "schema_version", "created_by", "created_at", "valid_from", "valid_until"}:
            raise ValueError("Closed project identity required")
        fields = {key: dt.datetime.strptime(identity[key], "%Y-%m-%dT%H:%M:%S.%fZ") for key in ("created_at", "valid_from", "valid_until")}
        for group in (value["governance"], value["authorization_review"]):
            for key, child in group.items():
                fields[key] = dt.datetime.strptime(child, "%Y-%m-%dT%H:%M:%S.%fZ") if key.endswith("_at") and child is not None else child
        row = SimpleNamespace(
            scope_id=identity["scope_id"],
            schema_version=identity["schema_version"],
            created_by=identity["created_by"],
            scope_json=_bounded(value["payload"], SOURCE_BYTES),
            parent_binding_json=_bounded(value["parent_binding"], PARENT_BYTES),
            content_hash=value["content_hash"],
            **fields,
        )
        proof = scope_proof(row)
        if canonical_json(proof) != canonical_json(value):
            raise ValueError("Original technical identity, body or full governance differs")
        return proof
    except (HTTPException, ValueError, TypeError, KeyError, AttributeError, UnicodeError) as exc:
        raise HTTPException(409, "完整科研项目原件证明无效，未据局部哈希恢复权限") from exc
