"""Real SQL Source/config/claim -> local synthetic provider ASGI -> SQL result.

No shared Main/JWT worker is claimed yet. The provider text is a controlled
double built from the real HMAC Source; this does not validate a model's RCA.
"""

import asyncio
import datetime as dt
import json
from contextlib import contextmanager

import httpx
import pytest
from fastapi import FastAPI, Request
from sqlalchemy import Select, event, inspect, text
from sqlalchemy.orm import Session
from starlette.responses import JSONResponse

from app.ai import rca_evidence_cancellation as cancellation
from app.ai import rca_evidence_configuration as configuration
from app.ai import rca_evidence_execution as execution
from app.ai import rca_evidence_grants as grants
from app.ai import rca_evidence_receipts as receipts
from app.ai import rca_evidence_result_storage as result_storage
from app.ai import rca_evidence_runtime as runtime
from app.ai import rca_evidence_storage as storage
from app.ai.rca_evidence_run_models import AIRcaEvidenceRunResult
from app.ai.schemas import RunRequest
from app.config import settings
from app.models import User
from tests.test_ai_rca_evidence_configuration import configured
from tests.test_ai_rca_evidence_grants import NOW, cas
from tests.test_ai_rca_evidence_grants import grant_case as grant_case
from tests.test_ai_rca_evidence_protocol import envelope


@pytest.fixture(autouse=True)
def synthetic_host(monkeypatch):
    monkeypatch.setattr(settings, "AI_PROVIDER_ALLOWED_HOSTS", "synthetic.invalid")


def setup(case, kind="chat"):
    db = case["db"]
    _, value, _current = configured(case, kind=kind)
    request = RunRequest(feature_key="incident_rca", input={"rca_evidence_case_id": value.binding.case_id}, preview=True)
    run = runtime.create_rca_run(db, case["actor"], request)
    identifier = inspect(run).identity[0]
    lease = runtime.claim_rca_run(db, identifier)
    owner = inspect(case["actor"]).identity[0]
    engine = db.get_bind()
    db.close()
    active, after_loss_reads, state = [], [], {"authority_lost": False}

    def observe(statement):
        if state["authority_lost"] and statement.is_select and isinstance(statement.statement, Select):
            after_loss_reads.extend(column.key for column in statement.statement.selected_columns if column.key in {*storage.RUN_TEXT, *storage.ART_TEXT})

    @contextmanager
    def factory():
        session = Session(bind=engine)
        active.append(session)
        event.listen(session, "do_orm_execute", observe)
        try:
            yield session
        finally:
            session.close()
            active.remove(session)

    return identifier, lease, owner, value, factory, active, state, after_loss_reads


def provider_service(kind, callback, active):
    app, calls = FastAPI(), []

    @app.post("/v1/{path:path}")
    async def reply(request: Request, path: str):
        assert active == [], "No worker SQL Session may remain open across provider HTTP"
        raw = await request.body()
        body = json.loads(raw)
        public = json.loads(body["messages"][1]["content"] if kind == "chat" else body["input"][0]["content"])
        calls.append((request.url.path, body, public))
        item = public["rca_source"]["items"][0]
        draft = {
            "hypotheses": [
                {
                    "hypothesis": "合成模型意见仍待核实",
                    "supporting_quotes": [{"item_id": item["item_id"], "start": 0, "end": len(item["text"]), "quote": item["text"]}],
                    "conflicting_quotes": [],
                    "timeline_entry_ids": [],
                    "evidence_needed": ["需要独立调查"],
                    "investigation_questions": [],
                }
            ],
            "clarification_questions": [],
        }
        result = envelope(kind, draft)
        result = callback(result) if callback is not None else result
        if hasattr(result, "__await__"):
            result = await result
        assert active == []
        return JSONResponse(result)

    return httpx.ASGITransport(app=app), calls


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["chat", "responses"])
@pytest.mark.parametrize("usage_shape", ["full", "missing", "partial"])
async def test_actual_dedicated_sql_worker_two_protocols_whole_bound_result_and_nullable_usage(grant_case, kind, usage_shape):
    identifier, lease, owner, _value, factory, active, _state, _reads = setup(grant_case, kind)

    def reply(body):
        if usage_shape == "missing":
            del body["usage"]
        elif usage_shape == "partial":
            body["usage"] = {"prompt_tokens" if kind == "chat" else "input_tokens": 11}
        return body

    transport, calls = provider_service(kind, reply, active)
    await execution.execute_rca_claimed(identifier, lease, session_factory=factory, transport=transport)
    assert len(calls) == 1 and calls[0][1]["store"] is False
    public = calls[0][2]
    assert set(public) == {"rca_source", "question"}
    assert not any('"' + key + '"' in json.dumps(public, ensure_ascii=False) for key in ("identity_secret", "event_id", "patient_id", "requested_by", "description"))
    with factory() as db:
        actor = db.get(User, owner)
        stored = storage.load_task(db, actor, identifier)
        assert (
            stored.run.status == "succeeded"
            and result_storage.read_result(db, actor, identifier).rca_evidence_draft.hypotheses[0].supporting_quotes[0].quote == public["rca_source"]["items"][0]["text"]
        )
        actual = receipts.read_receipt(db, receipts.technical_header(db, identifier))
        assert actual.usage.input_tokens == (None if usage_shape == "missing" else 11)
        assert actual.usage.output_tokens == (13 if usage_shape == "full" else None)
        assert actual.usage.complete is (usage_shape == "full") and actual.usage.model_call_attempted is True
        assert db.query(AIRcaEvidenceRunResult).filter_by(run_id=identifier).count() == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("loss", ["grant", "role", "provider"])
