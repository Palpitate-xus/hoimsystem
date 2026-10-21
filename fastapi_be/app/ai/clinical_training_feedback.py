"""Append human review bound to the actual accepted, currently readable draft."""

from fastapi import HTTPException

from app.ai import clinical_training_attempts as attempts
from app.ai import clinical_training_contract as c
from app.ai import clinical_training_receipts as receipts
from app.ai import clinical_training_registry as registry
from app.ai import clinical_training_result_storage as results
from app.ai import clinical_training_storage as storage
from app.ai.clinical_training_write_guard import current_rows, lock_training_write
from app.ai.models import AIFeedback

ACTION = "training.task.feedback"


def stage_feedback(db, user, identifier, request):
    """Caller owns commit/rollback; triggers must preserve the complete binding."""
    actor = lock_training_write(db, user)
    epoch = actor.user_id, actor.user_role, actor.token_invalid_before
    result = results.load_result(db, actor, identifier)
    header = storage.run_header(db, identifier)
    artifact = attempts.phase_header(db, identifier)
    actual = attempts.technical_header(db, identifier)
    accepted = receipts._accepted_header(db, actual, receipts.read_receipt(db, actual))
    if request.outcome == "modified" and len(request.comment) < 3:
        raise HTTPException(422, "请说明修改内容")
    when = registry.utcnow()
    item = AIFeedback(run_id=identifier, reviewer_id=actor.user_id, outcome=request.outcome, comment=request.comment, create_time=when.replace(microsecond=0))
    db.add(item)
    db.flush()
    key = registry.identifier(item.feedback_id)
    detail = {
        "schema_version": "clinical_training_feedback_audit_v1",
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
        "accept_audit_event_id": accepted["accept_audit_event_id"],
        "grade_policy": "server_score_unchanged",
        "recorded_at": registry.references.utc_text(when),
        "meaning": "human_review_of_educational_feedback_draft_not_regrading_or_competence_validation",
    }
    event_id = registry.audit_event(db, actor.user_id, ACTION, identifier, detail, when)
    # Recheck current authority before any protected post-trigger readback.
    current = lock_training_write(db, actor)
    if (current.user_id, current.user_role, current.token_invalid_before) != epoch:
        raise HTTPException(403, "培训复核者的当前角色或登录授权已变化")
    if results.load_result(db, current, identifier) != result or storage.run_header(db, identifier) != header or attempts.phase_header(db, identifier) != artifact:
        raise HTTPException(409, "培训复核后原任务、资料或实际接受结果绑定已变化")
    with db.no_autoflush:
        saved = current_rows(db.query(AIFeedback).filter_by(feedback_id=key), shared=True).one_or_none()
    expected = dict(feedback_id=key, run_id=identifier, reviewer_id=epoch[0], outcome=request.outcome, comment=request.comment, create_time=when.replace(microsecond=0))
    if saved is None or {column.name: getattr(saved, column.name) for column in AIFeedback.__table__.columns} != expected:
        raise HTTPException(409, "实际培训人工复核记录读回不一致")
    registry.verify_event(db, event_id, epoch[0], ACTION, identifier, detail, when)
    return {"feedback_id": key}
