"""Actual variable shared worker retries retain source/permission/result bindings."""
# ruff: noqa: F401,F811 -- original pytest fixture names retain their dependency graph.

import json

import httpx
import pytest

from app.ai import research_variables_result_storage as results
from app.ai import research_variables_task_reader as reader
from app.ai import runtime
from app.ai.research_variables_task_contract import VariableTaskSource, canonical
from tests.ai_admin_usage_assertions import assert_exact_usage_event
from tests.ai_retry_native_assertions import RecoverAfterTwoFailures, assert_unknown, business_fingerprint
from tests.test_ai_research_variables_configuration import configured
from tests.test_ai_research_variables_pipeline import main_case, queued_task
from tests.test_ai_research_variables_task_context import research_case, task_factory
from tests.test_ai_research_variables_task_result import draft, envelope


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ("chat", "responses"))
async def test_variables_shared_worker_recovers_three_attempts_and_reads_exact_nullable_result(async_client, db_session, main_case, kind):
    value = main_case
    value["provider"].kind, value["provider"].max_attempts = kind, 3
    db_session.commit()
    before = business_fingerprint(db_session)
    queued = await queued_task(async_client, value["admin"], value["selection"])
    identifier = queued["run_id"]
    claim = runtime.claim_next_run(db_session)
    assert claim and claim[0] == identifier
    loaded = reader.load_task(db_session, value["case"]["admin_user"], identifier)
    source_before = loaded.source
    db_session.rollback()
    replies = []

    def respond(request):
        body = json.loads(request.content)
        public = json.loads(body["messages"][1]["content"] if kind == "chat" else body["input"][0]["content"])
        source = VariableTaskSource.model_validate(public["research_variable_source"])
        replies.append(source)
        return httpx.Response(200, json=envelope(kind, canonical(draft(source)), True))

    transport = RecoverAfterTwoFailures(httpx.MockTransport(respond))
    await runtime.execute_claimed(*claim, transport=transport)
    detail_response = await async_client.get("/api/ai/runs/" + identifier, headers=value["admin"])
    assert detail_response.status_code == 200, detail_response.text
    detail = detail_response.json()["data"]
    assert detail["status"] == "succeeded", (detail["error_code"], detail["error_message"])
    assert_unknown(detail["usage_receipt"])
    result = results.result_piece(db_session, value["case"]["admin_user"], identifier)
    assert result["reference"] == detail["result_reference"]
    assert result["result"]["research_variable_extraction"]["literal_draft"]["candidates"] == draft(source_before)["candidates"]
    assert reader.load_task(db_session, value["case"]["admin_user"], identifier).source == source_before
    assert business_fingerprint(db_session) == before and transport.attempts == 3 and len(replies) == 1
    assert_exact_usage_event(db_session, identifier, "research_variables", detail["usage_receipt"])
