"""Actual coding worker retries retain accepted literal proof and unknown costs."""
# ruff: noqa: F401,F811 -- original pytest fixture names retain their dependency graph.

import json

import pytest

from app.ai import coding_evidence_storage, runtime
from app.ai.models import AIAuditEvent, AIRun
from tests.ai_retry_native_assertions import RecoverAfterTwoFailures, assert_unknown, business_fingerprint
from tests.test_ai_coding_evidence_pipeline import case, clear_coding_tasks, coding_case, draft_transport, pipeline_case, queue


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ("chat", "responses"))
async def test_coding_shared_worker_recovers_three_attempts_with_original_source_and_usage_audit(async_client, auth_headers, db_session, pipeline_case, kind):
    case = pipeline_case
    case["provider"].kind, case["provider"].max_attempts = kind, 3
    db_session.commit()
    before = business_fingerprint(db_session)
    claim, _ = await queue(async_client, auth_headers(case["doctor_user"].username), db_session, case)
    source_hash = case["source"].content_hash
    db_session.rollback()
    final, packets = draft_transport(case)
    transport = RecoverAfterTwoFailures(final)
    await runtime.execute_claimed(*claim, transport=transport)
    db_session.expire_all()
    run = db_session.get(AIRun, claim[0])
    assert run.status == "succeeded", (run.error_code, run.error_message)
    result = coding_evidence_storage.expand_result(db_session, run)
    assert result["coding_analysis"]["claims"][0]["citations"][0]["quote"] == case["home"].operation_summary
    assert run.input_tokens is run.output_tokens is None
    event = db_session.query(AIAuditEvent).filter_by(target=run.run_id, action="run.text_model.usage").one()
    usage = json.loads(event.detail_json)
    assert_unknown(usage)
    assert usage["attempts"] == 3 and usage["max_attempts"] == 3
    assert db_session.query(AIAuditEvent).filter_by(target=run.run_id, action="run.coding_result.accept").one().event_id != event.event_id
    assert case["source"].content_hash == source_hash and business_fingerprint(db_session) == before
    assert transport.attempts == 3 and len(packets) == 1
