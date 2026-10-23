"""Purpose-authorized76 Batch lifecycle, full recapture and exact SQL receipts."""

import secrets
import uuid
from types import SimpleNamespace

from fastapi import HTTPException
from pydantic import TypeAdapter

from app.ai.models import AIAuditEvent
from app.ai.research_cohort_contract import UUID, SourceReview, SourceRevoke, canonical_json
from app.ai.research_cohort_sources import _bounded, _typed, hash_content, utc_text, utcnow
from app.ai.research_cohort_write_guard import current_research_rows, lock_research_write
from app.ai.research_variables_authority import authorize_variable_scope
from app.ai.research_variables_batch_proof import batch_creation_detail, batch_governance_hash, batch_proof, batch_transition_detail, verify_batch_audits
from app.ai.research_variables_collection import capture_variable_sources
from app.ai.research_variables_contract import BatchCreate
from app.ai.research_variables_dictionary import _audit_clock
from app.ai.research_variables_fields import VARIABLE_SOURCE_ROLES
from app.ai.research_variables_models import MAX_BYTES, AIResearchVariableBatch
from app.ai.research_variables_snapshot import make_variable_snapshot, project_variable_snapshot


def _epoch(actor):
    return actor.user_id, actor.user_role, actor.token_invalid_before


def _header(db, identifier):
    try:
        TypeAdapter(UUID).validate_python(identifier, strict=True)
    except (ValueError, TypeError) as exc:
        raise HTTPException(422, "变量批次标识须为明确规范UUID") from exc
    columns = (
        AIResearchVariableBatch.batch_id,
        AIResearchVariableBatch.scope_id,
        AIResearchVariableBatch.dictionary_id,
        AIResearchVariableBatch.created_by,
        AIResearchVariableBatch.content_hash,
        AIResearchVariableBatch.scope_content_hash,
        AIResearchVariableBatch.scope_governance_hash,
        AIResearchVariableBatch.status,
        AIResearchVariableBatch.revision,
    )
    with db.no_autoflush:
        header = current_research_rows(db.query(*columns).filter_by(batch_id=identifier), shared=True).one_or_none()
    if header is None:
        raise HTTPException(404, "明确变量批次来源不存在")
    return header


def _authorized_row(db, user, identifier, *, writing=False):
    actor = lock_research_write(db, user, allowed_roles=VARIABLE_SOURCE_ROLES)
    header = _header(db, identifier)
    reference = {key: getattr(header, key) for key in ("scope_id", "scope_content_hash", "scope_governance_hash")}
    # The selected patient list lives in the private Batch. Conservatively
    # authorize ALL original Scope patients before its first private TEXT read.
    actor, scope, _, _ = authorize_variable_scope(db, actor, reference, capture=writing)
    with db.no_autoflush:
        row = current_research_rows(db.query(AIResearchVariableBatch).filter_by(batch_id=identifier), shared=not writing).one()
    proof = batch_proof(row)
    if proof["snapshot"]["capture"]["scope_original"] != scope:
        raise HTTPException(409, "变量批次原项目与当前完整项目原件不同")
    verify_batch_audits(db, row, proof)
    return actor, row, proof


def _current_collection(db, proof):
    snapshot = proof["snapshot"]
    try:
        captured = capture_variable_sources(db, SimpleNamespace(user_id=snapshot["created_by"]), snapshot["request"])
        return captured["collection_digest"] == snapshot["collection_digest"]
    except HTTPException as exc:
        if exc.status_code not in {403, 404, 409}:
            raise
        return False


def _packet(db, row, proof):
    current = _current_collection(db, proof)
    reasons = ([] if row.status == "published" else ["batch_not_published"]) + ([] if current else ["original_capture_or_creator_project_authority_no_longer_current"])
    return {
        "batch_id": row.batch_id,
        "scope_id": row.scope_id,
        "dictionary_id": row.dictionary_id,
        "content_hash": row.content_hash,
        "governance_hash": proof["governance_hash"],
        "projection_hash": row.projection_hash,
        "status": row.status,
        "revision": row.revision,
        "original": proof,
        "eligible": not reasons,
        "exclusion_reasons": reasons,
        "eligibility_basis": "current_recorded_fields_and_reviewed_definitions_not_scientific_validation",
    }


def batch_current(db, user, identifier, *, audit_only=False):
    if type(audit_only) is not bool:
        raise HTTPException(422, "技术元数据核对开关须明确布尔值")
    if audit_only:
        lock_research_write(db, user, allowed_roles={"super_admin"})
        header = _header(db, identifier)
        return {
            "batch_id": header.batch_id,
            "scope_id": header.scope_id,
            "dictionary_id": header.dictionary_id,
            "content_hash": header.content_hash,
            "status": header.status,
            "revision": header.revision,
            "original": None,
            "eligible": False,
            "audit_only": True,
            "exclusion_reasons": ["technical_metadata_only_no_patient_or_variable_body_authority"],
        }
    _, row, proof = _authorized_row(db, user, identifier)
    return _packet(db, row, proof)


