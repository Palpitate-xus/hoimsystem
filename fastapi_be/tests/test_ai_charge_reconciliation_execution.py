"""Actual synthetic SQL workers/cancellation with bounded mocked provider HTTP."""

import datetime
import uuid

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy import event, update

from app.ai import charge_reconciliation_execution as execution
from app.ai import charge_reconciliation_receipts as receipts
from app.ai import charge_reconciliation_runtime as runtime
from app.ai import charge_reconciliation_sources as sources
from app.ai.charge_reconciliation_models import AIChargeCaseSnapshot
from app.ai.charge_reconciliation_run_models import AIChargeRunArtifact
from app.ai.models import AIAuditEvent, AIProvider, AIRun
from app.models import InpatientCharge, User
from tests.test_ai_charge_reconciliation_gateway import envelope
from tests.test_ai_charge_reconciliation_runtime import configured
from tests.test_ai_charge_reconciliation_sources import charge_case as _charge_case

charge_case = _charge_case


def prepared(case, *, kind="chat", claimed=True):
    db = case["db"]
    actor, req, value, provider, config = configured(case, kind=kind)
    run = runtime.create_charge_run(db, actor, req)
    identifier, lease = run.run_id, str(uuid.uuid4()) if claimed else None
    if claimed:
        sources.current_actor(db, actor)
        db.execute(update(AIRun).where(AIRun.run_id == identifier).values(status="running", lease_token=lease, start_time=sources.utcnow()))
        db.commit()
    draft = {
        "schema_version": "charge_reconciliation_draft_v1",
        "source_id": value["source_id"],
        "source_projection_hash": value["projection_hash"],
        "coverage": "partial_questions_no_completeness_or_correctness_claim",
        "observations": [],
    }
    patient_id, admission_id, case_id, provider_id, actor_id = value["patient_id"], value["admission_id"], value["case_snapshot_id"], provider.provider_id, actor.user_id
    db.rollback()
    return {
        "run_id": identifier,
        "lease": lease,
        "draft": draft,
        "kind": kind,
        "patient_id": patient_id,
        "admission_id": admission_id,
        "case_id": case_id,
        "provider_id": provider_id,
        "actor_id": actor_id,
    }


def saved(case, item):
    db = case["db"]
    db.expire_all()
    run = db.get(AIRun, item["run_id"])
    result, receipt = receipts.load_terminal(db, run)
    return run, result, receipt


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["chat", "responses"])
async def test_worker_releases_all_sql_connections_and_saves_complete_result_receipt_once(charge_case, kind):
    case, db = charge_case, charge_case["db"]
    item = prepared(case, kind=kind)
    checked_out, calls = [], []
    engine = db.get_bind()

    def checkout(*_args):
        checked_out.append(True)

    def checkin(*_args):
        checked_out.pop()

    def handle(request):
        assert checked_out == []
        calls.append(request)
        return httpx.Response(200, json=envelope(kind, item["draft"]))

    event.listen(engine, "checkout", checkout)
    event.listen(engine, "checkin", checkin)
    try:
        await execution.execute_charge_claimed(item["run_id"], item["lease"], transport=httpx.MockTransport(handle))
        assert checked_out == []
    finally:
        event.remove(engine, "checkout", checkout)
        event.remove(engine, "checkin", checkin)
    run, result, receipt = saved(case, item)
    assert len(calls) == 1 and run.status == "succeeded" and result["charge_analysis"] == item["draft"]
    assert receipt == {"input_tokens": 13, "output_tokens": 7, "complete": True, "model_call_attempted": True}
    assert db.query(AIAuditEvent).filter_by(target=run.run_id, action=receipts.ACCEPT).count() == 1
    assert db.get(AIChargeCaseSnapshot, item["case_id"]).status == "published"
    db.rollback()
    await execution.execute_charge_claimed(item["run_id"], item["lease"], transport=httpx.MockTransport(handle))
    assert len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["partial_usage", "invalid_draft", "timeout", "http_error"])
