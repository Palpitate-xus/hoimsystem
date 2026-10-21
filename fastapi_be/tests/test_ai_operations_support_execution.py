"""Actual SQL transactions -> local synthetic ASGI provider -> actual SQL result.

These tests exercise the dedicated executor, not shared Main/JWT endpoints.
Controlled replies do not establish model reliability or real compatibility.
"""

import asyncio
import datetime as dt
import json
from contextlib import contextmanager

import httpx
import pytest
from fastapi import FastAPI, HTTPException, Request
from sqlalchemy import event, text
from sqlalchemy.orm import Session
from starlette.responses import JSONResponse

from app.ai import operations_support_attempts as attempts
from app.ai import operations_support_contract as c
from app.ai import operations_support_execution as execution
from app.ai import operations_support_receipts as receipts
from app.ai import operations_support_registry as registry
from app.ai import operations_support_result_storage as results
from app.ai import operations_support_runtime as runtime
from app.ai import operations_support_storage as storage
from app.ai.models import AIAuditEvent, AIRun
from app.ai.operations_support_run_models import AIOperationsRunArtifact, AIOperationsRunResult
from app.ai.operations_support_task_prompt import SYSTEM_PROMPT, TASK_PROMPT
from app.ai.operations_support_usage_contract import usage
from app.models import User
from tests.test_ai_operations_support_configuration import actors as actors
from tests.test_ai_operations_support_configuration import configured as configured
from tests.test_ai_operations_support_configuration import source as source
from tests.test_ai_operations_support_gateway import envelope
from tests.test_ai_operations_support_receipts import capture_without_body
from tests.test_ai_operations_support_storage import selection

_observers = []


@pytest.fixture(autouse=True)
def remove_test_observers():
    yield
    for engine, name, callback in _observers:
        event.remove(engine, name, callback)
    _observers.clear()


def setup(configured, kind="chat", *, claim=True):
    db, registrar, creator, reviewer, admin = configured[0]
    configured[-2].kind = kind
    db.flush()
    identifier = runtime.create_operations_run(db, admin, selection(configured))
    owner, stopper = admin.user_id, registrar.user_id
    original_id = configured[1]["original_id"]
    lease = runtime.claim_operations_run(db, identifier) if claim else None
    engine = db.get_bind()
    db.close()
    active, reads, state, connections = [], [], {"authority_lost": False}, set()

    def observe(conn, cursor, statement, params, context, many):
        if state["authority_lost"] and statement.lstrip().lower().startswith("select"):
            protected = [*storage.RUN_TEXT, "source_json", "prompt_snapshot_json", "execution_snapshot_json", "identity_json", "content_text", "draft_json", "published_review_json", "review_basis", "private_json", "public_json"]
            reads.extend(column[0] for column in cursor.description or [] if any(column[0] == key or column[0].endswith("_" + key) for key in protected))

    def checked_out(connection, record, proxy):
        connections.add(id(connection))

    def checked_in(connection, record):
        connections.discard(id(connection))

    for name, callback in [("after_cursor_execute", observe), ("checkout", checked_out), ("checkin", checked_in)]:
        event.listen(engine, name, callback)
        _observers.append((engine, name, callback))

    @contextmanager
    def factory():
        db = Session(bind=engine, autoflush=False)
        active.append(db)
        try:
            yield db
        finally:
            db.close()
            active.remove(db)

    return dict(identifier=identifier, lease=lease, owner=owner, stopper=stopper, original_id=original_id, factory=factory, active=active, reads=reads, state=state, connections=connections)


