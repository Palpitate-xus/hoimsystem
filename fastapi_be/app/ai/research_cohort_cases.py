"""Immutable finite research Cases with separate technical governance.

Current clinical reads require every patient's permission even for Super.
Technical audit can internally verify bytes after loss but returns only opaque
manifest/metadata, never clinical raw/evidence or a restored model permission.
"""

import uuid
from types import SimpleNamespace

from fastapi import HTTPException
from pydantic import TypeAdapter
from sqlalchemy.orm import defer

from app.ai.research_cohort_collection import capture_sources
from app.ai.research_cohort_contract import UUID, CaptureRequest, CaseCreate, ScopeReference, SourceReview, SourceRevoke, canonical_json
from app.ai.research_cohort_models import SNAPSHOT_BYTES, AIResearchCohortCase
from app.ai.research_cohort_registry import authorize_patient_research, authorize_project_acl
from app.ai.research_cohort_snapshot import current_recipe, opaque, project_snapshot, verify_snapshot
from app.ai.research_cohort_sources import _bounded, _governance, _original_json, _typed, hash_content, utc_text, utcnow
from app.ai.research_cohort_write_guard import current_actor, current_research_rows, lock_research_write


def _row(db, identifier, *, body=True, locking=False):
    query = db.query(AIResearchCohortCase).filter_by(case_id=identifier)
    if not body:
        query = query.options(defer(AIResearchCohortCase.snapshot_json), defer(AIResearchCohortCase.projection_json))
    with db.no_autoflush:
        row = current_research_rows(query, shared=not locking).one_or_none()
    if row is None:
        raise HTTPException(404, "明确研究队列病例不存在")
    return row


def metadata(row):
    return {
        "case_id": row.case_id,
        "scope_id": row.scope_id,
        "schema_version": row.schema_version,
        "created_by": row.created_by,
        "created_at": utc_text(row.created_at),
        "content_hash": row.content_hash,
        "collection_digest": row.collection_digest,
        "scope_binding_hash": row.scope_binding_hash,
        "member_manifest_hash": row.member_manifest_hash,
        "status": row.status,
        "revision": row.revision,
        "reviewed_by": row.reviewed_by,
        "reviewed_at": utc_text(row.reviewed_at),
        "review_basis_hash": hash_content(row.review_basis_note),
        "revoked_by": row.revoked_by,
        "revoked_at": utc_text(row.revoked_at),
        "revoke_reason_hash": hash_content(row.revoke_reason),
        "projection_hash": row.projection_hash,
    }


def governance_hash(row, *, publication=False):
    governance = _governance(row)
    if publication:
        if row.status not in {"published", "revoked"} or row.reviewed_at is None or row.projection_hash is None:
            raise HTTPException(409, "病例不存在原技术发布锚")
        governance = {**governance, "status": "published", "revision": 2, "revoked_by": None, "revoked_at": None, "revoke_reason": ""}
    return hash_content({"case_id": row.case_id, "content_hash": row.content_hash, "governance": governance})


def case_proof(row, *, validate_current_recipe=False):
    snapshot = verify_snapshot(_original_json(row.snapshot_json, SNAPSHOT_BYTES), validate_current_recipe=validate_current_recipe)
    if (
        row.schema_version != snapshot["schema_version"]
        or row.case_id != snapshot["case_id"]
        or row.scope_id != snapshot["scope_id"]
        or row.created_by != snapshot["created_by"]
        or utc_text(row.created_at) != snapshot["captured_at"]
        or row.content_hash != hash_content(snapshot)
        or row.collection_digest != snapshot["collection_digest"]
        or row.scope_binding_hash != snapshot["scope_binding_hash"]
        or row.member_manifest_hash != snapshot["member_manifest_hash"]
    ):
        raise HTTPException(409, "研究病例原件SHA与真实身份/集合列不一致")
    from app.ai.research_cohort_sources import _verify_governance

    _verify_governance(
        {"created_at": utc_text(row.created_at), "created_by": row.created_by},
        _governance(row),
        dict(authorization_review_status="unknown", authorization_reviewed_by=None, authorization_reviewed_at=None, authorization_review_basis=""),
    )
    projected = None
    if row.projection_json is not None or row.projection_hash is not None:
        if row.status not in {"published", "revoked"} or row.reviewed_at is None or row.projection_json is None or row.projection_hash is None:
            raise HTTPException(409, "研究公开投影与原技术发布不闭合")
        projected = project_snapshot(snapshot, governance_hash(row, publication=True), validate_current_recipe=validate_current_recipe)
        if _original_json(row.projection_json, SNAPSHOT_BYTES) != projected or hash_content(projected) != row.projection_hash:
            raise HTTPException(409, "完整研究公开投影与原冻结发布SHA不一致")
    elif row.status == "published":
        raise HTTPException(409, "已发布研究病例缺少原完整投影")
    return snapshot, projected