async def test_paid_errors_keep_reported_companion_or_unknown_counts_without_result(charge_case, fault):
    case = charge_case
    item, calls = prepared(case), []

    def handle(request):
        calls.append(request)
        if fault == "timeout":
            raise httpx.ReadTimeout("synthetic interruption", request=request)
        if fault == "http_error":
            return httpx.Response(503)
        packet = envelope("chat", item["draft"])
        if fault == "partial_usage":
            del packet["usage"]["completion_tokens"]
        else:
            packet["choices"][0]["message"]["content"] = '{"refund_amount":"100.00"}'
        return httpx.Response(200, json=packet)

    await execution.execute_charge_claimed(item["run_id"], item["lease"], transport=httpx.MockTransport(handle))
    run, result, receipt = saved(case, item)
    expected = (13, None) if fault == "partial_usage" else (13, 7) if fault == "invalid_draft" else (None, None)
    assert len(calls) == (3 if fault == "http_error" else 1) and run.status == "failed" and result is None
    assert (receipt["input_tokens"], receipt["output_tokens"]) == expected and receipt["model_call_attempted"] is True
    assert case["db"].get(AIChargeRunArtifact, run.run_id).result_json is None


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["role", "provider_permission", "source"])
async def test_pre_call_recheck_failure_has_actual_zero_usage_and_no_provider_call(charge_case, mutation):
    case, db = charge_case, charge_case["db"]
    item = prepared(case)
    if mutation == "role":
        db.execute(update(User).where(User.user_id == item["actor_id"]).values(user_role="doctor"))
    elif mutation == "provider_permission":
        db.execute(update(AIProvider).where(AIProvider.provider_id == item["provider_id"]).values(allows_patient_data=0))
    else:
        db.execute(update(InpatientCharge).where(InpatientCharge.admission_id == item["admission_id"]).values(status=99))
    db.commit()
    calls = []
    await execution.execute_charge_claimed(item["run_id"], item["lease"], transport=httpx.MockTransport(lambda request: calls.append(request)))
    run, result, receipt = saved(case, item)
    assert not calls and run.status == "failed" and result is None
    assert receipt == {"input_tokens": 0, "output_tokens": 0, "complete": True, "model_call_attempted": False}


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["role", "token_epoch", "source"])
async def test_post_call_current_authorization_rejects_result_and_keeps_actual_paid_usage(charge_case, mutation):
    case, db = charge_case, charge_case["db"]
    item, calls = prepared(case), []

    def handle(request):
        calls.append(request)
        if mutation == "role":
            db.execute(update(User).where(User.user_id == item["actor_id"]).values(user_role="doctor"))
        elif mutation == "token_epoch":
            db.execute(update(User).where(User.user_id == item["actor_id"]).values(token_invalid_before=sources.utcnow()))
        else:
            db.execute(update(InpatientCharge).where(InpatientCharge.admission_id == item["admission_id"]).values(status=99))
        db.commit()
        return httpx.Response(200, json=envelope("chat", item["draft"]))

    await execution.execute_charge_claimed(item["run_id"], item["lease"], transport=httpx.MockTransport(handle))
    run, result, receipt = saved(case, item)
    assert len(calls) == 1 and run.status == "failed" and result is None
    assert receipt == {"input_tokens": 13, "output_tokens": 7, "complete": True, "model_call_attempted": True}


@pytest.mark.asyncio
@pytest.mark.parametrize("claimed", [False, True])
async def test_cancel_before_worker_sends_no_call_and_retains_true_zero(charge_case, claimed):
    case, db = charge_case, charge_case["db"]
    item = prepared(case, claimed=claimed)
    execution.cancel_charge_run(db, case["super_admin_user"], item["run_id"])
    if claimed:
        run = db.get(AIRun, item["run_id"])
        assert run.status == "cancelled" and run.latency_ms is None
        assert receipts.load_terminal(db, run)[1]["model_call_attempted"] is None
        db.rollback()
    calls = []
    await execution.execute_charge_claimed(item["run_id"], item["lease"] or str(uuid.uuid4()), transport=httpx.MockTransport(lambda request: calls.append(request)))
    run, result, receipt = saved(case, item)
    assert not calls and run.status == "cancelled" and result is None
    assert receipt == {"input_tokens": 0, "output_tokens": 0, "complete": True, "model_call_attempted": False}


