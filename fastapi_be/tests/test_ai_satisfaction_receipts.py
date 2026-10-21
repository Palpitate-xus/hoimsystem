"""Specific-PK terminal proof tamper and actual same-transaction SQL faults."""

import asyncio

import httpx
import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import event, text

from app.ai import satisfaction_execution as execution
from app.ai import satisfaction_receipts as receipts
from app.ai import satisfaction_runtime as runtime
from app.ai.models import AIAuditEvent, AIRun
from app.ai.satisfaction_artifact_models import AISatisfactionRunArtifact
from app.ai.satisfaction_sources import utcnow
from app.ai.satisfaction_storage import RECEIPT_ACTION
from app.models import Review
from tests.test_ai_satisfaction_gateway import envelope
from tests.test_ai_satisfaction_runtime import prepared, saved
from tests.test_ai_satisfaction_runtime import runtime_case as runtime_case  # noqa: F401
from tests.test_ai_satisfaction_sources import satisfaction_case as satisfaction_case  # noqa: F401


@pytest.mark.parametrize("value", [(0, 0, False), (None, None, None), (13, None, True), (None, 7, True), (0, 0, True)])
def test_actual_independent_usage_semantics_preserve_zero_and_nullable(value):
    result = receipts.usage(*value)
    assert (result["input_tokens"], result["output_tokens"], result["model_call_attempted"]) == value
    assert result["complete"] == (value[0] is not None and value[1] is not None)


@pytest.mark.parametrize("value", [(None, None, False), (13, 0, False), (0, None, None), (False, 1, True), (-1, 1, True)])
def test_inconsistent_or_coerced_usage_cannot_be_a_real_receipt(value):
    with pytest.raises(ValidationError):
        receipts.usage(*value)


@pytest.mark.asyncio
@pytest.mark.parametrize("field,value", [("latency_ms", 999999), ("error_message", "伪造终态说明"), ("output_tokens", 18)])
async def test_historical_terminal_22_fields_are_bound_to_exact_original_usage_event(runtime_case, field, value):
    case, db = runtime_case, runtime_case["db"]
    item = prepared(case)
    await execution.execute_satisfaction_claimed(
        item["run_id"], item["lease"], transport=httpx.MockTransport(lambda _: httpx.Response(200, json=envelope("chat", item["draft"]))), session_factory=case["factory"]
    )
    run, _, _ = saved(case, item)
    setattr(run, field, value)
    db.commit()
    with pytest.raises(HTTPException) as error:
        runtime.describe_satisfaction_run(db, case["admin_user"], run)
    assert error.value.status_code == 409


@pytest.mark.asyncio
async def test_substituted_usage_fk_or_modified_exact_receipt_is_rejected_without_range_scan(runtime_case):
    case, db = runtime_case, runtime_case["db"]
    item = prepared(case)
    await execution.execute_satisfaction_claimed(
        item["run_id"], item["lease"], transport=httpx.MockTransport(lambda _: httpx.Response(200, json=envelope("chat", item["draft"]))), session_factory=case["factory"]
    )
    run, _, _ = saved(case, item)
    artifact = db.get(AISatisfactionRunArtifact, run.run_id)
    original_id = artifact.usage_event_id
    unrelated = AIAuditEvent(actor_id=run.requested_by, action="unrelated.synthetic", target=run.run_id, detail_json="{}")
    db.add(unrelated)
    db.flush()
    artifact.usage_event_id = unrelated.event_id
    db.commit()
    with pytest.raises(HTTPException):
        receipts.load_terminal(db, run)
    db.rollback()
    artifact = db.get(AISatisfactionRunArtifact, run.run_id)
    artifact.usage_event_id = original_id
    db.get(AIAuditEvent, original_id).detail_json = "{}"
    db.commit()
    statements = []

    def seen(conn, cursor, statement, parameters, context, many):
        if "FROM hoimsystem_ai_audit_event" in statement:
            statements.append(statement)

    event.listen(db.bind, "before_cursor_execute", seen)
    try:
        with pytest.raises(HTTPException):
            receipts.load_terminal(db, run)
    finally:
        event.remove(db.bind, "before_cursor_execute", seen)
    assert statements and all("WHERE hoimsystem_ai_audit_event.event_id =" in statement for statement in statements)


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["source", "run", "usage_body", "accept_abort"])
async def test_actual_sql_acceptance_faults_roll_back_complete_result_and_both_specific_audits(runtime_case, fault):
    case, db = runtime_case, runtime_case["db"]
    item = prepared(case)
    original_comment = case["review"].comment
    rid = item["review_id"]
    if fault == "accept_abort":
        sql = f"CREATE TRIGGER satisfaction_terminal_fault BEFORE INSERT ON hoimsystem_ai_audit_event WHEN NEW.action='{RECEIPT_ACTION}' BEGIN SELECT RAISE(ABORT,'synthetic receipt rejection'); END"
    else:
        body = {
            "source": f"UPDATE hoimsystem_review SET comment='synthetic terminal source changed' WHERE review_id={rid};",
            "run": "UPDATE hoimsystem_ai_run SET error_message='synthetic changed message' WHERE run_id=NEW.target;",
            "usage_body": "UPDATE hoimsystem_ai_audit_event SET detail_json='{}' WHERE event_id=NEW.event_id;",
        }[fault]
        sql = "CREATE TRIGGER satisfaction_terminal_fault AFTER INSERT ON hoimsystem_ai_audit_event WHEN NEW.action='" + receipts.ACTIONS["succeeded"] + "' BEGIN " + body + " END"
    db.execute(text(sql))
    db.commit()
    db.rollback()
    try:
        await execution.execute_satisfaction_claimed(
            item["run_id"], item["lease"], transport=httpx.MockTransport(lambda _: httpx.Response(200, json=envelope("chat", item["draft"]))), session_factory=case["factory"]
        )
        run, result, receipt = saved(case, item)
        assert run.status == "failed" and run.error_code == "RESULT_STORAGE_ERROR" and result is None and receipt == receipts.usage(13, 7, True)
        artifact = db.get(AISatisfactionRunArtifact, run.run_id)
        assert artifact.result_json is artifact.receipt_event_id is artifact.accepted_lease is None
        assert artifact.usage_event_id is not None
        assert db.query(AIAuditEvent).filter_by(target=run.run_id, action=RECEIPT_ACTION).count() == 0
        assert db.get(Review, rid).comment == original_comment
    finally:
        db.rollback()
        db.execute(text("DROP TRIGGER satisfaction_terminal_fault"))
        db.commit()


@pytest.mark.asyncio
async def test_base_cancellation_is_not_swallowed_and_recovery_never_invents_no_call(runtime_case):
    import datetime as dt

    case, db = runtime_case, runtime_case["db"]
    item = prepared(case)

    def handle(_):
        raise asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        await execution.execute_satisfaction_claimed(item["run_id"], item["lease"], transport=httpx.MockTransport(handle), session_factory=case["factory"])
    db.expire_all()
    run = db.get(AIRun, item["run_id"])
    assert run.status == "running" and db.get(AISatisfactionRunArtifact, run.run_id).usage_event_id is None
    run.start_time = utcnow() - dt.timedelta(minutes=11)
    db.commit()
    execution.expire_interrupted_satisfaction_runs(db)
    run, result, receipt = saved(case, item)
    assert run.error_code == "WORKER_INTERRUPTED" and result is None and receipt == receipts.usage()
