"""Shared operations retry keeps original reviewed text and separate receipts."""
# ruff: noqa: F401,F811 -- original pytest fixture names retain their dependency graph.

import pytest

from app import database
from app.ai import operations_support_result_storage as results
from app.ai import operations_support_storage as storage
from app.ai import runtime
from app.models import User
from tests.ai_admin_usage_assertions import assert_exact_usage_event
from tests.ai_retry_native_assertions import RecoverAfterTwoFailures, assert_unknown, business_fingerprint
from tests.test_ai_operations_support_configuration import actors, configured, source
from tests.test_ai_operations_support_execution import current_receipt, provider_service, remove_test_observers, setup


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ("chat", "responses"))
async def test_operations_shared_worker_recovers_three_attempts_and_reads_original_draft(configured, monkeypatch, kind):
    value = setup(configured, kind)
    monkeypatch.setattr(database, "SessionLocal", value["factory"])
    with value["factory"]() as db:
        actor = db.get(User, value["owner"])
        before = business_fingerprint(db)
        source_before = storage.load_artifact(db, actor, value["identifier"])[2]
    final, calls = provider_service(value, kind)
    transport = RecoverAfterTwoFailures(final)
    await runtime.execute_claimed(value["identifier"], value["lease"], transport=transport)
    receipt = current_receipt(value)
    assert receipt.status == "succeeded", receipt
    assert_unknown(receipt.usage)
    with value["factory"]() as db:
        actor = db.get(User, value["owner"])
        result = results.load_result(db, actor, value["identifier"])
        assert result.observations[0].evidence[0].quote == "😀\r\n\x00"
        assert storage.load_artifact(db, actor, value["identifier"])[2] == source_before
        assert business_fingerprint(db) == before
        assert_exact_usage_event(db, value["identifier"], "operations_support", receipt.usage.model_dump(mode="json"))
    assert transport.attempts == 3 and len(calls) == 1
