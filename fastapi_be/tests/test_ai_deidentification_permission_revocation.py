"""Deidentification retains exact receipts when platform AI access is revoked."""

import pytest

from app.ai import deidentification_runtime as runtime
from app.ai.deidentification_run_models import AIDeidentificationRunResult
from app.ai.models import AIRun
from tests.test_ai_deidentification_runtime import claim, model, queue
from tests.test_ai_deidentification_storage import task_case as task_case
from tests.test_ai_native_permission_guards import restore_actor_authority as restore_actor_authority
from tests.test_ai_native_permission_guards import revoke
from tests.test_ai_research_cohort_sources import research_case as research_case


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["feature_revoked", "disabled", "role"])
@pytest.mark.parametrize("phase", ["before_dispatch", "inflight"])
async def test_deidentification_policy_rechecked_before_call_and_result(task_case, change, phase):
    case, db = task_case, task_case["db"]
    identifier = queue(case)
    claimed = claim(case, identifier)
    actor_id = case["actor"].user_id
    calls = []

    def change_policy():
        revoke(db, actor_id, change, "deidentification")

    if phase == "before_dispatch":
        change_policy()
    await runtime.execute_deidentification_claimed(*claimed, transport=model(case, mutate=change_policy if phase == "inflight" else None, packets=calls))
    db.expire_all()
    run = db.get(AIRun, identifier)
    assert run.status == "failed"
    assert len(calls) == (1 if phase == "inflight" else 0)
    assert (run.input_tokens, run.output_tokens) == ((11, 13) if phase == "inflight" else (0, 0))
    result = db.get(AIDeidentificationRunResult, identifier)
    assert result.accept_event_id is None and result.result_json is None
