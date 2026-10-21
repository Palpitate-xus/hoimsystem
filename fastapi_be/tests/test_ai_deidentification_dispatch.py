"""Real synthetic tasks: exact receipts, no TEXT before Source, no duplicate HTTP."""

import asyncio

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy import event, text

from app import database
from app.ai import deidentification_runtime as runtime
from app.ai.deidentification_dispatch import CLAIM, DISPATCH, DeidentificationClaim, read_dispatch, verify_claim
from app.ai.deidentification_receipts import usage_receipt
from app.ai.deidentification_run_models import AIDeidentificationRunResult, AIDeidentificationRunSource
from app.ai.models import AIAuditEvent, AIRun
from tests.test_ai_deidentification_runtime import claim, model, queue
from tests.test_ai_deidentification_storage import task_case as task_case  # noqa: F401
from tests.test_ai_research_cohort_sources import research_case as research_case  # noqa: F401


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", [None, True, 0, -1, "claim", "create", "another"])
async def test_missing_wrong_or_boolean_exact_claim_never_changes_lease_or_calls_model(task_case, invalid):
    case, db = task_case, task_case["db"]
    claimed = claim(case, queue(case))
    original = db.get(AIRun, claimed.run_id)
    before = (original.status, original.lease_token, original.start_time, original.latency_ms)
    source = db.get(AIDeidentificationRunSource, claimed.run_id)
    value = source.create_event_id if invalid == "create" else claimed.claim_event_id + 100000 if invalid == "another" else invalid
    db.rollback()
    packets = []
    with pytest.raises(HTTPException) as rejected:
        await runtime.execute_deidentification_claimed(claimed.run_id, claimed.lease_token, value, transport=model(case, packets=packets))
    assert rejected.value.status_code == 409 and packets == []
    db.expire_all()
    original = db.get(AIRun, claimed.run_id)
    assert (original.status, original.lease_token, original.start_time, original.latency_ms) == before
    row = db.get(AIDeidentificationRunResult, claimed.run_id)
    assert row.claim_event_id == claimed.claim_event_id and row.dispatch_event_id is row.usage_event_id is None


@pytest.mark.asyncio
async def test_durable_specific_claim_dispatch_and_live_duplicate_preserve_first_paid_worker(task_case):
    case, db = task_case, task_case["db"]
    claimed = claim(case, queue(case))
    assert isinstance(claimed, DeidentificationClaim)
    verify_claim(db, *claimed)
    db.rollback()
    entered, release = asyncio.Event(), asyncio.Event()
    calls, sessions = [], []
    factory = database.SessionLocal

    def tracked():
        session = factory()
        sessions.append(session)
        return session

    actual = model(case, packets=calls, partial=True, sessions=sessions)

    async def held(request):
        assert all(not session.in_transaction() for session in sessions)
        entered.set()
        await release.wait()
        return await actual.handle_async_request(request)

    old = database.SessionLocal
    database.SessionLocal = tracked
    try:
        worker = asyncio.create_task(runtime.execute_deidentification_claimed(*claimed, transport=httpx.MockTransport(held)))
        await asyncio.wait_for(entered.wait(), 10)
        db.expire_all()
        reserved = read_dispatch(db, claimed.run_id)
        row = db.get(AIDeidentificationRunResult, claimed.run_id)
        assert reserved["claim_event_id"] == claimed.claim_event_id
        source = db.get(AIDeidentificationRunSource, claimed.run_id)
        assert len({source.create_event_id, row.claim_event_id, row.dispatch_event_id}) == 3
        db.rollback()
        await runtime.execute_deidentification_claimed(*claimed, transport=model(case, packets=calls))
        assert calls == [] and db.get(AIRun, claimed.run_id).status == "running"
        db.rollback()
        release.set()
        await worker
    finally:
        release.set()
        database.SessionLocal = old
    db.expire_all()
    run, result = db.get(AIRun, claimed.run_id), db.get(AIDeidentificationRunResult, claimed.run_id)
    assert run.status == "succeeded" and len(calls) == 1
    assert len({source.create_event_id, result.claim_event_id, result.dispatch_event_id, result.usage_event_id, result.accept_event_id}) == 5
    assert usage_receipt(db, run)["output_tokens"] is None


