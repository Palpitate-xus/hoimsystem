"""Actual RCA shared worker retries retain leased hypotheses and nullable usage."""
# ruff: noqa: F401,F811 -- original pytest fixture names retain their dependency graph.

import pytest

from app import database
from app.ai import rca_evidence_receipts as receipts
from app.ai import rca_evidence_result_storage as results
from app.ai import rca_evidence_storage as storage
from app.ai import runtime
from app.models import User
from tests.ai_admin_usage_assertions import assert_exact_usage_event
from tests.ai_retry_native_assertions import RecoverAfterTwoFailures, assert_unknown, business_fingerprint
from tests.test_ai_rca_evidence_execution import grant_case, provider_service, setup, synthetic_host


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ("chat", "responses"))
async def test_rca_shared_worker_recovers_three_attempts_and_reads_original_literal_hypotheses(grant_case, monkeypatch, kind):
    identifier, lease, owner, _, factory, active, _, _ = setup(grant_case, kind)
    monkeypatch.setattr(database, "SessionLocal", factory)
    with factory() as db:
        actor = db.get(User, owner)
        before = business_fingerprint(db)
        source_before = storage.load_task(db, actor, identifier).source
    final, calls = provider_service(kind, None, active)
    transport = RecoverAfterTwoFailures(final)
    await runtime.execute_claimed(identifier, lease, transport=transport)
    with factory() as db:
        actor = db.get(User, owner)
        task = storage.load_task(db, actor, identifier)
        assert task.run.status == "succeeded", (task.run.error_code, task.run.error_message)
        receipt = receipts.read_receipt(db, receipts.technical_header(db, identifier))
        assert_unknown(receipt.usage)
        result = results.read_result(db, actor, identifier)
        assert result.rca_evidence_draft.hypotheses[0].supporting_quotes[0].quote == source_before.items[0].text
        assert task.source == source_before and business_fingerprint(db) == before
        assert_exact_usage_event(db, identifier, "rca", receipt.usage.model_dump(mode="json"))
    assert transport.attempts == 3 and len(calls) == 1