def provider_service(value, kind="chat", callback=None):
    app, calls = FastAPI(), []

    @app.post("/v1/{path:path}")
    async def reply(request: Request, path: str):
        assert value["active"] == [] and value["connections"] == set(), "SQL Session/connection retained across model await"
        wire = json.loads(await request.body())
        assert wire["store"] is False and "tools" not in wire
        assert (wire["messages"][0]["content"] if kind == "chat" else wire["instructions"]) == SYSTEM_PROMPT + "\n\n" + TASK_PROMPT
        public = json.loads(wire["messages"][1]["content"] if kind == "chat" else wire["input"])
        assert public["selection"]["operations_case_id"] == public["source"]["source_id"]
        assert not {"patient_id", "original_id", "review_basis", "private_json", "identity_json"} & public["source"].keys()
        source = public["source"]
        document = source["documents"][0]
        draft = dict(
            schema_version="operations_support_draft_v1",
            source_id=source["source_id"],
            source_sha256=c.content_hash(source),
            objective=public["selection"]["objective"],
            status="unverified_operations_draft",
            environment_status="not_observed_by_this_task",
            compatibility_status="not_verified_from_reviewed_text",
            observations=[dict(title="受审合成片段", explanation="仍需管理员核实", evidence=[dict(source_id=document["source_id"], start_codepoint=4, end_codepoint=8, quote=document["text"][4:8])])],
            hypotheses=[],
            manual_checks=[],
            gaps=[dict(kind="missing_reviewed_runbook", explanation="没有审核手册，未生成检查指令")],
        )
        body = envelope(kind, draft)
        calls.append((request.url.path, wire, public))
        if callback is not None:
            body = callback(body)
            if hasattr(body, "__await__"):
                body = await body
        assert value["active"] == [] and value["connections"] == set()
        return JSONResponse(body)

    return httpx.ASGITransport(app=app), calls


def current_receipt(value):
    with value["factory"]() as db:
        return capture_without_body(db, lambda: receipts.read_receipt(db, attempts.technical_header(db, value["identifier"])))


def withdraw(value):
    with value["factory"]() as db:
        registry.revoke_original(db, db.get(User, value["stopper"]), value["original_id"], {"revision": 1, "reason": "在途资料撤回"})
        db.commit()
    value["state"]["authority_lost"] = True


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["chat", "responses"])
@pytest.mark.parametrize("usage_shape", ["full", "missing", "partial", "partial_total"])
async def test_actual_sql_asgi_two_protocols_and_independent_nullable_usage(configured, kind, usage_shape):
    value = setup(configured, kind)

    def reply(body):
        if usage_shape == "missing":
            del body["usage"]
        elif usage_shape in {"partial", "partial_total"}:
            body["usage"] = {"prompt_tokens" if kind == "chat" else "input_tokens": 11}
            if usage_shape == "partial_total":
                body["usage"]["total_tokens"] = 24
        return body

    transport, calls = provider_service(value, kind, reply)
    await execution.execute_operations_claimed(value["identifier"], value["lease"], session_factory=value["factory"], transport=transport)
    actual = current_receipt(value)
    assert len(calls) == 1 and actual.status == "succeeded"
    assert actual.usage.model_dump() == usage(None if usage_shape == "missing" else 11, 13 if usage_shape == "full" else None, True)
    with value["factory"]() as db:
        accepted = results.load_result(db, db.get(User, value["owner"]), value["identifier"])
        assert accepted.observations[0].evidence[0].quote == "😀\r\n\x00"
        artifact = db.get(AIOperationsRunArtifact, value["identifier"])
        blob = db.get(AIOperationsRunResult, value["identifier"])
        assert len({artifact.created_audit_event_id, artifact.claim_event_id, artifact.dispatch_event_id, artifact.usage_event_id, blob.accept_audit_event_id}) == 5
    await execution.execute_operations_claimed(value["identifier"], value["lease"], session_factory=value["factory"], transport=transport)
    assert len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("loss", ["source", "role", "epoch", "provider"])
async def test_actual_source_role_epoch_configuration_loss_before_dispatch_is_proven_zero(configured, loss):
    value = setup(configured)
    if loss == "source":
        withdraw(value)
    else:
        with value["factory"]() as db:
            if loss == "provider":
                db.execute(text("UPDATE hoimsystem_ai_provider SET revision=revision+1 WHERE provider_id=(SELECT provider_id FROM hoimsystem_ai_run WHERE run_id=:id)"), {"id": value["identifier"]})
            else:
                assignment = "user_role='doctor'" if loss == "role" else "token_invalid_before='2026-10-24 01:02:03.123456'"
                db.execute(text("UPDATE hoimsystem_users SET " + assignment + " WHERE user_id=:id"), {"id": value["owner"]})
            db.commit()
        value["state"]["authority_lost"] = True
    transport, calls = provider_service(value)
    await execution.execute_operations_claimed(value["identifier"], value["lease"], session_factory=value["factory"], transport=transport)
    actual = current_receipt(value)
    assert calls == [] and value["reads"] == [] and actual.status == "failed" and actual.usage.model_dump() == usage(0, 0, False)


