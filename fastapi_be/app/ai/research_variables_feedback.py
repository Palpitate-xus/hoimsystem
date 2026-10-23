"""Explicit current-source human feedback; no matrix or clinical write."""

from fastapi import HTTPException

from app.ai import research_variables_result_storage as results
from app.ai import research_variables_task_reader as reader
from app.ai.models import AIAuditEvent, AIFeedback
from app.ai.research_cohort_sources import utcnow
from app.ai.research_cohort_write_guard import current_research_rows
from app.ai.research_variables_task_contract import canonical
from app.ai.schemas import FeedbackWrite


def review_variable_result(db, user, identifier, value):
    try:
        request = value if isinstance(value, FeedbackWrite) else FeedbackWrite.model_validate(value)
        if request.outcome == "modified" and len(request.comment) < 3:
            raise HTTPException(422, "请明确记录人工修改说明，未更改原变量草稿")
        task = reader.load_task(db, user, identifier, exclusive=True)
        if task.run.status != "succeeded":
            raise HTTPException(409, "仅完整已接受结果可追加人工反馈")
        part = results.result_from_task(db, task)
        clock = utcnow().replace(microsecond=0)
        feedback = AIFeedback(run_id=identifier, reviewer_id=task.authority.actor.user_id, outcome=request.outcome, comment=request.comment, create_time=clock)
        db.add(feedback)
        db.flush()
        detail = {
            "schema_version": "research_variable_feedback_event_v1",
            "feedback_id": feedback.feedback_id,
            "create_event_id": task.artifact.create_event_id,
            "accept_audit_event_id": part["reference"]["accept_audit_event_id"],
            "result_hash": part["reference"]["result_hash"],
            "binding_hash": task.artifact.binding_hash,
            "request_authorization_hash": task.artifact.request_authorization_hash,
            "outcome": request.outcome,
            "comment": request.comment,
            "automatic_clinical_write": False,
            "automatic_export": False,
        }
        event = AIAuditEvent(actor_id=task.authority.actor.user_id, action="research_variable_run.feedback", target=identifier, detail_json=canonical(detail, 65535), create_time=clock)
        db.add(event)
        db.flush()
        expected_feedback = {str(c.name): getattr(feedback, str(c.name)) for c in AIFeedback.__table__.columns}
        expected_event = {str(c.name): getattr(event, str(c.name)) for c in AIAuditEvent.__table__.columns}
        # Repeat original purposes before any new Task/result BODY read. SQL
        # source/role triggers roll back feedback and their own side effects.
        current = reader.load_task(db, user, identifier, exclusive=True)
        actual_part = results.result_from_task(db, current)
        if actual_part != part:
            raise HTTPException(409, "人工复核期间原完整草稿或具体接受PK已变化")
        actual_feedback = current_research_rows(db.query(AIFeedback).filter_by(feedback_id=feedback.feedback_id), shared=True).one_or_none()
        actual_event = current_research_rows(db.query(AIAuditEvent).filter_by(event_id=event.event_id), shared=True).one_or_none()
        if (
            actual_feedback is None
            or actual_event is None
            or {str(c.name): getattr(actual_feedback, str(c.name)) for c in AIFeedback.__table__.columns} != expected_feedback
            or {str(c.name): getattr(actual_event, str(c.name)) for c in AIAuditEvent.__table__.columns} != expected_event
        ):
            raise HTTPException(409, "本次具体反馈或审计实际写入不一致，整事务未接受")
        db.commit()
        return {"feedback_id": feedback.feedback_id, "audit_event_id": event.event_id, "automatic_clinical_write": False, "automatic_export": False}
    except Exception:
        db.rollback()
        raise
