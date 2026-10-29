"""Operations tasks preserve usage while rejecting revoked execution rights."""

import pytest

from app.ai import operations_support_execution as execution
from app.ai import operations_support_runtime as runtime
from app.ai.operations_support_run_models import AIOperationsRunResult
from tests.test_ai_native_permission_guards import restore_actor_authority as restore_actor_authority
from tests.test_ai_native_permission_guards import revoke
from tests.test_ai_operations_support_configuration import actors as actors
from tests.test_ai_operations_support_configuration import configured as configured
from tests.test_ai_operations_support_configuration import source as source
from tests.test_ai_operations_support_execution import current_receipt, provider_service, setup
from tests.test_ai_operations_support_execution import remove_test_observers as remove_test_observers


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["feature_revoked", "disabled", "role"])
@pytest.mark.parametrize("phase", ["queued", "before_dispatch", "inflight"])
async def test_operations_policy_loss_is_checked_before_claim_dispatch_and_accept(configured, change, phase):
    value = setup(configured, claim=phase != "queued")

    def change_policy():
        with value["factory"]() as db:
            revoke(db, value["owner"], change, "operations_support")

    if phase != "inflight":
        change_policy()
    if phase == "queued":
        with value["factory"]() as db:
            assert runtime.claim_operations_run(db, value["identifier"]) is None
    else:
        def reply(body):
            assert phase == "inflight"
            change_policy()
            return body

        transport, calls = provider_service(value, callback=reply)
        await execution.execute_operations_claimed(value["identifier"], value["lease"], session_factory=value["factory"], transport=transport)
        assert len(calls) == (1 if phase == "inflight" else 0)
    actual = current_receipt(value)
    assert actual.status == "failed"
    assert actual.usage.model_call_attempted is (phase == "inflight")
    assert (actual.usage.input_tokens, actual.usage.output_tokens) == ((11, 13) if phase == "inflight" else (0, 0))
    with value["factory"]() as db:
        assert db.query(AIOperationsRunResult).filter_by(run_id=value["identifier"]).count() == 0