@pytest.mark.asyncio
@pytest.mark.parametrize("withdraw_source", [False, True])
async def test_actual_held_http_second_delivery_cannot_repeat_or_terminate_owner(configured, withdraw_source):
    value = setup(configured)
    entered, release = asyncio.Event(), asyncio.Event()

    async def reply(body):
        entered.set()
        await release.wait()
        body["usage"] = {"prompt_tokens": 11}
        return body

    transport, calls = provider_service(value, callback=reply)
    first = asyncio.create_task(execution.execute_operations_claimed(value["identifier"], value["lease"], session_factory=value["factory"], transport=transport))
    try:
        await asyncio.wait_for(entered.wait(), 10)
        if withdraw_source:
            withdraw(value)
        await execution.execute_operations_claimed(value["identifier"], value["lease"], session_factory=value["factory"], transport=transport)
        with value["factory"]() as db:
            current = attempts.technical_header(db, value["identifier"])
            assert current.header["status"] == "running" and current.artifact["usage_event_id"] is None
        assert len(calls) == 1
    finally:
        release.set()
        await first
    assert current_receipt(value).status == ("failed" if withdraw_source else "succeeded")
    assert current_receipt(value).usage.model_dump() == usage(11, None, True) and value["reads"] == []


@pytest.mark.asyncio
async def test_actual_commit_cancel_during_http_keeps_original_partial_paid_and_no_result(configured):
    value = setup(configured)
    entered, release = asyncio.Event(), asyncio.Event()

    async def reply(body):
        entered.set()
        await release.wait()
        body["usage"] = {"prompt_tokens": 11}
        return body

    transport, calls = provider_service(value, callback=reply)
    first = asyncio.create_task(execution.execute_operations_claimed(value["identifier"], value["lease"], session_factory=value["factory"], transport=transport))
    try:
        await asyncio.wait_for(entered.wait(), 10)
        with value["factory"]() as db:
            ack = runtime.cancel_operations_run(db, db.get(User, value["stopper"]), value["identifier"])
            assert ack.receipt_pending is True and ack.usage_event_id is None
    finally:
        release.set()
        await first
    assert len(calls) == 1 and current_receipt(value).status == "cancelled" and current_receipt(value).usage.model_dump() == usage(11, None, True)
    with value["factory"]() as db:
        assert db.get(AIOperationsRunResult, value["identifier"]) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("loss", ["role", "epoch"])
async def test_actual_authority_loss_after_paid_http_retains_receipt_without_task_text(configured, loss):
    value = setup(configured)

    def reply(body):
        with value["factory"]() as db:
            assignment = "user_role='doctor'" if loss == "role" else "token_invalid_before='2026-10-24 01:02:03.123456'"
            db.execute(text("UPDATE hoimsystem_users SET " + assignment + " WHERE user_id=:id"), {"id": value["owner"]})
            db.commit()
        value["state"]["authority_lost"] = True
        return body

    transport, calls = provider_service(value, callback=reply)
    await execution.execute_operations_claimed(value["identifier"], value["lease"], session_factory=value["factory"], transport=transport)
    assert len(calls) == 1 and current_receipt(value).status == "failed" and current_receipt(value).usage.model_dump() == usage(11, 13, True) and value["reads"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["accept_sql", "declined_result"])
