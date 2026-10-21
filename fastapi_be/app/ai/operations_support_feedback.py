"""Append human review bound to the actual accepted, currently readable draft."""

from fastapi import HTTPException

from app.ai import operations_support_attempts as attempts
from app.ai import operations_support_contract as c
from app.ai import operations_support_registry as registry
from app.ai import operations_support_result_storage as results
from app.ai import operations_support_storage as storage
from app.ai.models import AIFeedback
from app.ai.operations_support_write_guard import current_rows, lock_operations_write

ACTION = "operations.task.feedback"


def stage_feedback(db, user, identifier, request):
    """Caller owns commit/rollback; triggers must preserve the complete binding."""
    actor = lock_operations_write(db, user)
    epoch = actor.user_id, actor.user_role, actor.token_invalid_before
    result = results.load_result(db, actor, identifier)
    header = storage.run_header(db, identifier)
    artifact = attempts.phase_header(db, identifier)
    if request.outcome == "modified" and len(request.comment) < 3:
        raise HTTPException(422, "请说明修改内容")
    when = registry.utcnow()
    item = AIFeedback(run_id=identifier, reviewer_id=actor.user_id, outcome=request.outcome, comment=request.comment, create_time=when.replace(microsecond=0))
    db.add(item)
    db.flush()
    key = registry.identifier(item.feedback_id)
    detail = {
        "schema_version": "operations_support_feedback_audit_v1",
        "run_id": identifier,
        "feedback_id": key,
        "reviewer_id": actor.user_id,
        "outcome": request.outcome,
        "comment_sha256": registry.raw_sha(request.comment),
        "comment_utf8_bytes": len(request.comment.encode()),
        "result_sha256": c.content_hash(result),
        "source_binding_hash": artifact["source_binding_hash"],
        "instructions_digest": artifact["instructions_digest"],
        "usage_event_id": artifact["usage_event_id"],
        "recorded_at": registry.utc_text(when),
        "meaning": "human_review_of_unverified_operations_draft_not_environment_verification",
    }
    event_id = registry.audit_event(db, actor.user_id, ACTION, identifier, detail, when)
    # Recheck current authority before any protected post-trigger readback.
    current = lock_operations_write(db, actor)
    if (current.user_id, current.user_role, current.token_invalid_before) != epoch:
        raise HTTPException(403, "运维复核者的当前角色或登录授权已变化")
    if results.load_result(db, current, identifier) != result or storage.run_header(db, identifier) != header or attempts.phase_header(db, identifier) != artifact:
        raise HTTPException(409, "运维复核后原任务、资料或实际接受结果绑定已变化")
    with db.no_autoflush:
        saved = current_rows(db.query(AIFeedback).filter_by(feedback_id=key), shared=True).one_or_none()
    expected = dict(feedback_id=key, run_id=identifier, reviewer_id=epoch[0], outcome=request.outcome, comment=request.comment, create_time=when.replace(microsecond=0))
    if saved is None or {column.name: getattr(saved, column.name) for column in AIFeedback.__table__.columns} != expected:
        raise HTTPException(409, "实际运维人工复核记录读回不一致")
    registry.verify_event(db, event_id, epoch[0], ACTION, identifier, detail, when)
    return {"feedback_id": key}
