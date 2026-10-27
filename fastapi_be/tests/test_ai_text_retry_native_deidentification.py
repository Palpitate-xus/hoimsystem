"""Actual shared deidentification retry cannot apply candidates or export data."""
# ruff: noqa: F401,F811 -- original pytest fixture names retain their dependency graph.

from types import SimpleNamespace

import pytest

from app.ai import deidentification_storage as storage
from app.ai import runtime
from app.ai.deidentification_models import AIDeidentificationExportRelease, AIDeidentificationReview
from app.ai.deidentification_receipts import usage_receipt
from app.ai.models import AIRun
from tests.ai_admin_usage_assertions import assert_exact_usage_event
from tests.ai_retry_native_assertions import RecoverAfterTwoFailures, assert_unknown, business_fingerprint
from tests.test_ai_deidentification_runtime import model, queue
from tests.test_ai_deidentification_storage import task_case
from tests.test_ai_research_cohort_sources import research_case


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ("chat", "responses"))
async def test_deidentification_shared_worker_recovers_three_attempts_without_applying_or_exporting(task_case, kind):
    case, db = task_case, task_case["db"]
    case["provider"].kind, case["provider"].max_attempts = kind, 3
    db.commit()
    before = business_fingerprint(db)
    identifier = queue(case)
    claim = runtime.claim_next_run(db)
    assert claim.run_id == identifier
    db.rollback()
    packets = []
    transport = RecoverAfterTwoFailures(model({**case, "provider": SimpleNamespace(kind=kind)}, packets=packets))
    await runtime.execute_claimed(identifier, claim.lease_token, deidentification_claim_event_id=claim.claim_event_id, transport=transport)
    db.expire_all()
    run = db.get(AIRun, identifier)
    assert run.status == "succeeded", (run.error_code, run.error_message)
    loaded, result = storage.load_result(db, case["actor"], identifier)
    assert result["draft"]["candidates"][0]["quote"] == "张三"
    assert loaded[3]["public_source"] == case["source"]["public_source"]
    usage = usage_receipt(db, run)
    assert_unknown(usage)
    assert db.query(AIDeidentificationReview).count() == db.query(AIDeidentificationExportRelease).count() == 0
    assert business_fingerprint(db) == before and transport.attempts == 3 and len(packets) == 1
    assert_exact_usage_event(db, identifier, "deidentification", usage)
