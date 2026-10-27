"""Accepted native drafts retain actual unknown usage after HTTP retries."""

import httpx
import pytest

from app.ai import document_extraction_runtime as documents
from app.ai import runtime
from app.ai.models import AIRun
from tests.ai_admin_usage_assertions import assert_exact_usage_event
from tests.test_ai_document_extraction_pipeline import document_pipeline as document_pipeline
from tests.test_ai_document_extraction_pipeline import model_transport, queue
from tests.test_ai_satisfaction_gateway import envelope
from tests.test_ai_satisfaction_runtime import prepared, saved
from tests.test_ai_satisfaction_runtime import runtime_case as runtime_case
from tests.test_ai_satisfaction_sources import satisfaction_case as satisfaction_case


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
