"""Unexpected delivery errors cannot be turned into proven unattempted zero."""

import httpx
import pytest

from app.ai import clinical_training_attempts as attempts
from app.ai import clinical_training_execution as execution
from app.ai import clinical_training_receipts as receipts
from app.ai import clinical_training_runtime as runtime
from app.ai.clinical_training_run_models import AITrainingRunResult
from tests.test_ai_clinical_training_configuration import configured as configured
from tests.test_ai_clinical_training_practice import practice_case as practice_case
from tests.test_ai_clinical_training_reference_sql import reference_case as reference_case
from tests.test_ai_clinical_training_reviews import reviewed_case as reviewed_case
from tests.test_ai_clinical_training_runtime import sessions
from tests.test_ai_clinical_training_storage import stored as stored


@pytest.mark.asyncio
@pytest.mark.parametrize("boundary", ["gateway", "worker"])
@pytest.mark.parametrize("failure", [RuntimeError, AssertionError])
async def test_original_committed_dispatch_unexpected_failure_preserves_unknown_counts_without_replay(stored, monkeypatch, boundary, failure):
    case, key = stored
    db = case["db"]
    lease = runtime.claim_training_run(db, key)
    factory, active, _ = sessions(db)
    calls = []

    async def interrupted(*args, **kwargs):
        assert not active and not db.in_transaction()
        calls.append(True)
        raise failure("synthetic interrupted delivery, no actual token receipt")

    if boundary == "worker":
        monkeypatch.setattr(execution.gateway, "generate_training_feedback", interrupted)
    transport = httpx.MockTransport(interrupted)
    await execution.execute_training_claimed(key, lease, session_factory=factory, transport=transport)
    actual = attempts.technical_header(db, key)
    receipt = receipts.read_receipt(db, actual)
    assert actual.header["status"] == "failed" and actual.dispatch is not None
    assert receipt.usage.input_tokens is receipt.usage.output_tokens is None
    assert receipt.usage.model_call_attempted is (True if boundary == "gateway" else None)
    assert receipt.error_code == ("TRAINING_DELIVERY_INTERRUPTED" if boundary == "gateway" else "WORKER_INTERRUPTED")
    assert db.query(AITrainingRunResult).filter_by(run_id=key).count() == 0
    assert len(calls) == 1 and not active
    db.commit()
    await execution.execute_training_claimed(key, lease, session_factory=factory, transport=transport)
    assert len(calls) == 1