def _reader_permission(db, actor, scope_id, *, external_model=False):
    # Project ACL first, then every patient. No raw Case body is needed here.
    _, acl = authorize_project_acl(db, actor, scope_id)
    scope = acl["parent_binding"]["scope"]
    for patient_id in scope["payload"]["patient_ids"]:
        authorize_patient_research(db, actor, scope_id, patient_id, external_model=external_model)
    return scope


def _current(db, row, snapshot):
    # The frozen capture actor's exact grant belongs to the original binding;
    # the present reader is separately authorized and never impersonated.
    captured = capture_sources(db, SimpleNamespace(user_id=snapshot["created_by"]), snapshot["capture"]["request"], locking=True)
    if captured["collection_digest"] != row.collection_digest:
        raise HTTPException(409, "完整研究来源或任一授权/成员已变化，请重新捕获而非保留旧赢家")
    return captured


def preview_input(db, user, values):
    request = _typed(CaptureRequest, values)
    captured = capture_sources(db, user, ScopeReference.model_validate(request.model_dump(exclude={"criteria"})), locking=True)
    from app.ai.research_cohort_evaluator import evaluate_criteria

    return {
        "schema_version": "research_cohort_preview_v1",
        "request": request.model_dump(),
        "capture": captured,
        "evaluation": evaluate_criteria(captured, request.criteria),
        "expected_collection_digest": captured["collection_digest"],
        "can_create": True,
        "no_business_write": True,
    }


def _finish(db, actor, row, action, *, require_current):
    from app.ai.models import AIAuditEvent

    snapshot, _ = case_proof(row)
    detail = canonical_json({"case_id": row.case_id, "content_hash": row.content_hash, "governance_hash": governance_hash(row), "projection_hash": row.projection_hash})
    audit = AIAuditEvent(actor_id=actor.user_id, action=action, target=row.case_id, detail_json=detail)
    db.add(audit)
    db.flush()
    fresh = current_actor(db, actor)
    event = current_research_rows(db.query(AIAuditEvent).filter_by(event_id=audit.event_id), shared=True).one()
    checked = _row(db, row.case_id, locking=True)
    if event.actor_id != fresh.user_id or event.action != action or event.target != row.case_id or event.detail_json != detail or case_proof(checked)[0] != snapshot:
        raise HTTPException(409, "研究病例或具体审计回执同事务回读不一致")
    if require_current:
        _current(db, checked, snapshot)
        if action.endswith(".create"):
            _reader_permission(db, fresh, row.scope_id)
    db.commit()
    return case_current(db, fresh, row.case_id, audit_only=fresh.user_role == "super_admin")


