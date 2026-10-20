"""Scoped immutable planning declarations with independent Super review and CAS."""

import json
import uuid

from fastapi import HTTPException
from pydantic import ValidationError

from app.ai import governance
from app.ai import roster_facts as facts
from app.ai.roster_contract import RosterSource, canonical_json, hash_content
from app.ai.roster_plan_input import PlanRequest, capture_input, current_collection, project_source, validate_planning_period, verify_snapshot
from app.ai.roster_plan_models import PLAN_BYTES, AIRosterPlan


class PlanCreate(facts.StrictInput):
    request: PlanRequest
    expected_collection_digest: facts.HashText


class PlanReview(facts.SourceReview):
    pass


class PlanRevoke(facts.SourceRevoke):
    pass


def bounded_json(value):
    serialized = canonical_json(value)
    if not 0 < len(serialized.encode("utf-8")) <= PLAN_BYTES:
        raise HTTPException(422, "完整排班声明或投影超过8MiB；未截断或保存")
    return serialized


def plan_row(db, plan_id, *, locking=False):
    try:
        facts.canonical_id(plan_id)
    except (ValueError, TypeError, AttributeError) as exc:
        raise HTTPException(422, "排班计划标识须为规范UUID") from exc
    query = db.query(AIRosterPlan).filter_by(plan_id=plan_id).populate_existing()
    row = (query.with_for_update() if locking else query).one_or_none()
    if row is None:
        raise HTTPException(404, "排班计划不存在")
    return row


def published_governance(row):
    """Retain the exact original publication anchor after later revocation."""
    state = facts.governance_fields(row)
    return {**state, "status": "published", "revision": 2, "revoked_by": None, "revoked_at": None, "revoke_reason": ""}


def metadata(row):
    state = facts.governance_fields(row)
    return {
        "plan_id": row.plan_id,
        "department_id": row.department_id,
        "schema_version": row.schema_version,
        "as_of": facts.utc_text(row.as_of),
        "created_at": facts.utc_text(row.created_at),
        "created_by": row.created_by,
        "content_hash": row.content_hash,
        "collection_digest": row.collection_digest,
        "projection_hash": row.projection_hash,
        "source_id": f"roster_problem:{row.plan_id}:{row.content_hash[:12]}",
        **state,
        "governance_hash": hash_content(state),
    }


def plan_proof(row):
    """Own-byte integrity is mandatory even for Super frozen audit access."""
    try:
        facts.canonical_id(row.plan_id)
        if row.schema_version != "roster_plan_private_v1" or type(row.department_id) is not int or row.department_id < 1 or type(row.created_by) is not int or row.created_by < 1:
            raise ValueError("Invalid original plan identity")
        snapshot = json.loads(row.snapshot_json)
        if bounded_json(snapshot) != row.snapshot_json or hash_content(snapshot) != row.content_hash:
            raise ValueError("Complete private body differs")
        verify_snapshot(snapshot)
        expected = {
            "schema_version": row.schema_version,
            "problem_id": row.plan_id,
            "department_id": row.department_id,
            "created_by": row.created_by,
            "as_of": facts.utc_text(row.as_of),
            "captured_at": facts.utc_text(row.created_at),
            "collection_digest": row.collection_digest,
        }
        if any(snapshot[key] != value for key, value in expected.items()) or row.as_of > row.created_at:
            raise ValueError("Immutable table binding differs")
        if type(row.revision) is not int:
            raise ValueError("Invalid governance revision")
        reviewed = row.reviewed_by is not None and row.reviewed_at is not None
        if reviewed:
            if type(row.reviewed_by) is not int or row.reviewed_by < 1 or row.reviewed_at < row.created_at:
                raise ValueError("Invalid review provenance")
            PlanReview(expected_revision=1, expected_content_hash=row.content_hash, decision="publish", review_basis_note=row.review_basis_note)
        elif row.reviewed_by is not None or row.reviewed_at is not None or row.review_basis_note != "":
            raise ValueError("Partial review provenance")
        if row.status == "draft":
            if row.revision != 1 or reviewed:
                raise ValueError("Invalid original draft")
        elif row.status in {"published", "rejected"}:
            if row.revision != 2 or not reviewed:
                raise ValueError("Invalid original review")
        elif row.status == "revoked":
            if row.revision != (3 if reviewed else 2) or type(row.revoked_by) is not int or row.revoked_by < 1 or row.revoked_at is None:
                raise ValueError("Invalid revocation provenance")
            PlanRevoke(expected_revision=row.revision - 1, reason=row.revoke_reason)
            if row.revoked_at < (row.reviewed_at if reviewed else row.created_at):
                raise ValueError("Invalid revocation clock")
        else:
            raise ValueError("Unknown plan status")
        if row.status != "revoked" and (row.revoked_by is not None or row.revoked_at is not None or row.revoke_reason != ""):
            raise ValueError("Unbound revocation metadata")
        has_publication = row.status == "published" or row.status == "revoked" and reviewed
        source = None
        if has_publication:
            source = project_source(snapshot, hash_content(published_governance(row)), validate_current_recipe=False)
            if bounded_json(source) != row.projection_json or hash_content(source) != row.projection_hash:
                raise ValueError("Original published projection differs")
        elif row.projection_json is not None or row.projection_hash is not None:
            raise ValueError("Projection without original publication")
        return snapshot, source
    except (HTTPException, ValueError, TypeError, AttributeError, KeyError, OverflowError, RecursionError, UnicodeError, ValidationError) as exc:
        raise HTTPException(409, "排班计划的完整原件、治理、原时刻或投影哈希不一致") from exc


