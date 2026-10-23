"""Actual synthetic Source -> SQL claim/dispatch -> local ASGI -> settlement.

The provider is controlled ASGI, not real model inference. SQL cancellation
state is deliberately controlled here; formal Main cancel tests follow later.
"""

import json
from contextlib import contextmanager
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import event, inspect, text
from sqlalchemy.orm import sessionmaker

from app.ai import research_variables_execution as execution
from app.ai import research_variables_receipts as receipts
from app.ai import research_variables_result_storage as results
from app.ai.models import AIAuditEvent
from app.ai.research_cohort_registry import review_registry_original
from app.ai.research_variables_run_models import AIResearchVariableRunResult
from app.ai.research_variables_task_contract import VariableTaskSource, canonical
from tests.test_ai_research_cohort_contract import BASIS
from tests.test_ai_research_variables_attempts import claimed
from tests.test_ai_research_variables_configuration import configured as configured
from tests.test_ai_research_variables_task_context import research_case as research_case
from tests.test_ai_research_variables_task_context import task_factory as task_factory
from tests.test_ai_research_variables_task_reader import actual_task as actual_task
from tests.test_ai_research_variables_task_result import draft, envelope


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["full", "absent_usage", "partial_usage", "source_loss", "role_loss", "cancel_during_http", "duplicate_after_source_loss", "bad_quote"])
async def test_actual_current_sql_dispatch_has_zero_sql_connections_during_provider_await_and_exact_nullable_result_or_paid_terminal(db_session, actual_task, outcome):
    case, permissions, _, _ = actual_task
    super_id = inspect(case["super_admin_user"]).identity[0]
    claim = claimed(db_session, actual_task)
    factory = sessionmaker(bind=db_session.bind, expire_on_commit=False)
    db_session.rollback()
    active, calls = set(), []

    def checkout(connection, record, proxy):
        active.add(id(record))

    def checkin(connection, record):
        active.discard(id(record))

    app = FastAPI()

    @app.post("/v1/chat/completions")
    async def reply(request: Request):
        assert not active, "The worker retained a SQL transaction/connection during HTTP"
        calls.append(await request.json())
        source = VariableTaskSource.model_validate(json.loads(calls[-1]["messages"][1]["content"])["research_variable_source"])
        if outcome in {"source_loss", "duplicate_after_source_loss"}:
            with factory() as db:
                review_registry_original(db, SimpleNamespace(user_id=super_id), "authorization", permissions[1]["source_record_id"], {"expected_revision": 2, "basis_note": BASIS}, revoke=True)
        elif outcome in {"role_loss", "cancel_during_http"}:
            with factory() as db:
                if outcome == "role_loss":
                    db.execute(text("UPDATE hoimsystem_users SET user_role='nurse' WHERE user_id=:id"), {"id": claim.requested_by})
                else:
                    db.execute(text("UPDATE hoimsystem_ai_run SET status='cancelled' WHERE run_id=:id"), {"id": claim.run_id})
                db.commit()
        if outcome == "duplicate_after_source_loss":
            await execution.execute_research_variables_claimed(claim.run_id, claim.lease, session_factory=factory, transport=httpx.ASGITransport(app=app))
            with factory() as db:
                current = receipts.technical_task(db, claim)
                assert current.run.status == "running" and current.artifact.usage_event_id is None
        value = draft(source)
        if outcome == "bad_quote":
            value["candidates"][0]["quote"] += "原文没有"
        usage = False if outcome == "absent_usage" else {"prompt_tokens": 11} if outcome == "partial_usage" else True
        assert not active
        return JSONResponse(envelope("chat", canonical(value), usage))

    event.listen(db_session.bind, "checkout", checkout)
    event.listen(db_session.bind, "checkin", checkin)
    try:
        await execution.execute_research_variables_claimed(claim.run_id, claim.lease, session_factory=factory, transport=httpx.ASGITransport(app=app))
        assert not active and len(calls) == 1
    finally:
        event.remove(db_session.bind, "checkout", checkout)
        event.remove(db_session.bind, "checkin", checkin)
    task = receipts.technical_task(db_session, claim)
    result_row = db_session.query(AIResearchVariableRunResult).filter_by(run_id=claim.run_id).one_or_none()
    accepted = outcome in {"full", "absent_usage", "partial_usage"}
    assert task.run.status == ("succeeded" if accepted else "cancelled" if outcome == "cancel_during_http" else "failed")
    assert (result_row is not None) is accepted
    recorded = receipts.verify_receipt(db_session, task, accept_event_id=result_row.accept_audit_event_id if accepted else None)
    assert recorded.receipt.model_call_attempted is True
    assert (recorded.receipt.input_tokens, recorded.receipt.output_tokens) == ((None, None) if outcome == "absent_usage" else (11, None) if outcome == "partial_usage" else (11, 13))
    if accepted:
        part = results.result_piece(db_session, case["admin_user"], claim.run_id)
        assert part["usage_receipt"] == recorded.receipt.model_dump(mode="json")
    else:
        assert task.run.error_code is not None
    assert db_session.query(AIAuditEvent).filter_by(target=claim.run_id, action="research_variable_run.dispatch").count() == 1
    assert db_session.query(AIAuditEvent).filter_by(target=claim.run_id, action="research_variable_run.usage").count() == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("error_type", [RuntimeError, AssertionError])
