"""Variable extraction preserves paid use but cannot accept revoked results."""

import json

import httpx
import pytest
from sqlalchemy.orm import sessionmaker

from app.ai import research_variables_execution as execution
from app.ai import research_variables_receipts as receipts
from app.ai.research_variables_run_models import AIResearchVariableRunResult
from app.ai.research_variables_task_contract import VariableTaskSource, canonical
from tests.test_ai_native_permission_guards import restore_actor_authority as restore_actor_authority
from tests.test_ai_native_permission_guards import revoke
from tests.test_ai_research_variables_attempts import claimed
from tests.test_ai_research_variables_configuration import configured as configured
from tests.test_ai_research_variables_task_context import research_case as research_case
from tests.test_ai_research_variables_task_context import task_factory as task_factory
from tests.test_ai_research_variables_task_reader import actual_task as actual_task
from tests.test_ai_research_variables_task_result import draft, envelope


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["feature_revoked", "disabled", "role"])
@pytest.mark.parametrize("phase", ["before_dispatch", "inflight"])
async def test_variable_policy_rechecked_before_call_and_result(db_session, actual_task, change, phase):
    case, _, _, _ = actual_task
    claim = claimed(db_session, actual_task)
    factory = sessionmaker(bind=db_session.bind, expire_on_commit=False)
    db_session.rollback()
    calls = []

    def change_policy():
        with factory() as db:
            revoke(db, claim.requested_by, change, "research_extraction")

    if phase == "before_dispatch":
        change_policy()

    def reply(request):
        calls.append(request)
        source = VariableTaskSource.model_validate(json.loads(json.loads(request.content)["messages"][1]["content"])["research_variable_source"])
        change_policy()
        return httpx.Response(200, json=envelope("chat", canonical(draft(source)), True))

    await execution.execute_research_variables_claimed(claim.run_id, claim.lease, session_factory=factory, transport=httpx.MockTransport(reply))
    task = receipts.technical_task(db_session, claim)
    receipt = receipts.verify_receipt(db_session, task).receipt
    assert task.run.status == "failed"
    assert len(calls) == (1 if phase == "inflight" else 0)
    assert receipt.model_call_attempted is (phase == "inflight")
    assert (receipt.input_tokens, receipt.output_tokens) == ((11, 13) if phase == "inflight" else (0, 0))
    assert db_session.query(AIResearchVariableRunResult).filter_by(run_id=claim.run_id).count() == 0
