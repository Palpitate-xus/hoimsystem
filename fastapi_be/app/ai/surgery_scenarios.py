"""Frozen surgery scenarios, current complete authority and explicit Super review."""

import datetime
import json
import uuid
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from pydantic import ValidationError

from app.ai import governance
from app.ai import surgery_collection as collection
from app.ai import surgery_facts as facts
from app.ai.surgery_context import binding_for
from app.ai.surgery_contract import SurgerySource, hash_content, identity
from app.ai.surgery_scenario_input import ScenarioCreate
from app.ai.surgery_scenario_models import AISurgeryScenario
from app.ai.surgery_snapshot import bounded_json, build_snapshot, capture_request, local_resolution, project_snapshot, project_source, verify_snapshot


def scenario_row(db, scenario_id, *, locking=False):
    try:
        identity(scenario_id)
    except (ValueError, TypeError, AttributeError) as exc:
        raise HTTPException(422, "手术场景标识须为规范UUID") from exc
    row = facts.current_query(db.query(AISurgeryScenario).filter_by(scenario_id=scenario_id), locking=locking).one_or_none()
    if row is None:
        raise HTTPException(404, "手术排程场景不存在")
    return row


def published_governance(row):
    return {**facts.governance_fields(row), "status": "published", "revision": 2, "revoked_by": None, "revoked_at": None, "revoke_reason": ""}


def metadata(row):
    state = facts.governance_fields(row)
    return {
        "scenario_id": row.scenario_id,
        "pool_id": row.pool_id,
        "department_id": row.department_id,
        "schema_version": row.schema_version,
        "as_of": facts.utc_text(row.as_of),
        "created_at": facts.utc_text(row.created_at),
        "created_by": row.created_by,
        "content_hash": row.content_hash,
        "collection_digest": row.collection_digest,
        "projection_hash": row.projection_hash,
        "source_id": f"surgery_scenario:{row.scenario_id}:{row.content_hash[:12]}",
        **state,
        "governance_hash": hash_content(state),
    }


def scenario_proof(row):
    """Check immutable bytes even for Super audit; grant no current SQL access."""
    try:
        snapshot = json.loads(row.snapshot_json)
        if bounded_json(snapshot) != row.snapshot_json or hash_content(snapshot) != row.content_hash:
            raise ValueError("Complete private scenario bytes differ")
        verify_snapshot(snapshot)
        expected = {
            "schema_version": row.schema_version,
            "scenario_id": row.scenario_id,
            "pool_id": row.pool_id,
            "department_id": row.department_id,
            "created_by": row.created_by,
            "as_of": facts.utc_text(row.as_of),
            "captured_at": facts.utc_text(row.created_at),
            "collection_digest": row.collection_digest,
        }
        if any(type(snapshot[key]) is not type(value) or snapshot[key] != value for key, value in expected.items()) or row.as_of > row.created_at or type(row.revision) is not int:
            raise ValueError("Immutable scenario table identity differs")
        reviewed = row.reviewed_by is not None and row.reviewed_at is not None
        if reviewed:
            if type(row.reviewed_by) is not int or row.reviewed_by < 1 or row.reviewed_at < row.created_at:
                raise ValueError("Invalid actual review provenance")
            facts.SourceReview(expected_revision=1, expected_content_hash=row.content_hash, decision="publish", basis_note=row.review_basis_note)
        elif row.reviewed_by is not None or row.reviewed_at is not None or row.review_basis_note != "":
            raise ValueError("Partial scenario review")
        if row.status == "draft":
            if row.revision != 1 or reviewed:
                raise ValueError("Invalid draft revision")
        elif row.status in {"published", "rejected"}:
            if row.revision != 2 or not reviewed:
                raise ValueError("Invalid review revision")
        elif row.status == "revoked":
            if row.revision != (3 if reviewed else 2) or type(row.revoked_by) is not int or row.revoked_by < 1 or row.revoked_at is None:
                raise ValueError("Invalid revocation provenance")
            facts.SourceRevoke(expected_revision=row.revision - 1, expected_content_hash=row.content_hash, basis_note=row.revoke_reason)
            if row.revoked_at < (row.reviewed_at if reviewed else row.created_at):
                raise ValueError("Backdated revocation")
        else:
            raise ValueError("Unknown original scenario status")
        if row.status != "revoked" and (row.revoked_by is not None or row.revoked_at is not None or row.revoke_reason != ""):
            raise ValueError("Unbound revocation fields")
        source = None
        if row.status == "published" or row.status == "revoked" and reviewed:
            source = project_source(snapshot, hash_content(published_governance(row)), validate_current_recipe=False)
            if bounded_json(source) != row.projection_json or hash_content(source) != row.projection_hash:
                raise ValueError("Complete original published projection differs")
        elif row.projection_json is not None or row.projection_hash is not None:
            raise ValueError("A scenario without publication cannot have a native projection")
        return snapshot, source
    except (ValueError, TypeError, KeyError, AttributeError, UnicodeError, OverflowError, RecursionError, ValidationError) as exc:
        raise HTTPException(409, "手术场景完整原件、治理、时刻或公开投影不一致") from exc


