"""Immutable76 variable definitions, independent review and exact audit receipts."""

import uuid

from fastapi import HTTPException
from pydantic import TypeAdapter

from app.ai.models import AIAuditEvent
from app.ai.research_cohort_contract import UUID, SourceReview, SourceRevoke, canonical_json
from app.ai.research_cohort_sources import _bounded, _governance, _original_json, _typed, _verify_governance, hash_content, utc_text, utcnow, verify_scope_proof
from app.ai.research_cohort_write_guard import RESEARCH_SOURCE_ROLES, current_research_rows, lock_research_write
from app.ai.research_variables_authority import authorize_variable_scope, validate_dictionary_scope
from app.ai.research_variables_contract import DefinitionReview, DictionaryCreate
from app.ai.research_variables_models import MAX_BYTES, AIResearchVariableDictionary

DEFINITION_FIELDS = ("definition_review_status", "definition_reviewed_by", "definition_reviewed_at", "definition_review_basis")


def _audit_clock(value):
    # The existing shared Audit table physically retains whole seconds on
    # MySQL. Full UTC6 original/signature clocks remain in its exact JSON body.
    return value.replace(microsecond=0)


def _identity(row):
    return {
        "dictionary_id": row.dictionary_id,
        "scope_id": row.scope_id,
        "schema_version": "research_variable_dictionary_original_v1",
        "created_by": row.created_by,
        "created_at": utc_text(row.created_at),
        "created_event_id": row.created_event_id,
    }


def _definition(row):
    return {key: utc_text(getattr(row, key)) if key.endswith("_at") else getattr(row, key) for key in DEFINITION_FIELDS}


def dictionary_proof(row):
    """Validate a whole frozen original; this pure reconstruction grants no rights."""
    try:
        identity = _identity(row)
        for field in ("dictionary_id", "scope_id"):
            TypeAdapter(UUID).validate_python(identity[field], strict=True)
        if any(type(identity[key]) is not int or identity[key] <= 0 for key in ("created_by", "created_event_id")):
            raise ValueError("Actual creator and exact creation event required")
        payload = _original_json(row.dictionary_json, MAX_BYTES)
        parent = _original_json(row.parent_binding_json, 262144)
        if type(parent) is not dict or set(parent) != {"scope"}:
            raise ValueError("Closed whole scope parent required")
        scope = verify_scope_proof(parent["scope"])
        request = validate_dictionary_scope(payload, scope)
        if request.model_dump() != payload or row.scope_id != request.scope_id:
            raise ValueError("Exact typed dictionary and actual project required")
        if scope["governance"]["status"] != "published" or scope["governance"]["reviewed_at"] > identity["created_at"]:
            raise ValueError("Literal project publication must precede this original")
        if (row.scope_content_hash, row.scope_governance_hash) != (request.scope_content_hash, request.scope_governance_hash):
            raise ValueError("Actual stored parent anchors differ")
        if hash_content({"identity": identity, "payload": payload, "parent_binding": parent}) != row.content_hash:
            raise ValueError("Whole original SHA differs")
        governance, definition = _governance(row), _definition(row)
        # The existing signature validator is reused only as a structural
        # validator. Definition review retains its own explicitly named domain.
        manual = {name.replace("definition_", "authorization_"): value for name, value in definition.items()}
        _verify_governance(identity, governance, manual)
        if type(row.last_event_id) is not int or row.last_event_id <= 0:
            raise ValueError("Actual last event primary key required")
        return {
            "schema_version": "research_variable_dictionary_proof_v1",
            "identity": identity,
            "payload": payload,
            "parent_binding": parent,
            "content_hash": row.content_hash,
            "governance": governance,
            "definition_review": definition,
            "last_event_id": row.last_event_id,
            "governance_hash": hash_content(
                {"dictionary_id": row.dictionary_id, "content_hash": row.content_hash, "governance": governance, "definition_review": definition, "last_event_id": row.last_event_id}
            ),
        }
    except (HTTPException, ValueError, TypeError, KeyError, AttributeError, UnicodeError) as exc:
        raise HTTPException(409, "变量字典完整SHA、原项目、闭集定义或独立签署已损坏") from exc


def _header(db, identifier):
    try:
        TypeAdapter(UUID).validate_python(identifier, strict=True)
    except (ValueError, TypeError) as exc:
        raise HTTPException(422, "变量字典标识须为规范UUID") from exc
    columns = (
        AIResearchVariableDictionary.dictionary_id,
        AIResearchVariableDictionary.scope_id,
        AIResearchVariableDictionary.created_by,
        AIResearchVariableDictionary.created_at,
        AIResearchVariableDictionary.content_hash,
        AIResearchVariableDictionary.scope_content_hash,
        AIResearchVariableDictionary.scope_governance_hash,
        AIResearchVariableDictionary.status,
        AIResearchVariableDictionary.revision,
    )
    with db.no_autoflush:
        row = current_research_rows(db.query(*columns).filter_by(dictionary_id=identifier), shared=True).one_or_none()
    if row is None:
        raise HTTPException(404, "明确变量字典原件不存在")
    return row


