"""Actual Main cancellation, exact receipt references and recovery boundaries."""

import datetime as dt
import json

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy import event, inspect, text
from sqlalchemy.orm import Session

from app import database
from app.ai import research_variables_receipts as receipts
from app.ai import runtime
from app.ai.models import AIAuditEvent, AIFeedback
from app.ai.research_cohort_sources import utcnow
from app.ai.research_variables_run_models import AIResearchVariableRunArtifact
from app.ai.research_variables_storage_contract import VariableUsageReceipt
from app.ai.research_variables_task_contract import VariableTaskSource, canonical
from tests.test_ai_research_variables_attempts import claimed
from tests.test_ai_research_variables_configuration import configured as configured
from tests.test_ai_research_variables_pipeline import main_case as main_case
from tests.test_ai_research_variables_pipeline import queued_task
from tests.test_ai_research_variables_receipts import delivered
from tests.test_ai_research_variables_result_storage import material
from tests.test_ai_research_variables_task_context import research_case as research_case
from tests.test_ai_research_variables_task_context import task_factory as task_factory
from tests.test_ai_research_variables_task_reader import actual_task as actual_task
from tests.test_ai_research_variables_task_result import draft, envelope


def observe_bodies():
    columns = []

    def seen(state):
        if state.is_select and hasattr(state.statement, "selected_columns"):
            columns.extend(
                str(column.key) for column in state.statement.selected_columns if column.key in {"input_json", "result_json", "evidence_json", "context_metadata_json", "source_json", "binding_json"}
            )

    event.listen(Session, "do_orm_execute", seen)
    return columns, seen


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["queued", "claimed", "dispatched"])
async def test_actual_main_manual_cancel_keeps_known_uncalled_zero_separate_from_pending_and_original_partial_paid_delivery(db_session, main_case, async_client, phase):
    value = main_case
    queued = await queued_task(async_client, value["admin"], value["selection"])
    identifier = queued["run_id"]
    claim = None
    if phase != "queued":
        with database.SessionLocal() as db:
            claim = runtime.claim_next_run(db)
        assert claim[0] == identifier
    db_session.close()
    paths = "/api/ai/runs/" + identifier
    cancellations, calls = [], []

    async def cancel():
        response = await async_client.post(paths + "/cancel", headers=value["super"])
        assert response.status_code == 200, response.text
        cancellations.append(response.json()["data"])
        detail = await async_client.get(paths, headers=value["admin"])
        assert detail.status_code == 200, detail.text
        current = detail.json()["data"]
        assert current["status"] == "cancelled" and current["result"] is None
        assert (current["usage_receipt"] is None) is (phase == "dispatched")
        assert cancellations[-1]["receipt_pending"] is (phase == "dispatched")
        return current

    async def reply(request):
        calls.append(request.url.path)
        source = VariableTaskSource.model_validate(json.loads(json.loads(request.content)["messages"][1]["content"])["research_variable_source"])
        await cancel()
        return httpx.Response(200, json=envelope("chat", canonical(draft(source)), {"prompt_tokens": 11}))

    if phase == "dispatched":
        await runtime.execute_claimed(*claim, transport=httpx.MockTransport(reply))
    else:
        await cancel()
        if claim is not None:
            await runtime.execute_claimed(*claim, transport=httpx.MockTransport(reply))
    response = await async_client.get(paths, headers=value["admin"])
    assert response.status_code == 200, response.text
    detail = response.json()["data"]
    assert detail["status"] == "cancelled" and detail["usage_receipt_status"] == "recorded"
    receipt = detail["usage_receipt"]
    assert (receipt["input_tokens"], receipt["output_tokens"], receipt["model_call_attempted"]) == ((11, None, True) if phase == "dispatched" else (0, 0, False))
    assert len(calls) == int(phase == "dispatched")
    second = await async_client.post(paths + "/cancel", headers=value["super"])
    assert second.status_code == 409
    with database.SessionLocal() as db:
        artifact = db.get(AIResearchVariableRunArtifact, identifier)
        assert (artifact.claim_event_id is None) is (phase == "queued")
        assert (artifact.dispatch_event_id is not None) is (phase == "dispatched")
        assert artifact.usage_event_id is not None
        assert db.query(AIAuditEvent).filter_by(target=identifier, action="research_variable_run.usage").count() == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["failed", "cancelled"])
