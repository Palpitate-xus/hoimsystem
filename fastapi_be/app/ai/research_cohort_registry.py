"""Actual project ACL and per-patient research permission originals.

No clinical body is read by registry writes. Even Super must hold a current
explicit project ACL and every patient's current positive independently reviewed
permission before a clinical Case may be captured/read. A technical archive view
may retain only safe manifest/opaque hashes after that access is withdrawn.
"""

import datetime as dt
import json
import uuid

from fastapi import HTTPException
from pydantic import TypeAdapter

from app.ai.research_cohort_contract import UTC, UUID, AuthorizationReview, PatientAuthorizationCreate, Positive, ProjectACLCreate, SourceReview, SourceRevoke, canonical_json
from app.ai.research_cohort_models import PARENT_BYTES, SOURCE_BYTES, AIResearchPatientAuthorization, AIResearchProjectACL
from app.ai.research_cohort_sources import (
    _bounded,
    _declared_parents_current,
    _governance,
    _manual,
    _manual_reviewer_current,
    _original_json,
    _registry_authority,
    _typed,
    _verify_governance,
    actual_care_or_grant,
    hash_content,
    scope_proof,
    scope_row,
    utc_text,
    utcnow,
    verify_scope_proof,
)
from app.ai.research_cohort_write_guard import RESEARCH_SOURCE_ROLES, current_actor, current_research_rows, lock_research_write

MODELS = {
    "acl": (AIResearchProjectACL, "acl_id", ProjectACLCreate, "research_project_acl_v1"),
    "authorization": (AIResearchPatientAuthorization, "authorization_id", PatientAuthorizationCreate, "research_patient_auth_v1"),
}


def _model(kind):
    if type(kind) is not str or kind not in MODELS:
        raise HTTPException(422, "科研登记原件类别须明确为ACL或逐患者授权")
    return MODELS[kind]


def _row(db, kind, identifier, *, locking=False):
    model, pk, _, _ = _model(kind)
    with db.no_autoflush:
        row = current_research_rows(db.query(model).filter(getattr(model, pk) == identifier), shared=not locking).one_or_none()
    if row is None:
        raise HTTPException(404, "明确项目ACL或患者研究授权原件不存在")
    return row


def _identity(kind, row):
    _, pk, _, schema = _model(kind)
    identity = {
        "source_kind": kind,
        "source_record_id": getattr(row, pk),
        "scope_id": row.scope_id,
        "schema_version": row.schema_version,
        "created_by": row.created_by,
        "created_at": utc_text(row.created_at),
        "valid_from": utc_text(row.valid_from),
        "valid_until": utc_text(row.valid_until),
    }
    if kind == "acl":
        identity.update(user_id=row.user_id, permission=row.permission)
    else:
        identity.update(patient_id=row.patient_id, authorization_kind=row.authorization_kind, access_basis=row.access_basis)
    if row.schema_version != schema:
        raise ValueError("Original schema differs")
    return identity