def _scope_reference(header):
    return dict(scope_id=header.scope_id, scope_content_hash=header.scope_content_hash, scope_governance_hash=header.scope_governance_hash)


def _authorized_row(db, user, identifier, *, writing=False):
    actor = lock_research_write(db, user)
    header = _header(db, identifier)
    actor, scope, _, _ = authorize_variable_scope(db, actor, _scope_reference(header), capture=writing)
    with db.no_autoflush:
        row = current_research_rows(db.query(AIResearchVariableDictionary).filter_by(dictionary_id=identifier), shared=not writing).one()
    proof = dictionary_proof(row)
    if proof["parent_binding"]["scope"] != scope:
        raise HTTPException(409, "变量字典原项目与当前完整原件不一致")
    _verify_audits(db, row, proof)
    return actor, row, proof


def _create_detail(proof):
    return {"source_kind": "research_variable_dictionary", "identity": proof["identity"], "content_hash": proof["content_hash"]}


def _transition_detail(proof):
    return {"source_kind": "research_variable_dictionary", "content_hash": proof["content_hash"], "governance_hash": proof["governance_hash"]}


def _verify_audits(db, row, proof):
    created = current_research_rows(db.query(AIAuditEvent).filter_by(event_id=row.created_event_id), shared=True).one_or_none()
    if created is None or (created.actor_id, created.action, created.target, created.detail_json, utc_text(created.create_time)) != (
        row.created_by,
        "research.variable_dictionary.create",
        row.dictionary_id,
        canonical_json(_create_detail(proof)),
        utc_text(_audit_clock(row.created_at)),
    ):
        raise HTTPException(409, "变量字典具体创建审计回执或原创建时钟不一致")
    last = current_research_rows(db.query(AIAuditEvent).filter_by(event_id=row.last_event_id), shared=True).one_or_none()
    if last is None or last.target != row.dictionary_id:
        raise HTTPException(409, "变量字典具体最近审计回执不存在")
    if row.last_event_id == row.created_event_id:
        if row.status != "draft" or row.definition_review_status != "unknown":
            raise HTTPException(409, "变量字典签署状态缺少具体过渡回执")
        return
    if row.status == "revoked":
        action, actor, clock = "revoke", row.revoked_by, row.revoked_at
    elif row.status in {"published", "rejected"}:
        action, actor, clock = "review", row.reviewed_by, row.reviewed_at
    else:
        action, actor, clock = "definition_review", row.definition_reviewed_by, row.definition_reviewed_at
    if (last.actor_id, last.action, last.detail_json, utc_text(last.create_time)) != (
        actor,
        "research.variable_dictionary." + action,
        canonical_json(_transition_detail(proof)),
        utc_text(_audit_clock(clock)),
    ):
        raise HTTPException(409, "变量字典最近具体签署回执或原时钟不一致")


def _packet(db, row, proof):
    reviewer_current = None
    if row.definition_reviewed_by is not None:
        from app.models import User

        reviewer = current_research_rows(db.query(User.user_id, User.user_role).filter_by(user_id=row.definition_reviewed_by), shared=True).one_or_none()
        reviewer_current = reviewer is not None and reviewer.user_role in RESEARCH_SOURCE_ROLES
    reasons = []
    if row.status != "published":
        reasons.append("dictionary_not_published")
    if row.definition_review_status != "recorded_reviewed":
        reasons.append("independent_definition_review_unknown_or_not_confirmed")
    if reviewer_current is False:
        reasons.append("definition_reviewer_not_current")
    return {
        "dictionary_id": row.dictionary_id,
        "scope_id": row.scope_id,
        "content_hash": row.content_hash,
        "governance_hash": proof["governance_hash"],
        "status": row.status,
        "revision": row.revision,
        "original": proof,
        "eligible": not reasons,
        "exclusion_reasons": reasons,
        "definition_reviewer_current": reviewer_current,
        "eligibility_basis": "recorded_literal_definition_review_not_scientific_or_clinical_validation",
    }


def dictionary_current(db, user, identifier, *, audit_only=False):
    if type(audit_only) is not bool:
        raise HTTPException(422, "冻结技术核对开关须明确")
    if audit_only:
        lock_research_write(db, user, allowed_roles={"super_admin"})
        header = _header(db, identifier)
        return {
            "dictionary_id": header.dictionary_id,
            "scope_id": header.scope_id,
            "content_hash": header.content_hash,
            "status": header.status,
            "revision": header.revision,
            "original": None,
            "eligible": False,
            "exclusion_reasons": ["technical_metadata_only_no_patient_or_definition_body_authority"],
            "audit_only": True,
        }
    _, row, proof = _authorized_row(db, user, identifier)
    return _packet(db, row, proof)