def create_case(db, user, values):
    request = _typed(CaseCreate, values)
    try:
        actor = lock_research_write(db, user)
        preview = preview_input(db, actor, request.request)
        captured = preview["capture"]
        if captured["collection_digest"] != request.expected_collection_digest:
            raise HTTPException(409, "完整研究捕获集合已变化，未偷偷采用新原件或新患者")
        from app.ai.research_cohort_snapshot import make_snapshot

        snapshot = make_snapshot(str(uuid.uuid4()), actor.user_id, request.request, captured, request.basis_note)
        row = AIResearchCohortCase(
            case_id=snapshot["case_id"],
            scope_id=snapshot["scope_id"],
            schema_version=snapshot["schema_version"],
            snapshot_json=_bounded(snapshot, SNAPSHOT_BYTES),
            content_hash=hash_content(snapshot),
            collection_digest=snapshot["collection_digest"],
            scope_binding_hash=snapshot["scope_binding_hash"],
            member_manifest_hash=snapshot["member_manifest_hash"],
            projection_json=None,
            projection_hash=None,
            created_at=utcnow(),
            created_by=actor.user_id,
            status="draft",
            revision=1,
            reviewed_by=None,
            reviewed_at=None,
            review_basis_note="",
            revoked_by=None,
            revoked_at=None,
            revoke_reason="",
        )
        # Capture's server clock is the immutable original creation clock.
        import datetime as dt

        row.created_at = dt.datetime.strptime(snapshot["captured_at"], "%Y-%m-%dT%H:%M:%S.%fZ")
        db.add(row)
        db.flush()
        return _finish(db, actor, row, "research.case.create", require_current=True)
    except Exception:
        db.rollback()
        raise


def review_case(db, user, identifier, values, *, revoke=False):
    request = _typed(SourceRevoke if revoke else SourceReview, values)
    try:
        actor = lock_research_write(db, user, allowed_roles={"super_admin"})
        header = _row(db, identifier, body=False)
        lock_research_write(db, actor, scope_ids=(header.scope_id,))
        # This is internal technical whole-byte verification, never a raw API
        # grant. Publication additionally checks all original permissions/current.
        row = _row(db, identifier, locking=True)
        snapshot, _ = case_proof(row)
        if row.revision != request.expected_revision or row.status not in ({"draft", "published"} if revoke else {"draft"}):
            raise HTTPException(409, "研究病例原状态/CAS已变化")
        publishing = not revoke and request.decision == "publish"
        if publishing:
            if snapshot["recipe"] != current_recipe():
                raise HTTPException(409, "新发布须使用当前研究规则版本")
            _current(db, row, snapshot)
        if revoke:
            update = dict(status="revoked", revision=row.revision + 1, revoked_by=actor.user_id, revoked_at=utcnow(), revoke_reason=request.basis_note)
        else:
            update = dict(status="published" if publishing else "rejected", revision=2, reviewed_by=actor.user_id, reviewed_at=utcnow(), review_basis_note=request.basis_note)
        if db.query(AIResearchCohortCase).filter_by(case_id=identifier, revision=request.expected_revision, status=row.status).update(update, synchronize_session=False) != 1:
            raise HTTPException(409, "研究病例CAS未命中")
        row = _row(db, identifier, locking=True)
        if publishing:
            # Publication hash does not include projection_hash, so no cycle.
            projection = project_snapshot(snapshot, governance_hash(row))
            row.projection_json, row.projection_hash = _bounded(projection, SNAPSHOT_BYTES), hash_content(projection)
            db.flush()
        return _finish(db, actor, row, "research.case.revoke" if revoke else "research.case.review", require_current=publishing)
    except Exception:
        db.rollback()
        raise


