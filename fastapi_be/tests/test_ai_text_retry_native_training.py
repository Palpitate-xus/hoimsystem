"""Shared training retry reuses actual source authority and audited draft storage."""
# ruff: noqa: F401,F811 -- original pytest fixture names retain their dependency graph.

import httpx
import pytest

from app.ai import clinical_training_attempts as attempts
from app.ai import clinical_training_receipts as receipts
from app.ai import clinical_training_result_storage as results
from app.ai import clinical_training_runtime as training
from app.ai import clinical_training_storage as storage
from app.ai import runtime
from tests.ai_admin_usage_assertions import assert_exact_usage_event
from tests.ai_retry_native_assertions import RecoverAfterTwoFailures, assert_unknown, business_fingerprint
from tests.test_ai_clinical_training_configuration import configured, selected
from tests.test_ai_clinical_training_gateway import envelope
from tests.test_ai_clinical_training_practice import practice_case
from tests.test_ai_clinical_training_reference_sql import reference_case
from tests.test_ai_clinical_training_reviews import reviewed_case
from tests.test_ai_clinical_training_storage import stored
from tests.test_ai_clinical_training_task_contract import draft


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ("chat", "responses"))
async def test_training_shared_worker_recovers_three_attempts_without_changing_source_or_grade(stored, kind):
    case, _original_seed = stored
    db = case["db"]
    case["provider"].kind, case["provider"].max_attempts, case["provider"].api_key_env = kind, 3, ""
    db.commit()
    before = business_fingerprint(db)
    identifier = training.create_training_run(db, case["actor"], selected(case))
    source = storage.load_artifact(db, case["actor"], identifier)[2]
    db.commit()
    lease = training.claim_training_run(db, identifier)
    assert lease
    db.rollback()
    transport = RecoverAfterTwoFailures(httpx.MockTransport(lambda request: httpx.Response(200, json=envelope(kind, draft(source.model_dump(mode="json")), {"prompt_tokens": 11, "completion_tokens": 7} if kind == "chat" else {"input_tokens": 11, "output_tokens": 7}))))
    await runtime.execute_claimed(identifier, lease, transport=transport)
    actual = attempts.technical_header(db, identifier)
    assert actual.header["status"] == "succeeded", actual.header
    receipt = receipts.read_receipt(db, actual)
    assert_unknown(receipt.usage)
    result = results.load_result(db, case["actor"], identifier)
    assert result.explanations[0].evidence[0].quote == source.feedback.questions[0].reviewed_rationale
    assert storage.load_artifact(db, case["actor"], identifier)[2] == source
    assert business_fingerprint(db) == before and transport.attempts == 3
    assert_exact_usage_event(db, identifier, "clinical_training", receipt.usage.model_dump(mode="json"))