def _current(db, actor, row, *, locking=False):
    facts.roster_scope(db, actor, row.department_id, locking=locking)
    collection = current_collection(db, actor, row.department_id, locking=locking)
    if collection["collection_digest"] != row.collection_digest:
        raise HTTPException(409, "原人员完整集合或来源治理已经变化，请重新捕获并审核排班计划")


def authorize_plan(db, user, plan_id, *, execution=True, binding=None, locking=False):
    row = plan_row(db, plan_id, locking=locking)
    actor = facts.roster_scope(db, user, row.department_id, locking=locking)
    snapshot, source = plan_proof(row)
    _current(db, actor, row, locking=locking)
    if row.status != "published" or row.revision != 2 or source is None:
        raise HTTPException(409, "排班计划尚未发布或已经失效，不能执行新任务")
    if execution:
        validate_planning_period(PlanRequest.model_validate(snapshot["request"]))
        try:
            RosterSource.model_validate(source)
        except ValidationError as exc:
            raise HTTPException(409, "排班计划绑定的原算法或输入政策已改变，请重新捕获审核") from exc
    if binding is not None and (not isinstance(binding, dict) or any(binding.get(key) != value for key, value in binding_for(row, source).items())):
        raise HTTPException(409, "排班任务的完整原计划绑定已经变化")
    return row, snapshot, source


def binding_for(row, source):
    return {
        "plan_id": row.plan_id,
        "department_id": row.department_id,
        "revision": 2,
        "source_id": source["source_id"],
        "content_hash": row.content_hash,
        "problem_governance_hash": hash_content(published_governance(row)),
        "projection_hash": row.projection_hash,
        "scope_binding_hash": source["scope_binding_hash"],
        "manifest_digest": source["manifest_digest"],
        "collection_digest": row.collection_digest,
        "rule_id": source["rule_id"],
        "recipe_digest": source["recipe_digest"],
        "input_policy_digest": source["input_policy_digest"],
    }


def plan_current(db, user, plan_id, *, audit_only=False):
    row = plan_row(db, plan_id)
    actor = facts.current_actor(db, user)
    if audit_only and actor.user_role != "super_admin":
        raise HTTPException(403, "只有超级管理员可读取完整冻结排班审计")
    facts.roster_scope(db, actor, row.department_id, allow_missing=actor.user_role in {"admin", "super_admin"})
    snapshot, source = plan_proof(row)
    reasons = []
    try:
        _current(db, actor, row)
    except HTTPException as exc:
        if exc.status_code not in {403, 409, 422}:
            raise
        reasons.append("original_collection_changed")
    if row.status != "published":
        reasons.append("plan_" + row.status)
    visible = audit_only or not reasons or reasons == ["plan_draft"]
    run_reasons = list(reasons)
    if not run_reasons:
        try:
            validate_planning_period(PlanRequest.model_validate(snapshot["request"]))
            RosterSource.model_validate(source)
        except (HTTPException, ValidationError):
            run_reasons.append("planning_period_or_algorithm_changed")
    return {
        **metadata(row),
        "snapshot": snapshot if visible else None,
        "public_source": source if visible else None,
        "source_current": not any(reason == "original_collection_changed" for reason in reasons),
        "eligible": not run_reasons,
        "exclusion_reasons": run_reasons,
        "can_record": not any(reason == "original_collection_changed" for reason in reasons),
        "can_review": actor.user_role == "super_admin" and row.status == "draft" and "original_collection_changed" not in reasons,
        "can_revoke": row.status in {"draft", "published"} and (actor.user_role == "super_admin" or row.created_by == actor.user_id and "original_collection_changed" not in reasons),
        "review_basis_note": row.review_basis_note if visible else None,
        "revoke_reason": row.revoke_reason if visible else None,
        "audit_only": audit_only,
        "capacity_purpose": "declared_scenario_net_capacity_not_live_bookable_inventory",
    }