def original_proof(kind, row):
    try:
        _, _, request_model, _ = _model(kind)
        payload = _original_json(row.payload_json, SOURCE_BYTES)
        request = request_model.model_validate(payload)
        if canonical_json(request.model_dump()) != canonical_json(payload):
            raise ValueError("Original scalar request differs")
        identity = _identity(kind, row)
        for key in ("source_record_id", "scope_id"):
            TypeAdapter(UUID).validate_python(identity[key], strict=True)
        for key in ("created_by", "user_id" if kind == "acl" else "patient_id"):
            TypeAdapter(Positive).validate_python(identity[key], strict=True)
        for key in ("created_at", "valid_from", "valid_until"):
            if identity[key] is not None:
                TypeAdapter(UTC).validate_python(identity[key], strict=True)
        parent = _original_json(row.parent_binding_json, PARENT_BYTES)
        if type(parent) is not dict or set(parent) != {"scope", "subject"}:
            raise ValueError("Closed original parent required")
        scope = verify_scope_proof(parent["scope"])
        if scope["governance"]["status"] != "published" or scope["governance"]["reviewed_at"] > identity["created_at"]:
            raise ValueError("The literal project publication must precede this original")
        if (
            request.scope_id != scope["identity"]["scope_id"]
            or request.scope_content_hash != scope["content_hash"]
            or request.scope_governance_hash != scope["governance_hash"]
            or row.scope_id != request.scope_id
        ):
            raise ValueError("Original explicit scope anchors differ")
        if identity["valid_from"] != request.valid_from or identity["valid_until"] != request.valid_until:
            raise ValueError("Actual validity differs from literal request")
        if kind == "acl":
            if (
                row.user_id != request.user_id
                or row.permission != request.permission
                or parent["subject"] != {"user_id": request.user_id}
                or request.user_id not in scope["payload"]["proposed_user_ids"]
            ):
                raise ValueError("Explicit actual project member differs")
            manual = None
        else:
            if (
                row.patient_id != request.patient_id
                or row.authorization_kind != request.authorization_kind
                or row.access_basis != request.access_basis
                or parent["subject"] != {"patient_id": request.patient_id}
                or request.patient_id not in scope["payload"]["patient_ids"]
            ):
                raise ValueError("Explicit actual patient research original differs")
            manual = _manual(row)
        if hash_content({"identity": identity, "payload": payload, "parent_binding": parent}) != row.content_hash:
            raise ValueError("Whole immutable original differs")
        governance = _governance(row)
        _verify_governance(identity, governance, manual or dict(authorization_review_status="unknown", authorization_reviewed_by=None, authorization_reviewed_at=None, authorization_review_basis=""))
        return {
            "schema_version": "research_registry_original_proof_v1",
            "identity": identity,
            "payload": payload,
            "parent_binding": parent,
            "content_hash": row.content_hash,
            "governance": governance,
            "authorization_review": manual,
            "governance_hash": hash_content({"governance": governance, "authorization_review": manual}),
        }
    except (HTTPException, ValueError, TypeError, KeyError, AttributeError, UnicodeError) as exc:
        raise HTTPException(409, "项目ACL或逐患者研究授权原件自身SHA、真实父件或独立签署已损坏") from exc


def verify_registry_proof(kind, value):
    """Rebuild a closed frozen registry original; this grants no live access."""
    from types import SimpleNamespace

    try:
        keys = {"schema_version", "identity", "payload", "parent_binding", "content_hash", "governance", "authorization_review", "governance_hash"}
        if type(value) is not dict or set(value) != keys or value["schema_version"] != "research_registry_original_proof_v1":
            raise ValueError("Closed original required")
        identity = value["identity"]
        base = {"source_kind", "source_record_id", "scope_id", "schema_version", "created_by", "created_at", "valid_from", "valid_until"}
        expected = base | ({"user_id", "permission"} if kind == "acl" else {"patient_id", "authorization_kind", "access_basis"})
        if type(identity) is not dict or set(identity) != expected or identity["source_kind"] != kind:
            raise ValueError("Closed actual identity required")
        fields = {k: v for k, v in identity.items() if k not in {"source_kind", "source_record_id"}}
        _, pk, _, _ = _model(kind)
        fields[pk] = identity["source_record_id"]
        fields.update(value["governance"])
        if kind == "authorization":
            fields.update(value["authorization_review"])
        elif value["authorization_review"] is not None:
            raise ValueError("ACL has no invented professional signer")
        for name in ("created_at", "valid_from", "valid_until", "reviewed_at", "revoked_at", "authorization_reviewed_at"):
            if name in fields and fields[name] is not None:
                TypeAdapter(UTC).validate_python(fields[name], strict=True)
                fields[name] = dt.datetime.strptime(fields[name], "%Y-%m-%dT%H:%M:%S.%fZ")
        fields.update(payload_json=canonical_json(value["payload"]), parent_binding_json=canonical_json(value["parent_binding"]), content_hash=value["content_hash"])
        checked = original_proof(kind, SimpleNamespace(**fields))
        if canonical_json(checked) != canonical_json(value):
            raise ValueError("Original reconstruction differs")
        return checked
    except (HTTPException, ValueError, TypeError, KeyError, AttributeError, UnicodeError) as exc:
        raise HTTPException(409, "冻结研究授权原件闭集或完整SHA已损坏") from exc


def _scope_eligible(db, row, proof):
    return (
        row.status == "published"
        and row.authorization_review_status == "recorded_reviewed"
        and _manual_reviewer_current(db, row) is True
        and row.valid_from <= utcnow() < row.valid_until
        and _declared_parents_current(db, proof["payload"])
    )


def _parent_current(db, proof):
    scope = scope_row(db, proof["identity"]["scope_id"])
    current = scope_proof(scope)
    return current == proof["parent_binding"]["scope"] and _scope_eligible(db, scope, current)


def _current_acl_records(db, actor, scope_id):
    return current_research_rows(db.query(AIResearchProjectACL.acl_id).filter_by(scope_id=scope_id, user_id=actor.user_id, status="published"), shared=True).limit(2).all()