def test_claim_and_technical_status_select_no_private_task_or_result_text(task_case):
    case, db = task_case, task_case["db"]
    identifier = queue(case)
    selected = []

    def columns(conn, cursor, sql, args, context, many):
        if sql.lstrip().upper().startswith("SELECT") and cursor.description:
            selected.extend(column[0] for column in cursor.description)

    event.listen(db.bind, "after_cursor_execute", columns)
    try:
        claimed = claim(case, identifier)
        assert claimed.claim_event_id > 0
        runtime.technical_deidentification_status(db, case["actor"], identifier)
    finally:
        event.remove(db.bind, "after_cursor_execute", columns)
    forbidden = ("input_json", "evidence_json", "context_metadata_json", "source_json", "result_json")
    assert not any(column == name or column.endswith("_" + name) for column in selected for name in forbidden), selected


@pytest.mark.parametrize("fault", ["claim_audit", "claim_fk"])
def test_claim_actual_sql_fault_rolls_back_run_and_both_specific_receipt_writes(task_case, fault):
    case, db = task_case, task_case["db"]
    identifier = queue(case)
    before = db.query(AIAuditEvent).filter_by(target=identifier).count()
    trigger = (
        "CREATE TRIGGER deid_claim_fault AFTER INSERT ON hoimsystem_ai_audit_event WHEN NEW.action='"
        + CLAIM
        + "' BEGIN UPDATE hoimsystem_ai_audit_event SET action='wrong.claim' WHERE event_id=NEW.event_id; END"
        if fault == "claim_audit"
        else "CREATE TRIGGER deid_claim_fault AFTER UPDATE OF claim_event_id ON hoimsystem_ai_deidentification_run_result BEGIN UPDATE hoimsystem_ai_deidentification_run_result SET claim_event_id=NULL WHERE run_id=NEW.run_id; END"
    )
    db.execute(text(trigger))
    db.commit()
    try:
        with pytest.raises(HTTPException) as rejected:
            runtime.claim_deidentification_run(db, identifier)
        assert rejected.value.status_code == 409
        db.expire_all()
        row = db.get(AIRun, identifier)
        assert row.status == "queued" and row.lease_token is row.start_time is None
        assert db.get(AIDeidentificationRunResult, identifier).claim_event_id is None
        assert db.query(AIAuditEvent).filter_by(target=identifier).count() == before
    finally:
        db.rollback()
        db.execute(text("DROP TRIGGER IF EXISTS deid_claim_fault"))
        db.commit()


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["dispatch_audit", "dispatch_fk"])
async def test_dispatch_actual_sql_fault_rolls_back_reservation_before_any_http(task_case, fault):
    case, db = task_case, task_case["db"]
    claimed = claim(case, queue(case))
    trigger = (
        "CREATE TRIGGER deid_dispatch_fault AFTER INSERT ON hoimsystem_ai_audit_event WHEN NEW.action='"
        + DISPATCH
        + "' BEGIN UPDATE hoimsystem_ai_audit_event SET action='wrong.dispatch' WHERE event_id=NEW.event_id; END"
        if fault == "dispatch_audit"
        else "CREATE TRIGGER deid_dispatch_fault AFTER UPDATE OF dispatch_event_id ON hoimsystem_ai_deidentification_run_result BEGIN UPDATE hoimsystem_ai_deidentification_run_result SET dispatch_event_id=NULL WHERE run_id=NEW.run_id; END"
    )
    db.execute(text(trigger))
    db.commit()
    packets = []
    try:
        await runtime.execute_deidentification_claimed(*claimed, transport=model(case, packets=packets))
        db.expire_all()
        row = db.get(AIRun, claimed.run_id)
        result = db.get(AIDeidentificationRunResult, claimed.run_id)
        assert row.status == "failed" and packets == []
        assert result.claim_event_id == claimed.claim_event_id and result.dispatch_event_id is None
        assert db.query(AIAuditEvent).filter_by(target=claimed.run_id, action=DISPATCH).count() == 0
        assert usage_receipt(db, row) == {"input_tokens": 0, "output_tokens": 0, "complete": True, "model_call_attempted": False}
    finally:
        db.rollback()
        db.execute(text("DROP TRIGGER IF EXISTS deid_dispatch_fault"))
        db.commit()