@pytest.mark.parametrize("layer", ["gateway", "worker"])
async def test_unclassified_transport_exception_after_committed_dispatch_records_unknown_attempt_and_counts_never_initial_fake_zero(db_session, actual_task, monkeypatch, error_type, layer):
    case, permissions, _, _ = actual_task
    super_id = inspect(case["super_admin_user"]).identity[0]
    claim = claimed(db_session, actual_task)
    sessions = sessionmaker(bind=db_session.bind, expire_on_commit=False)
    db_session.rollback()
    calls, reads, state = [], [], {"lost": False}

    @contextmanager
    def factory():
        with sessions() as db:

            def observed(event):
                if state["lost"] and event.is_select and hasattr(event.statement, "selected_columns"):
                    reads.extend(
                        str(column.key)
                        for column in event.statement.selected_columns
                        if column.key in {"input_json", "result_json", "evidence_json", "context_metadata_json", "source_json", "binding_json"}
                    )

            event.listen(db, "do_orm_execute", observed)
            yield db

    async def transport(request):
        calls.append(request.url.path)
        with factory() as db:
            review_registry_original(db, SimpleNamespace(user_id=super_id), "authorization", permissions[1]["source_record_id"], {"expected_revision": 2, "basis_note": BASIS}, revoke=True)
        state["lost"] = True
        if layer == "gateway":
            raise error_type("controlled actual transport exception after the original dispatch commit")
        source = VariableTaskSource.model_validate(json.loads(json.loads(request.content)["messages"][1]["content"])["research_variable_source"])
        return httpx.Response(200, json=envelope("chat", canonical(draft(source))))

    if layer == "worker":
        actual_gateway = execution.generate_research_variables

        async def lost_typed_receipt(*args, **kwargs):
            await actual_gateway(*args, **kwargs)
            raise error_type("controlled missing typed receipt after an actual HTTP reply")

        monkeypatch.setattr(execution, "generate_research_variables", lost_typed_receipt)

    await execution.execute_research_variables_claimed(claim.run_id, claim.lease, session_factory=factory, transport=httpx.MockTransport(transport))
    task = receipts.technical_task(db_session, claim)
    recorded = receipts.verify_receipt(db_session, task)
    assert calls == ["/v1/chat/completions"] and task.run.status == "failed"
    assert task.artifact.dispatch_event_id is not None and task.run.error_code == ("VARIABLE_PROVIDER_ERROR" if layer == "gateway" else "WORKER_INTERRUPTED")
    assert (recorded.receipt.input_tokens, recorded.receipt.output_tokens, recorded.receipt.model_call_attempted) == (None, None, True if layer == "gateway" else None)
    assert recorded.receipt.complete is False
    assert not reads
    assert db_session.query(AIResearchVariableRunResult).filter_by(run_id=claim.run_id).count() == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("error_type", [RuntimeError, AssertionError])
async def test_unknown_pre_dispatch_credential_failure_has_no_http_no_dispatch_and_real_known_uncalled_zero(db_session, actual_task, monkeypatch, error_type):
    claim = claimed(db_session, actual_task)
    factory = sessionmaker(bind=db_session.bind, expire_on_commit=False)
    db_session.rollback()
    calls = []

    def unavailable(_provider):
        raise error_type("controlled failure before a dispatch commit")

    async def transport(_request):
        calls.append(1)
        return httpx.Response(200)

    monkeypatch.setattr(execution, "provider_credential", unavailable)
    await execution.execute_research_variables_claimed(claim.run_id, claim.lease, session_factory=factory, transport=httpx.MockTransport(transport))
    task = receipts.technical_task(db_session, claim)
    recorded = receipts.verify_receipt(db_session, task)
    assert not calls and task.artifact.dispatch_event_id is None and task.run.status == "failed"
    assert (recorded.receipt.input_tokens, recorded.receipt.output_tokens, recorded.receipt.model_call_attempted) == (0, 0, False)