def create_plan(db, user, values):
    req = values if isinstance(values, PlanCreate) else PlanCreate.model_validate(values)
    actor = facts.roster_scope(db, user, req.request.department_id)
    plan_id = str(uuid.uuid4())
    snapshot = capture_input(db, actor, req.request, plan_id, expected_collection_digest=req.expected_collection_digest)
    serialized = bounded_json(snapshot)
    row = AIRosterPlan(
        plan_id=plan_id,
        department_id=req.request.department_id,
        schema_version="roster_plan_private_v1",
        as_of=facts.instant(snapshot["as_of"]).replace(tzinfo=None),
        created_at=facts.instant(snapshot["captured_at"]).replace(tzinfo=None),
        created_by=actor.user_id,
        snapshot_json=serialized,
        content_hash=hash_content(snapshot),
        collection_digest=snapshot["collection_digest"],
        projection_json=None,
        projection_hash=None,
        status="draft",
        revision=1,
        review_basis_note="",
        revoke_reason="",
    )
    db.add(row)
    db.flush()
    plan_proof(row)
    actor = facts.current_actor(db, actor, locking=True)
    _current(db, actor, row, locking=True)
    governance.audit(db, actor.user_id, "roster.plan.create", row.plan_id, {"content_hash": row.content_hash, "department_id": row.department_id, "collection_digest": row.collection_digest})
    return row


def review_plan(db, user, plan_id, values):
    req = values if isinstance(values, PlanReview) else PlanReview.model_validate(values)
    actor = facts.current_actor(db, user)
    if actor.user_role != "super_admin":
        raise HTTPException(403, "只有当前超级管理员可审核排班计划")
    row = plan_row(db, plan_id)
    snapshot, _ = plan_proof(row)
    if row.status != "draft" or row.revision != req.expected_revision or row.content_hash != req.expected_content_hash:
        raise HTTPException(409, "排班原声明或审核版本已变化")
    _current(db, actor, row)
    validate_planning_period(PlanRequest.model_validate(snapshot["request"]))
    now = max(facts.utcnow(), row.created_at)
    updates = {"status": "published" if req.decision == "publish" else "rejected", "revision": 2, "reviewed_by": actor.user_id, "reviewed_at": now, "review_basis_note": req.review_basis_note}
    if req.decision == "publish":
        state = {**facts.governance_fields(row), **updates, "reviewed_at": facts.utc_text(now)}
        source = project_source(snapshot, hash_content(state))
        updates.update(projection_json=bounded_json(source), projection_hash=hash_content(source))
    changed = db.query(AIRosterPlan).filter_by(plan_id=plan_id, status="draft", revision=req.expected_revision, content_hash=req.expected_content_hash).update(updates, synchronize_session=False)
    if changed != 1:
        raise HTTPException(409, "排班计划发生并发审核，本次未保存")
    row = plan_row(db, plan_id)
    plan_proof(row)
    actor = facts.current_actor(db, actor, locking=True)
    if actor.user_role != "super_admin":
        raise HTTPException(403, "当前身份已不再具备排班审核权限，本次未发布")
    _current(db, actor, row, locking=True)
    governance.audit(
        db,
        actor.user_id,
        "roster.plan." + req.decision,
        plan_id,
        {"revision": row.revision, "content_hash": row.content_hash, "projection_hash": row.projection_hash, "governance_hash": hash_content(facts.governance_fields(row))},
    )
    return row


def revoke_plan(db, user, plan_id, values):
    req = values if isinstance(values, PlanRevoke) else PlanRevoke.model_validate(values)
    row = plan_row(db, plan_id)
    actor = facts.roster_scope(db, user, row.department_id, allow_missing=user.user_role == "super_admin")
    plan_proof(row)
    if actor.user_role != "super_admin":
        _current(db, actor, row)
        if row.created_by != actor.user_id:
            raise HTTPException(403, "只有当前原记录人或超级管理员可撤销排班计划")
    if row.status not in {"draft", "published"} or row.revision != req.expected_revision:
        raise HTTPException(409, "排班计划已终结或治理版本已变化")
    now = max(facts.utcnow(), row.reviewed_at or row.created_at)
    changed = (
        db.query(AIRosterPlan)
        .filter_by(plan_id=plan_id, status=row.status, revision=req.expected_revision, content_hash=row.content_hash)
        .update({"status": "revoked", "revision": req.expected_revision + 1, "revoked_by": actor.user_id, "revoked_at": now, "revoke_reason": req.reason}, synchronize_session=False)
    )
    if changed != 1:
        raise HTTPException(409, "排班计划发生并发变更，本次未撤销")
    row = plan_row(db, plan_id)
    plan_proof(row)
    actor = facts.current_actor(db, actor, locking=True)
    if actor.user_role != "super_admin":
        _current(db, actor, row, locking=True)
        if row.created_by != actor.user_id:
            raise HTTPException(403, "当前身份已不具备撤销该原计划的权限")
    governance.audit(db, actor.user_id, "roster.plan.revoke", plan_id, {"revision": row.revision, "content_hash": row.content_hash, "governance_hash": hash_content(facts.governance_fields(row))})
    return row