def _set_projection(row, snapshot):
    source = project_variable_snapshot(snapshot, batch_governance_hash(row), identity_key=row.identity_key)
    row.projection_json, row.projection_hash = _bounded(source, MAX_BYTES), hash_content(source)


def create_batch(db, user, values):
    request = _typed(BatchCreate, values)
    try:
        actor = lock_research_write(db, user, allowed_roles=VARIABLE_SOURCE_ROLES)
        epoch = _epoch(actor)
        captured = capture_variable_sources(db, actor, request.model_dump(exclude={"basis_note"}))
        identifier, now, key = str(uuid.uuid4()), utcnow(), secrets.token_bytes(32)
        event = AIAuditEvent(actor_id=actor.user_id, action="research.variable_batch.create", target=identifier, detail_json="{}", create_time=_audit_clock(now))
        db.add(event)
        db.flush()
        snapshot = make_variable_snapshot(identifier, actor.user_id, captured, request.basis_note, identity_key=key, created_event_id=event.event_id, created_at=utc_text(now))
        row = AIResearchVariableBatch(
            batch_id=identifier,
            scope_id=request.scope_id,
            dictionary_id=request.variable_dictionary_id,
            snapshot_json=_bounded(snapshot, MAX_BYTES),
            projection_json="{}",
            identity_key=key,
            content_hash=hash_content(snapshot),
            projection_hash="0" * 64,
            collection_digest=snapshot["collection_digest"],
            member_manifest_hash=snapshot["member_manifest_hash"],
            scope_content_hash=request.scope_content_hash,
            scope_governance_hash=request.scope_governance_hash,
            dictionary_content_hash=request.dictionary_content_hash,
            dictionary_governance_hash=request.dictionary_governance_hash,
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
        _set_projection(row, snapshot)
        expected = batch_proof(row)
        event.detail_json = canonical_json(batch_creation_detail(expected))
        db.add(row)
        db.flush()
        actor, fresh, actual = _authorized_row(db, actor, identifier, writing=True)
        if actual != expected or _epoch(actor) != epoch or not _current_collection(db, actual):
            raise HTTPException(409, "变量批次创建后原件、实际回执、授权或全部当前字段已变化")
        packet = _packet(db, fresh, actual)
        db.commit()
        return packet
    except Exception:
        db.rollback()
        raise


def review_batch(db, user, identifier, values, *, revoke=False):
    if type(revoke) is not bool:
        raise HTTPException(422, "变量批次撤销开关须明确")
    request = _typed(SourceRevoke if revoke else SourceReview, values)
    try:
        actor, row, before = _authorized_row(db, user, identifier, writing=True)
        epoch, now = _epoch(actor), utcnow()
        if row.revision != request.expected_revision:
            raise HTTPException(409, "变量批次原治理版本已变化")
        if revoke:
            if row.status not in {"draft", "published"} or actor.user_role != "super_admin" and actor.user_id != row.created_by:
                raise HTTPException(403, "变量批次撤销须由当前原作者或超级管理员明确执行")
            row.status, row.revision, row.revoked_by, row.revoked_at, row.revoke_reason = "revoked", row.revision + 1, actor.user_id, now, request.basis_note
            action = "revoke"
        else:
            if actor.user_role != "super_admin":
                raise HTTPException(403, "变量批次技术发布或驳回仅限当前超级管理员")
            if row.status != "draft":
                raise HTTPException(409, "变量批次仅从明确草稿做一次技术审核")
            if request.decision == "publish" and not _current_collection(db, before):
                raise HTTPException(409, "变量批次原字典、来源或捕获者研究权限已不再当前有效")
            row.status, row.revision, row.reviewed_by, row.reviewed_at, row.review_basis_note = "published" if request.decision == "publish" else "rejected", 2, actor.user_id, now, request.basis_note
            action = "review"
        event = AIAuditEvent(actor_id=actor.user_id, action="research.variable_batch." + action, target=row.batch_id, detail_json="{}", create_time=_audit_clock(now))
        db.add(event)
        db.flush()
        row.last_event_id = event.event_id
        _set_projection(row, before["snapshot"])
        expected = batch_proof(row)
        event.detail_json = canonical_json(batch_transition_detail(expected))
        db.flush()
        actor, fresh, actual = _authorized_row(db, actor, identifier, writing=True)
        if actual != expected or _epoch(actor) != epoch:
            raise HTTPException(409, "变量批次治理后完整原件、实际回执或请求授权已变化")
        packet = _packet(db, fresh, actual)
        db.commit()
        return packet
    except Exception:
        db.rollback()
        raise
