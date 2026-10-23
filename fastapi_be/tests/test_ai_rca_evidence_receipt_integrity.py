"""A lost exact usage FK must never turn a settled task back into pending."""

import pytest
from fastapi import HTTPException
from sqlalchemy import inspect, text

from app import database
from app.ai import rca_evidence_cancellation as cancellation
from app.ai import rca_evidence_receipts as receipts
from app.ai import runtime
from app.ai.models import AIAuditEvent
from tests.test_ai_rca_evidence_attempts import claimed
from tests.test_ai_rca_evidence_configuration import configured
from tests.test_ai_rca_evidence_execution import provider_service
from tests.test_ai_rca_evidence_execution import synthetic_host as synthetic_host
from tests.test_ai_rca_evidence_grants import grant_case as grant_case
from tests.test_ai_rca_evidence_pipeline import claim_http_task, queue, tracked_factory
from tests.test_ai_rca_evidence_pipeline import pipeline as pipeline
from tests.test_ai_rca_evidence_receipts import dispatched, settle
from tests.test_ai_rca_evidence_storage import no_task_text


def settled(case, phase):
    db = case["db"]
    if phase == "unclaimed_zero":
        stored, _, _ = configured(case)
        identifier = inspect(stored.run).identity[0]
    else:
        proof, _ = claimed(case) if phase == "claimed_zero" else dispatched(case)
        identifier = proof.run_id
    if phase == "failed_paid":
        settle(db, proof)
    else:
        cancellation.stage_cancel(db, case["actor"], identifier)
        if phase == "cancelled_paid":
            settle(db, proof)
    db.commit()
    return identifier


def replace_usage_fk(db, identifier, value):
    db.execute(text("UPDATE hoimsystem_ai_rca_evidence_run_artifact SET usage_event_id=:value WHERE run_id=:id"), {"value": value, "id": identifier})
    db.commit()


@pytest.mark.parametrize("phase", ["failed_paid", "cancelled_paid", "unclaimed_zero", "claimed_zero"])
def test_erased_settled_usage_fk_is_rejected_without_task_text_or_new_accounting(grant_case, phase):
    case, db = grant_case, grant_case["db"]
    identifier = settled(case, phase)
    original = receipts.technical_header(db, identifier)
    original_pk = original.artifact["usage_event_id"]
    assert original_pk is not None and receipts.read_receipt(db, original) is not None
    replace_usage_fk(db, identifier, None)
    try:
        attempt = receipts.technical_header(db, identifier)
        before = db.query(AIAuditEvent.event_id).count()
        with pytest.raises(HTTPException) as failure:
            no_task_text(db, lambda: receipts.read_receipt(db, attempt))
        assert failure.value.status_code == 409
        with pytest.raises(HTTPException) as failure:
            if attempt.claim is None:
                receipts.stage_unclaimed_terminal(db, identifier, status="cancelled", error_code="TASK_CANCELLED")
            else:
                receipts.stage_terminal(
                    db,
                    attempt.claim,
                    dispatch_event_id=attempt.artifact["dispatch_event_id"],
                    usage=receipts.RcaUsageReceipt(input_tokens=0, output_tokens=0, complete=True, model_call_attempted=False),
                    status="cancelled",
                    error_code="TASK_CANCELLED",
                    latency_ms=0,
                )
        assert failure.value.status_code == 409 and db.query(AIAuditEvent.event_id).count() == before
    finally:
        db.rollback()
        replace_usage_fk(db, identifier, original_pk)
    assert receipts.read_receipt(db, receipts.technical_header(db, identifier)) is not None


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel_paid", [False, True])
async def test_actual_main_paid_task_erased_receipt_fk_cannot_be_returned_as_pending(async_client, pipeline, monkeypatch, cancel_paid):
    setup, db = pipeline, pipeline["db"]
    identifier, _, _ = await queue(async_client, setup)
    claim = claim_http_task(db, identifier)
    active = []
    monkeypatch.setattr(database, "SessionLocal", tracked_factory(setup["engine"], active))

    async def reply(body):
        if cancel_paid:
            response = await async_client.post(f"/api/ai/runs/{identifier}/cancel", headers=setup["headers"])
            assert response.status_code == 200 and response.json()["data"]["receipt_pending"] is True, response.text
        else:
            body["choices"][0]["message"]["content"] = "not an RCA JSON draft"
        return body

    transport, calls = provider_service("chat", reply, active)
    db.close()
    await runtime.execute_claimed(*claim, transport=transport)
    assert len(calls) == 1 and not active
    original = receipts.technical_header(db, identifier)
    paid = receipts.read_receipt(db, original)
    assert paid.status == ("cancelled" if cancel_paid else "failed")
    assert (paid.usage.input_tokens, paid.usage.output_tokens) == (11, 13)
    original_pk = original.artifact["usage_event_id"]
    replace_usage_fk(db, identifier, None)
    try:
        response = await async_client.get(f"/api/ai/runs/{identifier}", headers=setup["headers"])
        assert response.status_code == 409, response.text
    finally:
        db.rollback()
        replace_usage_fk(db, identifier, original_pk)
    response = await async_client.get(f"/api/ai/runs/{identifier}", headers=setup["headers"])
    assert response.status_code == 200 and response.json()["data"]["usage_receipt"]["input_tokens"] == 11, response.text