def case_current(db, user, identifier, *, audit_only=False):
    TypeAdapter(UUID).validate_python(identifier, strict=True)
    actor = lock_research_write(db, user)
    if audit_only and actor.user_role != "super_admin":
        raise HTTPException(403, "技术冻结审计仅限当前超级管理员，不代授患者正文")
    header = _row(db, identifier, body=False)
    permitted = True
    try:
        _reader_permission(db, actor, header.scope_id)
    except HTTPException as exc:
        if exc.status_code not in {403, 404}:
            raise
        permitted = False
    if not permitted and actor.user_role != "super_admin" and header.created_by != actor.user_id:
        # A project member may read technical metadata, but a stranger may not
        # discover a foreign project's frozen manifest by guessing a UUID.
        authorize_project_acl(db, actor, header.scope_id)
    result = {
        **metadata(header),
        "governance_hash": governance_hash(header),
        "snapshot": None,
        "public_source": None,
        "local_resolution": None,
        "safe_manifest": None,
        "protected_original_integrity_verified": False,
        "parent_current": False,
        "eligible": False,
        "exclusion_reasons": [],
        "can_record": False,
        "can_review": False,
        "can_revoke": False,
        "audit_only": audit_only,
        "access_basis": "current_project_acl_and_each_patient_permission_even_super",
        "authorization_limitation": "technical_audit_does_not_restore_withdrawn_clinical_body",
    }
    # Own technical audit may verify protected bytes internally, but must never
    # return them (or selected clinical quotations) after patient access loss.
    if not permitted and not audit_only:
        result["exclusion_reasons"] = ["current_research_permission_missing"]
        return result
    row = _row(db, identifier)
    snapshot, projected = case_proof(row)
    result["protected_original_integrity_verified"] = True
    result["safe_manifest"] = [
        {"family": r["family"], "record_token": opaque(snapshot, "record", [r["family"], r["record_id"]]), "original_hash": opaque(snapshot, "original_hash", r["content_hash"])}
        for r in snapshot["capture"]["member_manifest"]
    ]
    if not permitted:
        result["exclusion_reasons"] = ["current_research_permission_missing"]
        result["can_revoke"] = row.status in {"draft", "published"}
        return result
    current = True
    try:
        _current(db, row, snapshot)
    except HTTPException as exc:
        if exc.status_code not in {403, 404, 409}:
            raise
        current = False
    result["parent_current"] = current
    if row.status != "published":
        result["exclusion_reasons"].append("case_not_published")
    if not current:
        result["exclusion_reasons"].append("original_sources_or_permissions_not_current")
    result["eligible"] = row.status == "published" and current
    result["can_review"] = actor.user_role == "super_admin" and row.status == "draft" and current
    result["can_revoke"] = actor.user_role == "super_admin" and row.status in {"draft", "published"}
    if current and row.status in {"draft", "published"} or audit_only:
        result["snapshot"], result["public_source"] = snapshot, projected
        result["local_resolution"] = {
            "patients": [{"patient_token": opaque(snapshot, "patient", patient_id), "patient_id": patient_id} for patient_id in snapshot["capture"]["scope_original"]["payload"]["patient_ids"]]
        }
    return result


def authorize_case(db, user, identifier, *, external_model=False, execution=False):
    row = case_current(db, user, identifier)
    if not row["eligible"] or row["snapshot"] is None or row["public_source"] is None:
        raise HTTPException(409, "研究病例未发布、来源已变化或当前逐患者权限不足")
    _reader_permission(db, user, row["scope_id"], external_model=external_model)
    if execution and row["snapshot"]["recipe"] != current_recipe():
        raise HTTPException(409, "新执行须使用当前确定研究谓词规则")
    return row, row["snapshot"], row["public_source"]


def frozen_case_proof(db, user, identifier):
    # No user=None raw escape hatch. Callers get the same loss-aware contract.
    return case_current(db, user, identifier, audit_only=True)


def binding_for(row, source):
    return {
        "case_id": row["case_id"],
        "scope_id": row["scope_id"],
        "content_hash": row["content_hash"],
        "governance_hash": source["governance_hash"],
        "projection_hash": row["projection_hash"],
        "collection_digest": row["collection_digest"],
        "scope_binding_hash": row["scope_binding_hash"],
        "member_manifest_hash": row["member_manifest_hash"],
        "public_manifest_hash": source["member_manifest_hash"],
        "scope_token": source["scope_token"],
        "source_id": source["source_id"],
        "rule_id": RULE_ID,
    }


from app.ai.research_cohort_snapshot import RULE_ID  # noqa: E402
