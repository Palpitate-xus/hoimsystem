"""Training tasks recheck administrative permissions at every execution stage."""

import httpx
import pytest

from app.ai import clinical_training_attempts as attempts
from app.ai import clinical_training_execution as execution
from app.ai import clinical_training_receipts as receipts
from app.ai import clinical_training_runtime as runtime
from app.ai import clinical_training_storage as storage
from app.ai.clinical_training_run_models import AITrainingRunResult
from tests.test_ai_clinical_training_configuration import configured as configured
from tests.test_ai_clinical_training_gateway import envelope
from tests.test_ai_clinical_training_practice import practice_case as practice_case
from tests.test_ai_clinical_training_reference_sql import reference_case as reference_case
from tests.test_ai_clinical_training_reviews import reviewed_case as reviewed_case
from tests.test_ai_clinical_training_runtime import sessions
from tests.test_ai_clinical_training_storage import stored as stored
from tests.test_ai_clinical_training_task_contract import draft
from tests.test_ai_native_permission_guards import restore_actor_authority as restore_actor_authority
from tests.test_ai_native_permission_guards import revoke


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["feature_revoked", "disabled", "role"])
@pytest.mark.parametrize("phase", ["queued", "before_dispatch", "inflight"])
async def test_current_policy_loss_never_calls_or_accepts_training_result(stored, change, phase):
    case, identifier = stored
    db, actor_id = case["db"], case["actor"].user_id
    source = storage.load_artifact(db, case["actor"], identifier)[2]
    db.commit()
    if phase == "queued":
        revoke(db, actor_id, change, "clinical_training")
        assert runtime.claim_training_run(db, identifier) is None
    else:
        lease = runtime.claim_training_run(db, identifier)
        assert lease
        factory, _, _ = sessions(db)
        calls = []
        if phase == "before_dispatch":
            revoke(db, actor_id, change, "clinical_training")

        async def reply(request):
            calls.append(request)
            assert phase == "inflight"
            revoke(db, actor_id, change, "clinical_training")
            return httpx.Response(200, json=envelope("chat", draft(source.model_dump(mode="json")), {"prompt_tokens": 11, "completion_tokens": 7}))

        await execution.execute_training_claimed(identifier, lease, session_factory=factory, transport=httpx.MockTransport(reply))
        assert len(calls) == (1 if phase == "inflight" else 0)
    actual = attempts.technical_header(db, identifier)
    receipt = receipts.read_receipt(db, actual)
    assert actual.header["status"] == "failed"
    assert db.query(AITrainingRunResult).filter_by(run_id=identifier).count() == 0
    assert receipt.usage.model_call_attempted is (phase == "inflight")
    assert (receipt.usage.input_tokens, receipt.usage.output_tokens) == ((11, 7) if phase == "inflight" else (0, 0))