async def test_actual_result_storage_failure_or_decline_keeps_paid_and_rolls_back_complete_blob(configured, monkeypatch, fault):
    value = setup(configured)
    if fault == "declined_result":
        monkeypatch.setattr(results, "stage_result", lambda *args, **kw: None)
    else:
        with value["factory"]() as db:
            db.execute(text("CREATE TRIGGER ops_worker_accept_fault BEFORE INSERT ON hoimsystem_ai_audit_event WHEN NEW.action='" + results.ACCEPT_ACTION + "' BEGIN SELECT RAISE(ABORT,'synthetic accept failure'); END"))
            db.commit()
    transport, calls = provider_service(value)
    try:
        await execution.execute_operations_claimed(value["identifier"], value["lease"], session_factory=value["factory"], transport=transport)
    finally:
        if fault == "accept_sql":
            with value["factory"]() as db:
                db.execute(text("DROP TRIGGER ops_worker_accept_fault"))
                db.commit()
    assert len(calls) == 1 and current_receipt(value).status == "failed" and current_receipt(value).usage.model_dump() == usage(11, 13, True)
    with value["factory"]() as db:
        assert db.get(AIOperationsRunResult, value["identifier"]) is None and db.get(AIRun, value["identifier"]).result_json == "{}"


@pytest.mark.asyncio
@pytest.mark.parametrize("has_dispatch", [False, True])
async def test_actual_interruption_timeout_has_known_zero_or_unknown_without_http_replay(configured, monkeypatch, has_dispatch):
    value = setup(configured)
    with value["factory"]() as db:
        actual = attempts.technical_header(db, value["identifier"])
        clock = attempts.clock(actual.claim.claimed_at)
        if has_dispatch:
            attempts.stage_dispatch(db, db.get(User, value["owner"]), actual.claim)
            db.commit()
    monkeypatch.setattr(registry, "utcnow", lambda: clock + dt.timedelta(minutes=11))
    with value["factory"]() as db:
        assert capture_without_body(db, lambda: runtime.expire_interrupted_operations_runs(db)) == 1
        assert runtime.expire_interrupted_operations_runs(db) == 0
    assert current_receipt(value).usage.model_dump() == (usage(None, None, None) if has_dispatch else usage(0, 0, False))
    transport, calls = provider_service(value)
    await execution.execute_operations_claimed(value["identifier"], value["lease"], session_factory=value["factory"], transport=transport)
    assert calls == []


@pytest.mark.parametrize("loss", ["source", "role", "config"])
def test_actual_committed_queue_claim_failure_is_unclaimed_zero_without_any_source_text(configured, loss):
    value = setup(configured, claim=False)
    if loss == "source":
        withdraw(value)
    else:
        with value["factory"]() as db:
            if loss == "role":
                db.execute(text("UPDATE hoimsystem_users SET user_role='doctor' WHERE user_id=:id"), {"id": value["owner"]})
            else:
                db.execute(text("UPDATE hoimsystem_ai_feature_config SET enabled=0 WHERE feature_key='operations_support'"))
            db.commit()
        value["state"]["authority_lost"] = True
    with value["factory"]() as db:
        assert runtime.claim_operations_run(db, value["identifier"]) is None
    actual = current_receipt(value)
    assert actual.status == "failed" and actual.claim_event_id is None and actual.lease_token is None and actual.usage.model_dump() == usage(0, 0, False)
    assert value["reads"] == []


def test_actual_creation_commit_failure_rolls_back_new_run_artifact_and_create_receipt(configured):
    db, registrar, creator, reviewer, admin = configured[0]
    owner = admin.user_id
    before = db.query(AIRun).count(), db.query(AIOperationsRunArtifact).count(), db.query(AIAuditEvent).count()
    db.execute(text("CREATE TRIGGER ops_create_fault AFTER INSERT ON hoimsystem_ai_operations_run_artifact BEGIN UPDATE hoimsystem_users SET user_role='doctor' WHERE user_id=" + str(owner) + "; END"))
    db.commit()
    try:
        with pytest.raises(HTTPException) as exc:
            runtime.create_operations_run(db, admin, selection(configured))
        assert exc.value.status_code == 403
        assert (db.query(AIRun).count(), db.query(AIOperationsRunArtifact).count(), db.query(AIAuditEvent).count()) == before
        assert db.query(User.user_role).filter_by(user_id=owner).scalar() == "admin"
    finally:
        db.rollback()
        db.execute(text("DROP TRIGGER IF EXISTS ops_create_fault"))
        db.commit()