def validate_planning_time(snapshot):
    request = ScenarioCreate.model_validate(snapshot["request"])
    now = facts.utcnow().replace(tzinfo=datetime.UTC)
    local_today = now.astimezone(ZoneInfo(request.period.business_timezone)).date()
    if datetime.date.fromisoformat(request.period.date_from) < local_today or any(start.start_at < facts.utc_text(now) for case in request.cases for start in case.starts):
        raise HTTPException(409, "原场景日期或显式候选开始时刻已经过去，请重新捕获完整场景并审核")
    verify_snapshot(snapshot, validate_current_recipe=True)


def _current(db, user, row, snapshot, *, locking=False):
    actual = collection.current_collection(db, user, capture_request(snapshot["request"]), locking=locking)
    if actual["collection_digest"] != row.collection_digest:
        raise HTTPException(409, "实际病例、人员、物理资源、相关来源或治理已变化，请重新捕获并逐件审核")
    return actual


def authorize_scenario(db, user, scenario_id, *, binding=None, locking=False, execution=True):
    if locking:
        with db.no_autoflush:
            facts.lock_write_gate(db)
    actor = facts.current_actor(db, user, locking=locking)
    row = scenario_row(db, scenario_id, locking=locking)
    facts.pool_scope(db, actor, row.pool_id, locking=locking)
    snapshot, source = scenario_proof(row)
    _current(db, actor, row, snapshot, locking=locking)
    if row.status != "published" or row.revision != 2 or source is None:
        raise HTTPException(409, "场景尚未发布、已被拒绝或撤销，不能执行新任务")
    if execution:
        try:
            validate_planning_time(snapshot)
            SurgerySource.model_validate(source)
        except (ValidationError, ValueError) as exc:
            raise HTTPException(409, "场景原规则、输入政策或规划时刻已失效，请重新捕获审核") from exc
    if binding is not None and binding != binding_for(source, pool_id=row.pool_id, department_id=row.department_id):
        raise HTTPException(409, "手术任务的完整原场景绑定已经变化")
    return row, snapshot, source