@pytest.mark.asyncio
@pytest.mark.parametrize("partial", [False, True])
async def test_actual_inflight_cancel_keeps_paid_receipt_and_never_accepts_result(charge_case, partial):
    case, db = charge_case, charge_case["db"]
    item, calls = prepared(case), []

    def handle(request):
        calls.append(request)
        execution.cancel_charge_run(db, case["super_admin_user"], item["run_id"])
        packet = envelope("chat", item["draft"])
        if partial:
            del packet["usage"]["completion_tokens"]
        return httpx.Response(200, json=packet)

    await execution.execute_charge_claimed(item["run_id"], item["lease"], transport=httpx.MockTransport(handle))
    run, result, receipt = saved(case, item)
    assert len(calls) == 1 and run.status == "cancelled" and result is None
    assert receipt == {"input_tokens": 13, "output_tokens": None if partial else 7, "complete": not partial, "model_call_attempted": True}
    assert db.query(AIAuditEvent).filter_by(target=run.run_id, action=receipts.ACCEPT).count() == 0
    assert db.query(AIAuditEvent).filter_by(target=run.run_id, action=receipts.CANCEL).count() == 1


@pytest.mark.asyncio
async def test_actual_post_accept_audit_sql_fault_rolls_back_result_then_keeps_paid_failure_receipt(charge_case):
    case, db = charge_case, charge_case["db"]
    item, fired = prepared(case), []
    engine = db.get_bind()

    def fault(conn, cursor, statement, parameters, execution_context, many):
        values = tuple(parameters.values()) if isinstance(parameters, dict) else parameters
        if not fired and statement.lstrip().upper().startswith("INSERT INTO HOIMSYSTEM_AI_AUDIT_EVENT") and receipts.ACCEPT in values:
            fired.append(True)
            conn.execute(update(AIRun).where(AIRun.run_id == item["run_id"]).values(preview=0))

    event.listen(engine, "after_cursor_execute", fault)
    try:
        await execution.execute_charge_claimed(item["run_id"], item["lease"], transport=httpx.MockTransport(lambda request: httpx.Response(200, json=envelope("chat", item["draft"]))))
    finally:
        event.remove(engine, "after_cursor_execute", fault)
    run, result, receipt = saved(case, item)
    assert fired == [True] and run.status == "failed" and run.error_code == "RESULT_STORAGE_ERROR" and run.preview == 1 and result is None
    assert receipt["input_tokens"] == 13 and receipt["output_tokens"] == 7
    assert db.query(AIAuditEvent).filter_by(target=run.run_id, action=receipts.ACCEPT).count() == 0
    assert db.query(AIAuditEvent).filter_by(target=run.run_id, action=receipts.FAIL).count() == 1


@pytest.mark.parametrize("cancelled", [False, True])
def test_interrupted_claim_retains_unknown_actual_attempt_without_retry(charge_case, cancelled):
    case, db = charge_case, charge_case["db"]
    item = prepared(case)
    db.execute(update(AIRun).where(AIRun.run_id == item["run_id"]).values(status="cancelled" if cancelled else "running", start_time=sources.utcnow() - datetime.timedelta(minutes=11)))
    db.commit()
    assert execution.expire_interrupted_charge_runs(db) == 1
    run, result, receipt = saved(case, item)
    assert run.status == ("cancelled" if cancelled else "failed") and run.error_code == "WORKER_INTERRUPTED" and result is None
    assert receipt == {"input_tokens": None, "output_tokens": None, "complete": False, "model_call_attempted": None}
    db.rollback()
    assert execution.expire_interrupted_charge_runs(db) == 0


@pytest.mark.parametrize("field,value", [("lease_token", "lease"), ("start_time", "clock"), ("input_tokens", 1), ("output_tokens", 1), ("error_code", "HAS_CALL"), ("latency_ms", 0)])
def test_forged_queued_execution_footprint_cannot_claim_true_zero_cancel(charge_case, field, value):
    case, db = charge_case, charge_case["db"]
    item = prepared(case, claimed=False)
    value = str(uuid.uuid4()) if value == "lease" else sources.utcnow() if value == "clock" else value
    db.execute(update(AIRun).where(AIRun.run_id == item["run_id"]).values({field: value}))
    db.commit()
    with pytest.raises(HTTPException) as caught:
        execution.cancel_charge_run(db, case["super_admin_user"], item["run_id"])
    assert caught.value.status_code == 409
    run = db.get(AIRun, item["run_id"])
    assert run.status == "queued" and db.get(AIChargeRunArtifact, run.run_id).receipt_event_id is None
