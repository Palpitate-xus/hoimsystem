"""Actual current Super technical cancellation does not restore research bodies."""

import asyncio
from types import SimpleNamespace

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy import event, text

from app.ai import deidentification_runtime as dedicated
from app.ai import runtime
from app.ai.deidentification_receipts import usage_receipt
from app.ai.deidentification_run_models import AIDeidentificationRunResult
from app.ai.models import AIAuditEvent, AIRun
from app.ai.research_cohort_registry import review_registry_original
from tests.test_ai_deidentification_runtime import model, queue
from tests.test_ai_deidentification_storage import task_case as task_case  # noqa: F401
from tests.test_ai_research_cohort_contract import BASIS
from tests.test_ai_research_cohort_sources import research_case as research_case  # noqa: F401


def withdraw(case):
    review_registry_original(case["db"], case["users"]["super_admin_user"], "authorization", case["values"][3]["source_record_id"], {"expected_revision": 2, "basis_note": BASIS}, revoke=True)


def selected_columns(db):
    columns = []

    def observed(conn, cursor, sql, args, context, many):
        if sql.lstrip().upper().startswith("SELECT") and cursor.description:
            columns.extend(field[0] for field in cursor.description)

    event.listen(db.bind, "after_cursor_execute", observed)
    return columns, observed


def no_private_text(columns):
    names = ("input_json", "evidence_json", "context_metadata_json", "source_json", "result_json")
    assert not any(column == name or column.endswith("_" + name) for column in columns for name in names), columns


@pytest.mark.asyncio
async def test_actual_withdrawn_scope_super_stops_queued_known_zero_without_any_clinical_or_task_body(task_case, async_client, auth_headers):
    case, db = task_case, task_case["db"]
    identifier = queue(case)
    ordinary, sup = auth_headers(case["actor"].username), auth_headers(case["users"]["super_admin_user"].username)
    withdraw(case)
    columns, observed = selected_columns(db)
    try:
        denied = await async_client.post(f"/api/ai/runs/{identifier}/cancel", headers=ordinary)
        assert denied.status_code == 403
        stopped = await async_client.post(f"/api/ai/runs/{identifier}/cancel", headers=sup)
        assert stopped.status_code == 200, stopped.text
    finally:
        event.remove(db.bind, "after_cursor_execute", observed)
    no_private_text(columns)
    run = db.get(AIRun, identifier)
    result = db.get(AIDeidentificationRunResult, identifier)
    assert run.status == "cancelled" and result.claim_event_id is result.dispatch_event_id is None
    assert result.usage_event_id is not None and result.accept_event_id is None
    assert usage_receipt(db, run) == {"input_tokens": 0, "output_tokens": 0, "complete": True, "model_call_attempted": False}
    for path in (f"/api/ai/admin/runs/{identifier}", f"/api/ai/deidentification/tasks/{identifier}/parts/source?audit_only=true"):
        assert (await async_client.get(path, headers=sup)).status_code == 403
    assert (await async_client.post("/api/ai/runs", headers=sup, json={"feature_key": "deidentification", "input": case["input"]})).status_code == 403