def _finish(db, actor, row, action):
    before = (actor.user_id, actor.user_role, actor.token_invalid_before)
    proof = dictionary_proof(row)
    event = AIAuditEvent(actor_id=actor.user_id, action="research.variable_dictionary." + action, target=row.dictionary_id, detail_json="{}", create_time=_audit_clock(utcnow()))
    if action == "create":
        raise ValueError("Creation uses its preallocated actual audit primary key")
    db.add(event)
    db.flush()
    row.last_event_id = event.event_id
    proof = dictionary_proof(row)
    event.detail_json = canonical_json(_transition_detail(proof))
    # A transition's own actual SQL clock is its retained signature clock.
    event.create_time = _audit_clock(row.revoked_at if action == "revoke" else row.reviewed_at if action == "review" else row.definition_reviewed_at)
    db.flush()
    actor, fresh, actual = _authorized_row(db, actor, row.dictionary_id, writing=True)
    if actual != proof or (actor.user_id, actor.user_role, actor.token_invalid_before) != before:
        raise HTTPException(409, "变量字典原件、具体回执或请求授权在同事务变化")
    packet = _packet(db, fresh, actual)
    db.commit()
    return packet


def create_dictionary(db, user, values):
    request = _typed(DictionaryCreate, values)
    try:
        actor, scope, _, _ = authorize_variable_scope(db, user, {key: getattr(request, key) for key in ("scope_id", "scope_content_hash", "scope_governance_hash")}, capture=True)
        validate_dictionary_scope(request, scope)
        identifier, now = str(uuid.uuid4()), utcnow()
        event = AIAuditEvent(actor_id=actor.user_id, action="research.variable_dictionary.create", target=identifier, detail_json="{}", create_time=_audit_clock(now))
        db.add(event)
        db.flush()
        row = AIResearchVariableDictionary(
            dictionary_id=identifier,
            scope_id=request.scope_id,
            dictionary_json=_bounded(request.model_dump(), MAX_BYTES),
            parent_binding_json=_bounded({"scope": scope}, 262144),
            content_hash="0" * 64,
            scope_content_hash=request.scope_content_hash,
            scope_governance_hash=request.scope_governance_hash,
            definition_review_status="unknown",
            definition_reviewed_by=None,
            definition_reviewed_at=None,
            definition_review_basis="",
            created_by=actor.user_id,
            created_at=now,
            created_event_id=event.event_id,
            last_event_id=event.event_id,
            status="draft",
            revision=1,
            reviewed_by=None,
            reviewed_at=None,
            review_basis_note="",
            revoked_by=None,
            revoked_at=None,
            revoke_reason="",
        )
        row.content_hash = hash_content({"identity": _identity(row), "payload": request.model_dump(), "parent_binding": {"scope": scope}})
        expected = dictionary_proof(row)
        event.detail_json = canonical_json(_create_detail(expected))
        db.add(row)
        db.flush()
        _, fresh, proof = _authorized_row(db, actor, identifier, writing=True)
        if proof != expected:
            raise HTTPException(409, "变量字典创建后完整原件在同事务变化")
        packet = _packet(db, fresh, proof)
        db.commit()
        return packet
    except Exception:
        db.rollback()
        raise


def review_dictionary(db, user, identifier, values, *, definition=False, revoke=False):
    if definition and revoke:
        raise HTTPException(422, "变量核查与撤销必须为不同明确操作")
    request = _typed(DefinitionReview if definition else SourceRevoke if revoke else SourceReview, values)
    try:
        actor, row, _ = _authorized_row(db, user, identifier, writing=True)
        if row.revision != request.expected_revision:
            raise HTTPException(409, "变量字典明确原版本已变化")
        now = utcnow()
        if definition:
            if row.status != "draft" or row.definition_review_status != "unknown" or actor.user_id == row.created_by or request.expected_content_hash != row.content_hash:
                raise HTTPException(409, "变量定义独立核查不能自签、换原件或覆盖既有签署")
            row.definition_review_status, row.definition_reviewed_by, row.definition_reviewed_at, row.definition_review_basis = request.decision, actor.user_id, now, request.basis_note
            action = "definition_review"
        elif revoke:
            if row.status not in {"draft", "published"} or actor.user_role != "super_admin" and actor.user_id != row.created_by:
                raise HTTPException(403, "变量字典撤销须由当前原作者或超级管理员明确执行")
            row.status, row.revision, row.revoked_by, row.revoked_at, row.revoke_reason = "revoked", row.revision + 1, actor.user_id, now, request.basis_note
            action = "revoke"
        else:
            if actor.user_role != "super_admin":
                raise HTTPException(403, "变量字典技术发布或驳回仅限当前超级管理员")
            if row.status != "draft":
                raise HTTPException(409, "变量字典仅允许从明确草稿进行一次技术审核")
            row.status, row.revision, row.reviewed_by, row.reviewed_at, row.review_basis_note = "published" if request.decision == "publish" else "rejected", 2, actor.user_id, now, request.basis_note
            action = "review"
        return _finish(db, actor, row, action)
    except Exception:
        db.rollback()
        raise