async def test_settled_terminal_receipt_reference_erasure_cannot_be_reinterpreted_as_pending(db_session, actual_task, auth_headers, async_client, state):
    case, _, _, _ = actual_task
    delivery = delivered(db_session, actual_task)
    identifier = delivery.claim.run_id
    receipts.stage_terminal(
        db_session,
        delivery.claim,
        delivery=delivery,
        receipt=VariableUsageReceipt(input_tokens=11, output_tokens=13, complete=True, model_call_attempted=True),
        status=state,
        error_code="VARIABLE_PROVIDER_ERROR",
        error_message="actual paid terminal",
        latency_ms=123,
    )
    db_session.commit()
    headers = auth_headers(case["admin_user"].username)
    normal = await async_client.get("/api/ai/runs/" + identifier, headers=headers)
    assert normal.status_code == 200 and normal.json()["data"]["usage_receipt_status"] == "recorded"
    original_event = db_session.query(AIResearchVariableRunArtifact.usage_event_id).filter_by(run_id=identifier).scalar()
    assert original_event is not None
    try:
        db_session.execute(text("UPDATE hoimsystem_ai_research_variable_run_artifact SET usage_event_id=NULL WHERE run_id=:id"), {"id": identifier})
        db_session.commit()
        for suffix in ("", "/research-variables/receipt"):
            response = await async_client.get("/api/ai/runs/" + identifier + suffix, headers=headers)
            assert response.status_code == 409, response.text
        before = db_session.query(AIAuditEvent).count()
        with pytest.raises(HTTPException) as error:
            receipts.stage_terminal(
                db_session,
                delivery.claim,
                delivery=delivery,
                receipt=VariableUsageReceipt(input_tokens=11, output_tokens=13, complete=True, model_call_attempted=True),
                status=state,
                error_code="VARIABLE_PROVIDER_ERROR",
                error_message="must not settle twice",
                latency_ms=456,
            )
        assert error.value.status_code == 409
        assert db_session.query(AIAuditEvent).count() == before
    finally:
        db_session.rollback()
        db_session.execute(text("UPDATE hoimsystem_ai_research_variable_run_artifact SET usage_event_id=:event WHERE run_id=:id"), {"event": original_event, "id": identifier})
        db_session.commit()


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["audit", "role"])
async def test_actual_feedback_specific_audit_or_current_actor_trigger_failure_rolls_back_feedback_and_its_sql_side_effect(db_session, actual_task, auth_headers, async_client, fault):
    from app.ai import research_variables_result_storage as results

    case, _, _, _ = actual_task
    delivery = delivered(db_session, actual_task)
    accepted = material(db_session, case, delivery)
    results.stage_result(db_session, case["admin_user"], delivery, accepted, VariableUsageReceipt(input_tokens=11, output_tokens=13, complete=True, model_call_attempted=True), latency_ms=123)
    db_session.commit()
    identifier = delivery.claim.run_id
    headers = auth_headers(case["admin_user"].username)
    actor_id = inspect(case["admin_user"]).identity[0]
    before = db_session.query(AIFeedback).count(), db_session.query(AIAuditEvent).count()
    mutation = "UPDATE hoimsystem_ai_audit_event SET detail_json='{}' WHERE event_id=NEW.event_id" if fault == "audit" else f"UPDATE hoimsystem_users SET user_role='nurse' WHERE user_id={actor_id}"
    trigger = "research_variable_feedback_fault_" + fault
    db_session.execute(text("CREATE TRIGGER " + trigger + " AFTER INSERT ON hoimsystem_ai_audit_event WHEN NEW.action='research_variable_run.feedback' BEGIN " + mutation + "; END"))
    db_session.commit()
    try:
        response = await async_client.post("/api/ai/runs/" + identifier + "/feedback", headers=headers, json={"outcome": "modified", "comment": "实际人工说明"})
        assert response.status_code == (403 if fault == "role" else 409), response.text
        db_session.expire_all()
        assert (db_session.query(AIFeedback).count(), db_session.query(AIAuditEvent).count()) == before
        assert db_session.execute(text("SELECT user_role FROM hoimsystem_users WHERE user_id=:id"), {"id": actor_id}).scalar() == "admin"
    finally:
        db_session.rollback()
        db_session.execute(text("DROP TRIGGER IF EXISTS " + trigger))
        db_session.commit()


@pytest.mark.parametrize("phase", ["claimed", "dispatched", "cancel_pending"])
def test_shared_recovery_of_actual_original_claim_never_replays_or_reads_task_body_and_preserves_unknown_after_dispatch(db_session, actual_task, monkeypatch, phase):
    case, _, _, _ = actual_task
    delivery = delivered(db_session, actual_task) if phase != "claimed" else None
    claim = delivery.claim if delivery is not None else claimed(db_session, actual_task)
    if phase == "cancel_pending":
        from app.ai.research_variables_cancellation import cancel_variable_run

        cancel_variable_run(db_session, case["super_admin_user"], claim.run_id)
    monkeypatch.setattr(runtime, "utcnow", lambda: utcnow() + dt.timedelta(minutes=11))
    columns, seen = observe_bodies()
    try:
        assert runtime.expire_interrupted_runs(db_session) == 1
        assert runtime.expire_interrupted_runs(db_session) == 0
    finally:
        event.remove(Session, "do_orm_execute", seen)
    assert not columns
    task = receipts.technical_task(db_session, claim)
    actual = receipts.verify_receipt(db_session, task).receipt
    assert (actual.input_tokens, actual.output_tokens, actual.model_call_attempted) == ((0, 0, False) if delivery is None else (None, None, None))
    assert task.run.status == ("cancelled" if phase == "cancel_pending" else "failed")