@pytest.mark.asyncio
async def test_withdrawn_inflight_super_cancel_keeps_pending_unknown_then_actual_partial_paid_and_duplicate_never_replays(task_case, async_client, auth_headers):
    case, db = task_case, task_case["db"]
    identifier = queue(case)
    claimed = runtime.claim_next_run(db)
    db.rollback()
    entered, release, calls = asyncio.Event(), asyncio.Event(), []
    actual = model({**case, "provider": SimpleNamespace(kind="chat")}, partial=True, packets=calls)

    async def held(incoming):
        entered.set()
        await release.wait()
        return await actual.handle_async_request(incoming)

    async def invoke():
        await runtime.execute_claimed(identifier, claimed.lease_token, deidentification_claim_event_id=claimed.claim_event_id, transport=httpx.MockTransport(held))

    first = asyncio.create_task(invoke())
    await asyncio.wait_for(entered.wait(), 15)
    try:
        withdraw(case)
        sup = auth_headers(case["users"]["super_admin_user"].username)
        stopped = await async_client.post(f"/api/ai/runs/{identifier}/cancel", headers=sup)
        assert stopped.status_code == 200, stopped.text
        db.expire_all()
        run, result = db.get(AIRun, identifier), db.get(AIDeidentificationRunResult, identifier)
        assert run.status == "cancelled" and result.dispatch_event_id is not None and result.usage_event_id is None
        assert usage_receipt(db, run) == {"input_tokens": None, "output_tokens": None, "complete": False, "model_call_attempted": None}
        db.rollback()
        await invoke()
        with pytest.raises(HTTPException):
            await runtime.execute_claimed(identifier, claimed.lease_token, deidentification_claim_event_id=claimed.claim_event_id + 100000)
        assert calls == []
    finally:
        release.set()
        await first
    db.expire_all()
    run, result = db.get(AIRun, identifier), db.get(AIDeidentificationRunResult, identifier)
    assert run.status == "cancelled" and result.result_json is result.accept_event_id is None and len(calls) == 1
    assert usage_receipt(db, run) == {"input_tokens": 11, "output_tokens": None, "complete": False, "model_call_attempted": True}
    db.rollback()
    await invoke()
    assert len(calls) == 1


@pytest.mark.parametrize("field,value", [("feature_key", "erased"), ("input_json", "{}")])
def test_current_super_cannot_invent_zero_receipt_for_tampered_native_header_or_raw_binding(task_case, field, value):
    case, db = task_case, task_case["db"]
    identifier = queue(case)
    db.execute(text("UPDATE hoimsystem_ai_run SET " + field + "=:value WHERE run_id=:id"), {"value": value, "id": identifier})
    db.commit()
    before = db.query(AIAuditEvent).filter_by(target=identifier).count()
    columns, observed = selected_columns(db)
    try:
        with pytest.raises(HTTPException) as denied:
            dedicated.cancel_deidentification_run(db, case["users"]["super_admin_user"], identifier, audit_only=True)
        assert denied.value.status_code == 409
    finally:
        event.remove(db.bind, "after_cursor_execute", observed)
    no_private_text(columns)
    assert db.query(AIRun.status).filter_by(run_id=identifier).scalar() == "queued"
    assert db.query(AIAuditEvent).filter_by(target=identifier).count() == before
    assert db.get(AIDeidentificationRunResult, identifier).usage_event_id is None


@pytest.mark.asyncio
async def test_existing_dispatch_prevents_forged_queued_zero_even_when_lease_headers_are_erased(task_case):
    case, db = task_case, task_case["db"]
    identifier = queue(case)
    # Prior corruption controls deliberately retain queued rows. This stop-
    # only case addresses its actual Run ID instead of claiming those fixtures.
    claimed = dedicated.claim_deidentification_run(db, identifier)
    db.rollback()

    class Interrupted(BaseException):
        pass

    def interrupt(incoming):
        raise Interrupted("synthetic interrupted already-reserved model send")

    with pytest.raises(Interrupted):
        await runtime.execute_claimed(identifier, claimed.lease_token, deidentification_claim_event_id=claimed.claim_event_id, transport=httpx.MockTransport(interrupt))
    dispatch = db.get(AIDeidentificationRunResult, identifier).dispatch_event_id
    assert dispatch is not None
    db.execute(text("UPDATE hoimsystem_ai_run SET status='queued',lease_token=NULL,start_time=NULL,latency_ms=NULL WHERE run_id=:id"), {"id": identifier})
    db.commit()
    with pytest.raises(HTTPException) as denied:
        dedicated.cancel_deidentification_run(db, case["users"]["super_admin_user"], identifier, audit_only=True)
    assert denied.value.status_code == 409
    result = db.get(AIDeidentificationRunResult, identifier)
    assert result.dispatch_event_id == dispatch and result.usage_event_id is None
    assert db.query(AIRun.status).filter_by(run_id=identifier).scalar() == "queued"
