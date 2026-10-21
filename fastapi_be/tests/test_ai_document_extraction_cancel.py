"""Actual cancellation endpoints and worker leases; no external model or DB."""

import datetime

import httpx
import pytest
from sqlalchemy import text

from app.ai import runtime
from app.ai.document_extraction_run_record import parse_record
from app.ai.models import AIAuditEvent, AIRun
from tests.test_ai_document_extraction_pipeline import document_pipeline as _document_pipeline
from tests.test_ai_document_extraction_pipeline import model_transport, request

document_pipeline = _document_pipeline


async def queued(client, headers, case):
    response = await client.post("/api/ai/runs", headers=headers, json=request(case))
    assert response.status_code == 200, response.text
    return response.json()["data"]["run_id"]


@pytest.mark.asyncio
@pytest.mark.parametrize("claimed", [False, True])
async def test_cancel_before_any_provider_call_retains_actual_zero_receipt(async_client, auth_headers, document_pipeline, claimed):
    case, db = document_pipeline, document_pipeline["db"]
    headers = auth_headers(case["actor"].username)
    run_id = await queued(async_client, headers, case)
    claim = runtime.claim_next_run(db) if claimed else None
    if claimed:
        assert claim[0] == run_id
    cancelled = await async_client.post(f"/api/ai/runs/{run_id}/cancel", headers=headers)
    assert cancelled.status_code == 200, cancelled.text
    calls = []

    def forbidden(req):
        calls.append(req)
        raise AssertionError("A cancelled unstarted task must never invoke a provider")

    if claimed:
        pending = await async_client.get(f"/api/ai/runs/{run_id}", headers=headers)
        assert pending.json()["data"]["usage_receipt_status"] == "pending"
        await runtime.execute_claimed(*claim, transport=httpx.MockTransport(forbidden))
    else:
        assert runtime.claim_next_run(db) is None
    for path in (f"/api/ai/runs/{run_id}", f"/api/ai/admin/runs/{run_id}"):
        response = await async_client.get(path, headers=headers)
        assert response.status_code == 200, response.text
        data = response.json()["data"]
        assert data["status"] == "cancelled" and data["result"] is None
        assert data["usage_receipt_status"] == "recorded"
        assert data["usage_receipt"] == {"input_tokens": 0, "output_tokens": 0, "complete": True, "model_call_attempted": False}
    db.expire_all()
    run = db.get(AIRun, run_id)
    record = parse_record(run.result_json)
    assert record.result is None and not record.saved_candidates
    event = db.get(AIAuditEvent, record.receipt_event_id)
    assert event.target == run_id and event.action == "run.document_extraction.cancel"
    before = run.result_json
    if claimed:
        await runtime.execute_claimed(*claim, transport=httpx.MockTransport(forbidden))
        db.expire_all()
        assert db.get(AIRun, run_id).result_json == before
    assert not calls
    repeated = await async_client.post(f"/api/ai/runs/{run_id}/cancel", headers=headers)
    assert repeated.status_code == 409


@pytest.mark.asyncio
async def test_real_inflight_cancel_endpoint_preserves_actual_provider_usage(async_client, auth_headers, document_pipeline):
    case, db = document_pipeline, document_pipeline["db"]
    headers = auth_headers(case["actor"].username)
    run_id = await queued(async_client, headers, case)
    claim = runtime.claim_next_run(db)
    base, packets = model_transport(case)

    async def handler(req):
        response = await async_client.post(f"/api/ai/runs/{run_id}/cancel", headers=headers)
        assert response.status_code == 200, response.text
        detail = await async_client.get(f"/api/ai/runs/{run_id}", headers=headers)
        data = detail.json()["data"]
        assert data["status"] == "cancelled" and data["usage_receipt_status"] == "pending"
        assert data["input_tokens"] is None and data["output_tokens"] is None
        return base.handle_request(req)

    await runtime.execute_claimed(*claim, transport=httpx.MockTransport(handler))
    detail = await async_client.get(f"/api/ai/runs/{run_id}", headers=headers)
    data = detail.json()["data"]
    assert data["status"] == "cancelled" and data["result"] is None
    assert data["usage_receipt"] == {"input_tokens": 11, "output_tokens": 13, "complete": True, "model_call_attempted": True}
    assert len(packets) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field,value",
    [
        ("lease_token", "00000000-0000-4000-8000-000000000099"),
        ("start_time", datetime.datetime(2026, 10, 21, 12)),
        ("latency_ms", 1),
        ("finish_time", datetime.datetime(2026, 10, 21, 12)),
        ("result_json", '{"unexpected":true}'),
        ("input_tokens", 1),
        ("output_tokens", 1),
        ("error_code", "unexpected"),
        ("error_message", "unexpected"),
    ],
)
async def test_queued_execution_footprints_cannot_be_relabelled_as_no_call(async_client, auth_headers, document_pipeline, field, value):
    case, db = document_pipeline, document_pipeline["db"]
    headers = auth_headers(case["actor"].username)
    run_id = await queued(async_client, headers, case)
    db.query(AIRun).filter_by(run_id=run_id).update({field: value})
    db.commit()
    before = db.query(AIAuditEvent).filter_by(target=run_id).count()
    response = await async_client.post(f"/api/ai/runs/{run_id}/cancel", headers=headers)
    assert response.status_code == 409, response.text
    db.expire_all()
    assert db.get(AIRun, run_id).status == "queued"
    assert getattr(db.get(AIRun, run_id), field) == value
    assert db.query(AIAuditEvent).filter_by(target=run_id).count() == before


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "action,fault",
    [
        ("run.document_extraction.cancel", "audit"),
        ("run.document_extraction.cancel", "tokens"),
        ("run.cancel", "audit"),
        ("run.cancel", "tokens"),
        ("run.cancel", "terminal"),
    ],
)
async def test_cancel_actual_sql_fault_rolls_back_zero_receipt_and_both_audits(async_client, auth_headers, document_pipeline, action, fault):
    case, db = document_pipeline, document_pipeline["db"]
    headers = auth_headers(case["actor"].username)
    run_id = await queued(async_client, headers, case)
    before = db.query(AIAuditEvent).filter_by(target=run_id).count()
    effect = (
        "DELETE FROM hoimsystem_ai_audit_event WHERE event_id=NEW.event_id"
        if fault == "audit"
        else "DELETE FROM hoimsystem_ai_audit_event WHERE target=NEW.target AND action='run.document_extraction.cancel'"
        if fault == "terminal"
        else "UPDATE hoimsystem_ai_run SET input_tokens=999 WHERE run_id=NEW.target"
    )
    db.execute(text(f"CREATE TRIGGER document_accept_fault AFTER INSERT ON hoimsystem_ai_audit_event WHEN NEW.action='{action}' BEGIN {effect}; END"))
    db.commit()
    response = await async_client.post(f"/api/ai/runs/{run_id}/cancel", headers=headers)
    assert response.status_code == 409, response.text
    db.expire_all()
    run = db.get(AIRun, run_id)
    assert run.status == "queued" and run.result_json == "{}"
    assert run.input_tokens == 0 and run.output_tokens == 0 and run.latency_ms is None
    assert db.query(AIAuditEvent).filter_by(target=run_id).count() == before