async def test_source_role_or_configuration_loss_before_dispatch_has_no_http_and_known_zero(grant_case, loss):
    identifier, lease, owner, value, factory, active, state, reads = setup(grant_case)
    with factory() as db:
        if loss == "grant":
            actor = db.get(User, owner)
            record = grants.grant_detail(db, actor, value.binding.event_grant.grant_id)
            grants.revoke_grant(db, actor, record.identity.grant_id, cas(record))
        elif loss == "role":
            db.execute(text("UPDATE hoimsystem_users SET user_role='admin' WHERE user_id=:id"), {"id": owner})
        else:
            db.execute(text("UPDATE hoimsystem_ai_provider SET model='changed actual provider' WHERE provider_id=(SELECT provider_id FROM hoimsystem_ai_run WHERE run_id=:id)"), {"id": identifier})
        db.commit()
    state["authority_lost"] = loss != "provider"
    transport, calls = provider_service("chat", None, active)
    await execution.execute_rca_claimed(identifier, lease, session_factory=factory, transport=transport)
    assert not calls and not reads
    with factory() as db:
        actual = receipts.read_receipt(db, receipts.technical_header(db, identifier))
        assert actual.status == "failed" and actual.usage.model_call_attempted is False
        assert (actual.usage.input_tokens, actual.usage.output_tokens) == (0, 0)


@pytest.mark.asyncio
@pytest.mark.parametrize("source_loss", [False, True])
async def test_actual_adjacent_delivery_during_held_http_is_inert_even_after_source_loss(grant_case, source_loss):
    identifier, lease, owner, value, factory, active, state, reads = setup(grant_case)
    entered, release = asyncio.Event(), asyncio.Event()

    async def reply(body):
        entered.set()
        await release.wait()
        return body

    transport, calls = provider_service("chat", reply, active)
    first = asyncio.create_task(execution.execute_rca_claimed(identifier, lease, session_factory=factory, transport=transport))
    try:
        await asyncio.wait_for(entered.wait(), 2)
        if source_loss:
            with factory() as db:
                actor = db.get(User, owner)
                record = grants.grant_detail(db, actor, value.binding.event_grant.grant_id)
                grants.revoke_grant(db, actor, record.identity.grant_id, cas(record))
                db.commit()
            state["authority_lost"] = True
        await execution.execute_rca_claimed(identifier, lease, session_factory=factory, transport=transport)
        with factory() as db:
            header = receipts.technical_header(db, identifier)
            assert header.header["status"] == "running" and header.artifact["usage_event_id"] is None
        assert len(calls) == 1
    finally:
        release.set()
        await first
    assert not reads
    with factory() as db:
        actual = receipts.read_receipt(db, receipts.technical_header(db, identifier))
        assert actual.status == ("failed" if source_loss else "succeeded")
        assert (actual.usage.input_tokens, actual.usage.output_tokens) == (11, 13)


@pytest.mark.asyncio
async def test_actual_cancel_during_held_http_keeps_paid_partial_receipt_but_never_accepts_body(grant_case):
    identifier, lease, owner, _value, factory, active, _state, _reads = setup(grant_case)
    entered, release = asyncio.Event(), asyncio.Event()

    async def reply(body):
        entered.set()
        await release.wait()
        body["usage"] = {"prompt_tokens": 11}
        return body

    transport, calls = provider_service("chat", reply, active)
    worker = asyncio.create_task(execution.execute_rca_claimed(identifier, lease, session_factory=factory, transport=transport))
    try:
        await asyncio.wait_for(entered.wait(), 2)
        with factory() as db:
            ack = cancellation.stage_cancel(db, db.get(User, owner), identifier)
            db.commit()
            assert ack.receipt_pending is True and ack.usage_event_id is None
    finally:
        release.set()
        await worker
    with factory() as db:
        actual = receipts.read_receipt(db, receipts.technical_header(db, identifier))
        assert actual.status == "cancelled" and actual.usage.input_tokens == 11 and actual.usage.output_tokens is None
        assert db.query(AIRcaEvidenceRunResult).filter_by(run_id=identifier).count() == 0
    assert len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("loss", ["role", "epoch"])
