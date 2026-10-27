"""Accepted native drafts retain actual unknown usage after HTTP retries."""

import httpx
import pytest

from app.ai import document_change_storage as change_storage
from app.ai import document_extraction_runtime as documents
from app.ai import drug_label_runtime as labels
from app.ai import runtime
from app.ai.models import AIRun
from tests.ai_admin_usage_assertions import assert_exact_usage_event
from tests.test_ai_charge_reconciliation_execution import prepared as charge_prepared
from tests.test_ai_charge_reconciliation_execution import saved as charge_saved
from tests.test_ai_charge_reconciliation_gateway import envelope as charge_envelope
from tests.test_ai_charge_reconciliation_sources import charge_case as charge_case
from tests.test_ai_document_change_runtime import claim as change_claim
from tests.test_ai_document_change_runtime import model_transport as change_model_transport
from tests.test_ai_document_change_runtime import pipeline as _change_pipeline
from tests.test_ai_document_change_runtime import queued as change_queued
from tests.test_ai_document_change_sources import change_case as change_case
from tests.test_ai_document_change_storage import remove_prior_tasks as remove_prior_tasks
from tests.test_ai_document_extraction_pipeline import document_pipeline as document_pipeline
from tests.test_ai_document_extraction_pipeline import model_transport, queue
from tests.test_ai_drug_label_gateway import envelope as label_envelope
from tests.test_ai_drug_label_runtime import case as _label_runtime_case
from tests.test_ai_drug_label_runtime import queued as label_queued
from tests.test_ai_drug_label_runtime import stored as label_stored
from tests.test_ai_drug_label_runtime import view as label_view
from tests.test_ai_drug_label_sources import label_case as label_case
from tests.test_ai_satisfaction_gateway import envelope
from tests.test_ai_satisfaction_runtime import prepared, saved
from tests.test_ai_satisfaction_runtime import runtime_case as runtime_case
from tests.test_ai_satisfaction_sources import satisfaction_case as satisfaction_case

change_pipeline = _change_pipeline
label_runtime_case = _label_runtime_case


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ("chat", "responses"))
async def test_document_retry_success_has_exact_nullable_usage_event_and_valid_source_result(async_client, auth_headers, document_pipeline, kind):
    case = document_pipeline
    case["provider"].kind = kind
    case["provider"].max_attempts = 3
    case["db"].commit()
    claim, _queued = await queue(async_client, auth_headers(case["actor"].username), case)
    final, _packets = model_transport(case)
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(503) if len(calls) < 3 else final.handle_request(request)

    await runtime.execute_claimed(*claim, transport=httpx.MockTransport(respond))
    case["db"].expire_all()
    run = case["db"].get(AIRun, claim[0])
    assert run.status == "succeeded", (run.error_code, run.error_message)
    usage = documents.usage_receipt(case["db"], run)
    assert usage == dict(input_tokens=None, output_tokens=None, complete=False, model_call_attempted=True)
    assert_exact_usage_event(case["db"], run.run_id, "document", usage)
    assert documents.load_result(case["db"], run)["document_extraction"]["spans"][0]["quote"] == case["original"].snapshot.text
    assert len(calls) == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ("chat", "responses"))
async def test_satisfaction_retry_success_preserves_independent_usage_and_acceptance_audits(runtime_case, kind):
    case = runtime_case
    case["provider"].kind = kind
    case["provider"].max_attempts = 3
    case["db"].commit()
    item, calls = prepared(case), []

    def respond(request):
        calls.append(request)
        return httpx.Response(503) if len(calls) < 3 else httpx.Response(200, json=envelope(kind, item["draft"]))

    await runtime.execute_claimed(item["run_id"], item["lease"], transport=httpx.MockTransport(respond))
    run, result, usage = saved(case, item)
    assert run.status == "succeeded", (run.error_code, run.error_message)
    assert result["satisfaction_analysis"] == item["draft"]
    assert usage == dict(input_tokens=None, output_tokens=None, complete=False, model_call_attempted=True)
    assert_exact_usage_event(case["db"], run.run_id, "satisfaction", usage)
    assert len(calls) == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ("chat", "responses"))
async def test_charge_retry_success_retains_unknown_usage_and_exact_acceptance_receipt(charge_case, kind):
    case = charge_case
    item, calls = charge_prepared(case, kind=kind), []

    def respond(request):
        calls.append(request)
        return httpx.Response(503) if len(calls) < 3 else httpx.Response(200, json=charge_envelope(kind, item["draft"]))

    await runtime.execute_claimed(item["run_id"], item["lease"], transport=httpx.MockTransport(respond))
    run, result, usage = charge_saved(case, item)
    assert run.status == "succeeded", (run.error_code, run.error_message)
    assert result["charge_analysis"] == item["draft"]
    assert usage == dict(input_tokens=None, output_tokens=None, complete=False, model_call_attempted=True)
    assert_exact_usage_event(case["db"], run.run_id, "charge", usage)
    assert len(calls) == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ("chat", "responses"))
async def test_document_change_retry_success_retains_unknown_usage_and_source_bound_result(change_pipeline, kind):
    case = change_pipeline
    case["provider"].kind = kind
    case["provider"].max_attempts = 3
    case["db"].commit()
    run_id = change_queued(case)
    claimed = change_claim(case, run_id)
    final, packets, close = change_model_transport(case)
    calls = []

    class TransientFailures(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):
            calls.append(request)
            return httpx.Response(503) if len(calls) < 3 else await final.handle_async_request(request)

    try:
        await runtime.execute_claimed(*claimed, transport=TransientFailures())
    finally:
        close()
    case["db"].expire_all()
    run = case["db"].get(AIRun, run_id)
    assert run.status == "succeeded", (run.error_code, run.error_message)
    usage = change_storage.usage_receipt(case["db"], run).model_dump(mode="json")
    assert usage == dict(input_tokens=None, output_tokens=None, complete=False, model_call_attempted=True)
    result = change_storage.expand_result(case["db"], case["actor"], run)
    assert result.document_change.changes[0].baseline_spans[0].quote == case["source"].baseline.text[:1]
    assert_exact_usage_event(case["db"], run_id, "document_change", usage)
    assert len(calls) == 3 and len(packets) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ("chat", "responses"))
async def test_drug_label_retry_success_retains_unknown_usage_and_three_original_audits(label_runtime_case, kind):
    case = label_runtime_case
    case.provider.kind = kind
    case.provider.max_attempts = 3
    case.db.commit()
    label_queued(case)
    before = label_stored(case)
    start = before.public_source.text.index("合成成分")
    reply = {"fields": [{"field": "composition", "spans": [{"start": start, "end": start + 4, "quote": "合成成分"}], "review_question": "请药师逐字核对该字段与原文条件。"}]}
    case.db.rollback()
    lease = labels.claim_drug_label_run(case.db, case.id)
    assert lease
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(503) if len(calls) < 3 else httpx.Response(200, json=label_envelope(kind, reply))

    await runtime.execute_claimed(case.id, lease, transport=httpx.MockTransport(respond))
    after = label_stored(case)
    assert after.run.status == "succeeded", (after.run.error_code, after.run.error_message)
    data = label_view(case)
    usage = data["usage_receipt"]
    assert usage["input_tokens"] is usage["output_tokens"] is None and usage["model_call_attempted"] is True
    assert data["result"]["drug_label_extraction"]["fields"][0]["spans"][0]["quote"] == "合成成分"
    assert len({after.artifact.create_event_id, after.artifact.receipt_event_id, after.artifact.accept_event_id}) == 3
    assert_exact_usage_event(case.db, case.id, "drug_label", usage)
    assert len(calls) == 3