def scenario_current(db, user, scenario_id, *, audit_only=False):
    actor = facts.current_actor(db, user)
    row = scenario_row(db, scenario_id)
    if audit_only and actor.user_role != "super_admin":
        raise HTTPException(403, "只有当前超级管理员可读取冻结场景完整审计")
    if not (audit_only and actor.user_role == "super_admin"):
        facts.pool_scope(db, actor, row.pool_id, require_published=False)
    snapshot, source = scenario_proof(row)
    reasons = []
    try:
        _current(db, actor, row, snapshot)
    except HTTPException as exc:
        if exc.status_code not in {403, 404, 409, 422}:
            raise
        reasons.append("original_collection_changed")
    if row.status != "published":
        reasons.append("scenario_" + row.status)
    visible = audit_only or not reasons or reasons == ["scenario_draft"]
    run_reasons = list(reasons)
    if not run_reasons:
        try:
            validate_planning_time(snapshot)
            SurgerySource.model_validate(source)
        except (HTTPException, ValidationError, ValueError):
            run_reasons.append("scenario_period_or_algorithm_changed")
    return {
        **metadata(row),
        "snapshot": snapshot if visible else None,
        "public_source": source if visible else None,
        "local_resolution": local_resolution(snapshot) if visible else None,
        "projection_issues": project_snapshot(snapshot, source["governance_hash"] if source is not None else "0" * 64, validate_current_recipe=False)["issues"] if visible else [],
        "source_current": "original_collection_changed" not in reasons,
        "eligible": not run_reasons,
        "exclusion_reasons": run_reasons,
        "can_review": actor.user_role == "super_admin" and row.status == "draft" and "original_collection_changed" not in reasons,
        "can_revoke": row.status in {"draft", "published"} and (actor.user_role == "super_admin" or row.created_by == actor.user_id and "original_collection_changed" not in reasons),
        "review_basis_note": row.review_basis_note if visible else None,
        "revoke_reason": row.revoke_reason if visible else None,
        "audit_only": audit_only,
        "candidate_only": True,
        "automatic_booking": False,
    }


def _postcheck(db, actor, row, snapshot, *, require_super=False, require_creator=False, require_current=True):
    db.flush()
    actor = facts.current_actor(db, actor, locking=True)
    if require_super and actor.user_role != "super_admin":
        raise HTTPException(403, "当前身份已不具备完整场景审核权限，本次未保存")
    if require_creator and actor.user_role != "super_admin" and row.created_by != actor.user_id:
        raise HTTPException(403, "当前身份已不具备撤销原场景的权限")
    # Role changes during audit must switch a former Super back to the full
    # ordinary current-care policy, including when that account is the creator.
    current_required = require_current or actor.user_role != "super_admin"
    if current_required:
        facts.pool_scope(db, actor, row.pool_id, locking=True)
        _current(db, actor, row, snapshot, locking=True)
    return actor


