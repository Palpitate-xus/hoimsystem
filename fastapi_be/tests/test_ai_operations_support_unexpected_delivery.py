"""Unexpected delivery errors must preserve unknown actual usage after dispatch."""

import httpx
import pytest

from app.ai import operations_support_execution as execution
from app.ai.operations_support_run_models import AIOperationsRunResult
from tests.test_ai_operations_support_configuration import actors as actors
from tests.test_ai_operations_support_configuration import configured as configured
from tests.test_ai_operations_support_configuration import source as source
from tests.test_ai_operations_support_execution import current_receipt, setup
from tests.test_ai_operations_support_execution import remove_test_observers as remove_test_observers


@pytest.mark.asyncio
@pytest.mark.parametrize("boundary", ["gateway", "worker"])
@pytest.mark.parametrize("failure", [RuntimeError, AssertionError])
async def test_original_committed_dispatch_unexpected_failure_preserves_unknown_counts_without_replay(configured, monkeypatch, boundary, failure):
    value = setup(configured)
    calls = []

    async def interrupted(*args, **kwargs):
        assert not value["active"] and not value["connections"]
        calls.append(True)
        raise failure("synthetic interrupted delivery, no actual token receipt")

    if boundary == "worker":
        monkeypatch.setattr(execution.gateway, "generate_operations", interrupted)
    transport = httpx.MockTransport(interrupted)
    await execution.execute_operations_claimed(value["identifier"], value["lease"], session_factory=value["factory"], transport=transport)
    receipt = current_receipt(value)
    assert receipt.status == "failed" and receipt.dispatch_event_id is not None
    assert receipt.usage.input_tokens is receipt.usage.output_tokens is None
    assert receipt.usage.model_call_attempted is (True if boundary == "gateway" else None)
    assert receipt.error_code == ("OPERATIONS_DELIVERY_INTERRUPTED" if boundary == "gateway" else "WORKER_INTERRUPTED")
    with value["factory"]() as db:
        assert db.query(AIOperationsRunResult).filter_by(run_id=value["identifier"]).count() == 0
    assert len(calls) == 1 and not value["active"] and not value["connections"]
    await execution.execute_operations_claimed(value["identifier"], value["lease"], session_factory=value["factory"], transport=transport)
    assert len(calls) == 1