def authorize_project_acl(db, user, scope_id, *, capture=False):
    """No Super/admin bypass; explicit current original grant only."""
    from app.dependencies import VALID_USER_ROLES

    actor = lock_research_write(db, user, allowed_roles=VALID_USER_ROLES - {"patient"})
    pending = current_research_rows(db.query(AIResearchProjectACL.acl_id).filter_by(scope_id=scope_id, user_id=actor.user_id, status="draft"), shared=True).first()
    if pending is not None:
        raise HTTPException(403, "项目访问授权存在未处置原件，未用旧正向记录盖过未知")
    candidates = _current_acl_records(db, actor, scope_id)
    if len(candidates) != 1:
        raise HTTPException(403, "未有且仅有一件明确当前项目ACL，未据角色或最新记录代授访问")
    row = _row(db, "acl", candidates[0].acl_id)
    proof = original_proof("acl", row)
    if not _parent_current(db, proof) or not row.valid_from <= utcnow() < row.valid_until or capture and row.permission != "read_capture":
        raise HTTPException(403, "原项目、独立核查、明确权限或有效期已不允许本次访问")
    return actor, proof


def authorize_patient_research(db, user, scope_id, patient_id, *, capture=False, use="cohort_criteria_review", external_model=False):
    """Project ACL plus one positive original, independent review and access basis."""
    actor, acl = authorize_project_acl(db, user, scope_id, capture=capture)
    scope = acl["parent_binding"]["scope"]
    if use not in scope["payload"]["permitted_uses"]:
        raise HTTPException(403, "本次明确研究用途不在受审项目授权中，未自动授予后续功能")
    if type(external_model) is not bool or external_model and scope["payload"]["external_model_use"] != "recorded_permitted":
        raise HTTPException(403, "模型处理许可未知或未允许，未因院内读取权限自动出站")
    if patient_id not in scope["payload"]["patient_ids"]:
        raise HTTPException(403, "该患者不属于项目明确且完整的有限声明集合")
    pending = current_research_rows(db.query(AIResearchPatientAuthorization.authorization_id).filter_by(scope_id=scope_id, patient_id=patient_id, status="draft"), shared=True).first()
    if pending is not None:
        raise HTTPException(403, "该患者研究授权存在未处置原件，保持未知而不保留有利赢家")
    rows = current_research_rows(db.query(AIResearchPatientAuthorization.authorization_id).filter_by(scope_id=scope_id, patient_id=patient_id, status="published"), shared=True).limit(2).all()
    if len(rows) != 1:
        raise HTTPException(403, "逐患者研究授权缺失或当前原件冲突，不按最新或有利记录补权")
    row = _row(db, "authorization", rows[0].authorization_id)
    proof = original_proof("authorization", row)
    if (
        row.authorization_kind not in {"permission_recorded", "waiver_recorded"}
        or row.authorization_review_status != "recorded_reviewed"
        or row.valid_from is None
        or not row.valid_from <= utcnow() < row.valid_until
        or not _parent_current(db, proof)
    ):
        raise HTTPException(403, "该患者研究许可未知、否定、退出、过期或原项目已变化")
    from app.models import User

    reviewer = current_research_rows(db.query(User.user_id, User.user_role).filter_by(user_id=row.authorization_reviewed_by), shared=True).one_or_none()
    if reviewer is None or reviewer.user_role not in RESEARCH_SOURCE_ROLES:
        raise HTTPException(403, "逐患者授权人工核查身份已失效")
    if row.access_basis == "current_care_or_grant" and not actual_care_or_grant(db, actor, patient_id):
        raise HTTPException(403, "该患者所声明的当前care/grant访问依据已失效")
    return actor, acl, proof


def _registry_access(db, actor, scope_id, *, writing=False):
    try:
        _registry_authority(db, actor, scope_id)
    except HTTPException as exc:
        if exc.status_code != 403:
            raise
        authorize_project_acl(db, actor, scope_id, capture=writing)


