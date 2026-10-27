"""Actual shared research retry preserves original scope, evaluation and receipts."""
# ruff: noqa: F401,F811 -- original pytest fixture names retain their dependency graph.

import httpx
import pytest

from app import database
from app.ai import runtime
from app.ai.models import AIProvider, AIRun
from app.ai.research_cohort_receipts import read_usage_event
from app.ai.research_cohort_runtime import read_research_part
from tests.ai_admin_usage_assertions import assert_exact_usage_event
from tests.ai_retry_native_assertions import RecoverAfterTwoFailures, assert_unknown, business_fingerprint
from tests.test_ai_research_cohort_execution import created_claim, reply, runtime_case
from tests.test_ai_research_cohort_storage import artifact_foreign_keys, configured, research_case, storage_rows


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ("chat", "responses"))
async def test_research_shared_worker_recovers_three_attempts_and_reads_bound_evaluation(runtime_case, monkeypatch, kind):
    case, db = runtime_case, runtime_case["db"]
    provider = db.get(AIProvider, case["values"]["provider_id"])
    provider.kind, provider.max_attempts = kind, 3
    db.commit()
    before = business_fingerprint(db)
    identifier, claim = created_claim(case)
    source_before = read_research_part(db, case["actor"], identifier, "source")
    db.rollback()
    monkeypatch.setattr(database, "SessionLocal", case["factory"])
    transport = RecoverAfterTwoFailures(httpx.MockTransport(lambda request: httpx.Response(200, json=reply(case["source"], kind))))
    await runtime.execute_claimed(identifier, claim.lease_token, research_claim_event_id=claim.claim_event_id, transport=transport)
    db.expire_all()
    run = db.get(AIRun, identifier)
    assert run.status == "succeeded", (run.error_code, run.error_message)
    result = read_research_part(db, case["actor"], identifier, "result")
    assert result["deterministic_evaluation"]["counts"] == case["source"]["counts"]
    usage = read_usage_event(db, identifier)["usage"]
    assert_unknown(usage)
    assert read_research_part(db, case["actor"], identifier, "source") == source_before
    assert business_fingerprint(db) == before and transport.attempts == 3
    assert_exact_usage_event(db, identifier, "research_cohort", usage)