def create_scenario(db, user, values):
    request = ScenarioCreate.model_validate(values.model_dump(mode="json") if isinstance(values, ScenarioCreate) else values)
    with db.no_autoflush:
        facts.lock_write_gate(db)
    actor = facts.current_actor(db, user, locking=True)
    captured = collection.capture_input(db, actor, capture_request(request), locking=True)
    try:
        snapshot = build_snapshot(request, captured, scenario_id=str(uuid.uuid4()), created_by=actor.user_id)
        # Check the whole declared domain before saving a draft, without publishing it.
        project_snapshot(snapshot, "0" * 64)
    except (ValueError, KeyError, TypeError, ValidationError) as exc:
        raise HTTPException(409, "场景声明、逐件审核或完整原件已变化，未冻结不完整声明") from exc
    row = AISurgeryScenario(
        scenario_id=snapshot["scenario_id"],
        pool_id=snapshot["pool_id"],
        department_id=snapshot["department_id"],
        schema_version=snapshot["schema_version"],
        as_of=datetime.datetime.fromisoformat(snapshot["as_of"].replace("Z", "+00:00")).replace(tzinfo=None),
        created_at=datetime.datetime.fromisoformat(snapshot["captured_at"].replace("Z", "+00:00")).replace(tzinfo=None),
        created_by=actor.user_id,
        snapshot_json=bounded_json(snapshot),
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
    scenario_proof(row)
    governance.audit(db, actor.user_id, "surgery.scenario.create", row.scenario_id, {"content_hash": row.content_hash, "collection_digest": row.collection_digest, "department_id": row.department_id})
    _postcheck(db, actor, row, snapshot)
    return row


def review_scenario(db, user, scenario_id, values):
    request = facts.SourceReview.model_validate(values.model_dump(mode="json") if isinstance(values, facts.SourceReview) else values)
    with db.no_autoflush:
        facts.lock_write_gate(db)
    actor = facts.current_actor(db, user, locking=True)
    if actor.user_role != "super_admin":
        raise HTTPException(403, "只有当前超级管理员可审核完整排程场景")
    row = scenario_row(db, scenario_id, locking=True)
    snapshot, _ = scenario_proof(row)
    facts.pool_scope(db, actor, row.pool_id, locking=True)
    _current(db, actor, row, snapshot, locking=True)
    if row.status != "draft" or row.revision != request.expected_revision or row.content_hash != request.expected_content_hash:
        raise HTTPException(409, "完整场景或原审核版本已变化")
    if request.decision == "publish":
        validate_planning_time(snapshot)
    now = facts.utcnow()
    if now < row.created_at:
        raise HTTPException(409, "审核服务器时刻早于原场景捕获时刻")
    updates = {"status": "published" if request.decision == "publish" else "rejected", "revision": 2, "reviewed_by": actor.user_id, "reviewed_at": now, "review_basis_note": request.basis_note}
    if request.decision == "publish":
        state = {**facts.governance_fields(row), **updates, "reviewed_at": facts.utc_text(now)}
        source = project_source(snapshot, hash_content(state))
        updates.update(projection_json=bounded_json(source), projection_hash=hash_content(source))
    changed = (
        db.query(AISurgeryScenario)
        .filter_by(scenario_id=scenario_id, status="draft", revision=request.expected_revision, content_hash=request.expected_content_hash)
        .update(updates, synchronize_session=False)
    )
    if changed != 1:
        raise HTTPException(409, "场景发生并发审核，本次未保存")
    row = scenario_row(db, scenario_id, locking=True)
    scenario_proof(row)
    governance.audit(
        db,
        actor.user_id,
        "surgery.scenario." + request.decision,
        scenario_id,
        {"content_hash": row.content_hash, "projection_hash": row.projection_hash, "governance_hash": hash_content(facts.governance_fields(row))},
    )
    _postcheck(db, actor, row, snapshot, require_super=True)
    return row


def revoke_scenario(db, user, scenario_id, values):
    request = facts.SourceRevoke.model_validate(values.model_dump(mode="json") if isinstance(values, facts.SourceRevoke) else values)
    with db.no_autoflush:
        facts.lock_write_gate(db)
    actor = facts.current_actor(db, user, locking=True)
    row = scenario_row(db, scenario_id, locking=True)
    snapshot, _ = scenario_proof(row)
    if actor.user_role != "super_admin":
        facts.pool_scope(db, actor, row.pool_id, locking=True)
        _current(db, actor, row, snapshot, locking=True)
        if row.created_by != actor.user_id:
            raise HTTPException(403, "只有当前原记录人或超级管理员可撤销完整场景")
    if row.status not in {"draft", "published"} or row.revision != request.expected_revision or row.content_hash != request.expected_content_hash:
        raise HTTPException(409, "场景已终结或完整原件、治理版本已变化")
    now = facts.utcnow()
    if now < (row.reviewed_at or row.created_at):
        raise HTTPException(409, "撤销服务器时刻早于原捕获或审核时刻")
    changed = (
        db.query(AISurgeryScenario)
        .filter_by(scenario_id=scenario_id, status=row.status, revision=request.expected_revision, content_hash=request.expected_content_hash)
        .update(
            {"status": "revoked", "revision": request.expected_revision + 1, "revoked_by": actor.user_id, "revoked_at": now, "revoke_reason": request.basis_note},
            synchronize_session=False,
        )
    )
    if changed != 1:
        raise HTTPException(409, "场景发生并发变更，本次未撤销")
    row = scenario_row(db, scenario_id, locking=True)
    scenario_proof(row)
    governance.audit(
        db, actor.user_id, "surgery.scenario.revoke", scenario_id, {"content_hash": row.content_hash, "revision": row.revision, "governance_hash": hash_content(facts.governance_fields(row))}
    )
    _postcheck(db, actor, row, snapshot, require_creator=True, require_current=actor.user_role != "super_admin")
    return row