def registry_current(db, user, kind, identifier, *, audit_only=False):
    actor = lock_research_write(db, user)
    if audit_only and actor.user_role != "super_admin":
        raise HTTPException(403, "完整项目登记审计仅限当前超级管理员")
    model, pk, _, _ = _model(kind)
    header = current_research_rows(db.query(model.scope_id, model.created_by).filter(getattr(model, pk) == identifier), shared=True).one_or_none()
    if header is None:
        raise HTTPException(404, "研究授权登记原件不存在")
    _registry_access(db, actor, header.scope_id)
    row = _row(db, kind, identifier)
    proof = original_proof(kind, row)
    reasons = []
    if row.status != "published":
        reasons.append("original_not_published")
    current = _parent_current(db, proof)
    if not current:
        reasons.append("original_scope_or_review_not_current")
    if row.valid_from is None or not row.valid_from <= utcnow() < row.valid_until:
        reasons.append("permission_period_unknown_or_not_current")
    if kind == "authorization" and (row.authorization_kind not in {"permission_recorded", "waiver_recorded"} or row.authorization_review_status != "recorded_reviewed"):
        reasons.append("patient_permission_unknown_denied_withdrawn_or_unreviewed")
    visible = audit_only or row.status in {"draft", "published"} and current
    governance = dict(proof["governance"])
    manual = dict(proof["authorization_review"]) if proof["authorization_review"] is not None else None
    if not visible:
        governance["review_basis_note"] = governance["revoke_reason"] = None
        if manual is not None:
            manual["authorization_review_basis"] = None
    return {
        **proof["identity"],
        "source_id": f"research_{kind}:{identifier}:{row.content_hash[:12]}",
        "content_hash": row.content_hash,
        **governance,
        "authorization_review": manual,
        "governance_hash": proof["governance_hash"],
        "original": proof if visible else None,
        "parent_current": current,
        "eligible": not reasons,
        "exclusion_reasons": reasons,
        "can_record": False,
        "can_review": actor.user_role == "super_admin" and row.status == "draft" and current,
        "can_revoke": (actor.user_role == "super_admin" or actor.user_id == row.created_by and current) and row.status in {"draft", "published"},
        "can_authorization_review": kind == "authorization" and actor.user_id != row.created_by and row.status == "draft" and row.authorization_review_status == "unknown" and current,
        "audit_only": audit_only,
        "eligibility_basis": "recorded_project_permission_not_irb_certification_or_role_based_patient_access",
    }


def _finish(db, actor, kind, row, action):
    from app.ai.models import AIAuditEvent

    proof = original_proof(kind, row)
    identifier = proof["identity"]["source_record_id"]
    detail = canonical_json({"source_kind": kind, "content_hash": proof["content_hash"], "governance_hash": proof["governance_hash"]})
    audit = AIAuditEvent(actor_id=actor.user_id, action=action, target=identifier, detail_json=detail)
    db.add(audit)
    db.flush()
    fresh = current_actor(db, actor)
    event = current_research_rows(db.query(AIAuditEvent).filter_by(event_id=audit.event_id), shared=True).one()
    if (
        event.actor_id != fresh.user_id
        or event.action != action
        or event.target != identifier
        or event.detail_json != detail
        or original_proof(kind, _row(db, kind, identifier, locking=True)) != proof
    ):
        raise HTTPException(409, "研究授权或具体审核回执在同事务已变化，未提交")
    current_required = action.endswith(".create") or action.endswith(".manual_review") or action.endswith(".review") and row.status == "published"
    if current_required and scope_proof(scope_row(db, proof["identity"]["scope_id"])) != proof["parent_binding"]["scope"]:
        raise HTTPException(409, "项目原始完整三锚在同事务已变化，未偷偷绑定新父件")
    db.commit()
    return registry_current(db, fresh, kind, identifier, audit_only=fresh.user_role == "super_admin")


