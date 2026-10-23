"""Append manual feedback after full current Source and accepted-result proof."""

import uuid

from fastapi import HTTPException

from app.ai import rca_evidence_grants as grants
from app.ai import rca_evidence_result_storage as results
from app.ai import rca_evidence_storage as storage
from app.ai.models import AIFeedback
from app.ai.rca_evidence_write_guard import current_rows


@grants._write
def stage_feedback(db, user, identifier, request):
    stored = storage.load_task(db, user, identifier, exclusive=True)
    if stored.run.status != "succeeded" or results._read_stored_result(db, stored) is None:
        raise HTTPException(409, "仅实际完整成功的未核实假设可追加人工反馈")
    if request.outcome == "modified" and len(request.comment) < 3:
        raise HTTPException(422, "请原样说明修改内容")
    when = grants.utcnow().replace(microsecond=0)
    item = AIFeedback(feedback_id=str(uuid.uuid4()), run_id=identifier, reviewer_id=stored.authorized.actor.user_id, outcome=request.outcome, comment=request.comment, create_time=when)
    db.add(item)
    expected = {column.name: getattr(item, column.name) for column in AIFeedback.__table__.columns}
    audit_id, expected_audit = grants._audit(
        db,
        stored.authorized.actor,
        "rca_run.feedback",
        identifier,
        {
            "feedback": {key: storage._clock_value(value) for key, value in expected.items()},
            "source_hash": stored.artifact.source_hash,
            "result_hash": storage.canonical_value(stored.run.result_json)["result_hash"],
            "automatic_legacy_write": False,
        },
        grants.utcnow(),
    )
    after = storage.load_task(db, user, identifier, exclusive=True)
    results._read_stored_result(db, after)
    actual = current_rows(db.query(AIFeedback).filter_by(feedback_id=item.feedback_id), shared=True).one_or_none()
    if actual is None or {column.name: getattr(actual, column.name) for column in AIFeedback.__table__.columns} != expected:
        raise HTTPException(409, "实际反馈原字段或审计在写回后改变，整笔未接受")
    grants._exact_audit(db, audit_id, expected_audit)
    return {"feedback_id": item.feedback_id, "audit_event_id": audit_id, "automatic_legacy_write": False}