async def test_authority_changed_during_actual_http_keeps_paid_receipt_without_postloss_task_text(grant_case, loss):
    identifier, lease, owner, _value, factory, active, state, reads = setup(grant_case)

    def reply(body):
        with factory() as db:
            assignment = "user_role='admin'" if loss == "role" else "token_invalid_before='2026-10-21 12:00:01.123456'"
            db.execute(text("UPDATE hoimsystem_users SET " + assignment + " WHERE user_id=:id"), {"id": owner})
            db.commit()
        state["authority_lost"] = True
        return body

    transport, calls = provider_service("chat", reply, active)
    await execution.execute_rca_claimed(identifier, lease, session_factory=factory, transport=transport)
    assert len(calls) == 1 and not reads
    with factory() as db:
        actual = receipts.read_receipt(db, receipts.technical_header(db, identifier))
        assert actual.status == "failed" and (actual.usage.input_tokens, actual.usage.output_tokens) == (11, 13)
        assert db.query(AIRcaEvidenceRunResult).filter_by(run_id=identifier).count() == 0


@pytest.mark.asyncio
async def test_actual_accept_audit_sql_failure_never_leaves_blob_pointer_or_success_and_retains_paid_usage(grant_case):
    identifier, lease, _owner, _value, factory, active, _state, _reads = setup(grant_case)
    with factory() as db:
        db.execute(
            text("CREATE TRIGGER rca_worker_accept_fault BEFORE INSERT ON hoimsystem_ai_audit_event WHEN NEW.action='rca_run.accept' BEGIN SELECT RAISE(ABORT,'actual worker accept reject'); END")
        )
        db.commit()
    transport, calls = provider_service("chat", None, active)
    try:
        await execution.execute_rca_claimed(identifier, lease, session_factory=factory, transport=transport)
    finally:
        with factory() as db:
            db.execute(text("DROP TRIGGER rca_worker_accept_fault"))
            db.commit()
    with factory() as db:
        actual = receipts.read_receipt(db, receipts.technical_header(db, identifier))
        assert actual.status == "failed" and actual.usage.model_call_attempted is True
        assert (actual.usage.input_tokens, actual.usage.output_tokens) == (11, 13)
        assert db.query(AIRcaEvidenceRunResult).filter_by(run_id=identifier).count() == 0
    assert len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("has_dispatch", [False, True])
async def test_actual_recovery_has_known_zero_only_without_dispatch_otherwise_unknown_and_no_replay(grant_case, monkeypatch, has_dispatch):
    identifier, lease, owner, _value, factory, active, _state, _reads = setup(grant_case)
    if has_dispatch:
        with factory() as db:
            stored, _ = configuration.for_execution(db, db.get(User, owner), identifier)
            from app.ai import rca_evidence_attempts as attempts

            attempts.stage_dispatch(db, db.get(User, owner), attempts.claim_proof(db, stored))
            db.commit()
    monkeypatch.setattr(grants, "utcnow", lambda: NOW + dt.timedelta(minutes=11))
    with factory() as db:
        assert execution.expire_interrupted_rca_runs(db) == 1
        actual = receipts.read_receipt(db, receipts.technical_header(db, identifier))
        assert actual.status == "failed" and actual.error_code == "WORKER_INTERRUPTED"
        assert actual.usage.model_call_attempted is (None if has_dispatch else False)
        assert (actual.usage.input_tokens, actual.usage.output_tokens) == ((None, None) if has_dispatch else (0, 0))
    transport, calls = provider_service("chat", None, active)
    await execution.execute_rca_claimed(identifier, lease, session_factory=factory, transport=transport)
    assert calls == []


@pytest.mark.asyncio
async def test_storage_refusal_without_exception_still_settles_this_deliveries_actual_paid_usage(grant_case, monkeypatch):
    identifier, lease, _owner, _value, factory, active, _state, _reads = setup(grant_case)
    transport, calls = provider_service("chat", None, active)
    # Explicitly simulate the result stage declining acceptance. The real
    # technical settlement still verifies the original dispatch and SQL audit.
    monkeypatch.setattr(result_storage, "stage_result", lambda *args, **kwargs: None)
    await execution.execute_rca_claimed(identifier, lease, session_factory=factory, transport=transport)
    assert len(calls) == 1
    with factory() as db:
        actual = receipts.read_receipt(db, receipts.technical_header(db, identifier))
        assert actual.status == "failed" and actual.error_code == "RCA_RESULT_NOT_ACCEPTED"
        assert (actual.usage.input_tokens, actual.usage.output_tokens, actual.usage.model_call_attempted) == (11, 13, True)
        assert db.query(AIRcaEvidenceRunResult).filter_by(run_id=identifier).count() == 0