def create_registry_original(db, user, kind, values):
    model, pk, request_model, schema = _model(kind)
    request = _typed(request_model, values)
    try:
        actor = lock_research_write(db, user, scope_ids=(request.scope_id,))
        _registry_access(db, actor, request.scope_id, writing=True)
        scope = scope_proof(scope_row(db, request.scope_id))
        if scope["content_hash"] != request.scope_content_hash or scope["governance_hash"] != request.scope_governance_hash or scope["governance"]["status"] != "published":
            raise HTTPException(409, "项目三锚或技术发布状态已变化，未绑定新原件")
        if kind == "acl":
            if request.user_id not in scope["payload"]["proposed_user_ids"] or request.valid_from < scope["identity"]["valid_from"] or request.valid_until > scope["identity"]["valid_until"]:
                raise HTTPException(422, "项目ACL须在原明确成员和完整期限内")
            from app.models import User

            subject = current_research_rows(db.query(User.user_id).filter_by(user_id=request.user_id), shared=True).one_or_none()
            subject_value = {"user_id": request.user_id}
        else:
            if request.patient_id not in scope["payload"]["patient_ids"]:
                raise HTTPException(422, "研究授权患者须在原明确项目集合内")
            from app.models import Patient

            subject = current_research_rows(db.query(Patient.patient_id).filter_by(patient_id=request.patient_id), shared=True).one_or_none()
            subject_value = {"patient_id": request.patient_id}
        if subject is None:
            raise HTTPException(404, "真实项目用户或患者父件不存在")
        fields = dict(
            scope_id=request.scope_id,
            schema_version=schema,
            payload_json=_bounded(request.model_dump(), SOURCE_BYTES),
            parent_binding_json=_bounded({"scope": scope, "subject": subject_value}, PARENT_BYTES),
            content_hash="0" * 64,
            valid_from=dt.datetime.strptime(request.valid_from, "%Y-%m-%dT%H:%M:%S.%fZ") if request.valid_from is not None else None,
            valid_until=dt.datetime.strptime(request.valid_until, "%Y-%m-%dT%H:%M:%S.%fZ") if request.valid_until is not None else None,
            created_by=actor.user_id,
            created_at=utcnow(),
            status="draft",
            revision=1,
            reviewed_by=None,
            reviewed_at=None,
            review_basis_note="",
            revoked_by=None,
            revoked_at=None,
            revoke_reason="",
        )
        fields[pk] = str(uuid.uuid4())
        if kind == "acl":
            fields.update(user_id=request.user_id, permission=request.permission)
        else:
            fields.update(
                patient_id=request.patient_id,
                authorization_kind=request.authorization_kind,
                access_basis=request.access_basis,
                authorization_review_status="unknown",
                authorization_reviewed_by=None,
                authorization_reviewed_at=None,
                authorization_review_basis="",
            )
        row = model(**fields)
        row.content_hash = hash_content({"identity": _identity(kind, row), "payload": request.model_dump(), "parent_binding": json.loads(row.parent_binding_json)})
        db.add(row)
        db.flush()
        return _finish(db, actor, kind, row, "research." + kind + ".create")
    except Exception:
        db.rollback()
        raise


def review_registry_original(db, user, kind, identifier, values, *, revoke=False, manual=False):
    request = _typed(AuthorizationReview if manual else SourceRevoke if revoke else SourceReview, values)
    if manual and kind != "authorization":
        raise HTTPException(422, "项目ACL不伪造逐患者研究授权人工签署")
    try:
        actor = lock_research_write(db, user, allowed_roles=RESEARCH_SOURCE_ROLES if revoke or manual else {"super_admin"})
        model, pk, _, _ = _model(kind)
        header = current_research_rows(db.query(model.scope_id).filter(getattr(model, pk) == identifier), shared=True).one_or_none()
        if header is None:
            raise HTTPException(404, "研究授权登记原件不存在")
        _registry_access(db, actor, header.scope_id, writing=True)
        row = _row(db, kind, identifier, locking=True)
        original_proof(kind, row)
        if row.revision != request.expected_revision or row.status not in ({"draft", "published"} if revoke else {"draft"}):
            raise HTTPException(409, "原授权记录状态或CAS已变化")
        if actor.user_role != "super_admin" and revoke and row.created_by != actor.user_id:
            raise HTTPException(403, "只能撤销自己登记的授权原件")
        if manual:
            if row.created_by == actor.user_id or row.content_hash != request.expected_content_hash or row.authorization_review_status != "unknown":
                raise HTTPException(409, "逐患者核查必须独立且绑定明确原件，不覆盖旧签署")
            update = dict(authorization_review_status=request.decision, authorization_reviewed_by=actor.user_id, authorization_reviewed_at=utcnow(), authorization_review_basis=request.basis_note)
        elif revoke:
            update = dict(status="revoked", revision=row.revision + 1, revoked_by=actor.user_id, revoked_at=utcnow(), revoke_reason=request.basis_note)
        else:
            update = dict(status="published" if request.decision == "publish" else "rejected", revision=2, reviewed_by=actor.user_id, reviewed_at=utcnow(), review_basis_note=request.basis_note)
        query = db.query(model).filter(getattr(model, pk) == identifier, model.revision == request.expected_revision, model.status == row.status)
        if manual:
            query = query.filter_by(content_hash=request.expected_content_hash, authorization_review_status="unknown")
        if query.update(update, synchronize_session=False) != 1:
            raise HTTPException(409, "研究授权原件CAS未命中")
        row = _row(db, kind, identifier, locking=True)
        return _finish(db, actor, kind, row, "research." + kind + (".manual_review" if manual else ".revoke" if revoke else ".review"))
    except Exception:
        db.rollback()
        raise
