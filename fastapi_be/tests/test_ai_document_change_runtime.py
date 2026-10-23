"""Actual Source services/SQL durable claim and ASGI provider, no public dispatch.

The common main/catalog/routes are not wired here. A synthetic provider handles
real httpx ASGI requests. This is neither live model HTTP nor a hospital test.
"""

import json
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import event, inspect, text

from app import database
from app.ai import document_change_contract as c
from app.ai import document_change_runtime as changes
from app.ai import document_change_sources as sources
from app.ai import document_change_storage as storage
from app.ai import runtime
from app.ai.document_change_run_models import AIDocumentChangeRunArtifact, AIDocumentChangeRunResult
from app.ai.models import AIAuditEvent, AIFeatureConfig, AIProvider, AIRun
from app.models import User
from tests.ai_admin_usage_assertions import assert_exact_usage_event
from tests.test_ai_document_change_protocol import envelope
from tests.test_ai_document_change_sources import change_case as change_case  # noqa: F401
from tests.test_ai_document_change_storage import remove_prior_tasks as remove_prior_tasks  # noqa: F401
from tests.test_ai_document_change_storage import task
from tests.test_ai_document_evidence_contract import NOTE, NOW
from tests.test_ai_document_evidence_sources import cas


@pytest.fixture
def pipeline(change_case, monkeypatch):
    db, actor, *_ = change_case
    value = task(change_case)
    old_id = inspect(value["run"]).identity[0]
    db.query(AIDocumentChangeRunArtifact).filter_by(run_id=old_id).delete(synchronize_session=False)
    db.query(AIRun).filter_by(run_id=old_id).delete(synchronize_session=False)
    value["provider"].api_base = "http://127.0.0.1:8824/v1"
    db.commit()
    monkeypatch.setattr(runtime, "utcnow", lambda: c.e.clock(NOW))
    value.update(db=db, actor=actor, actor_id=actor.user_id, provider_id=value["provider"].provider_id)
    db.commit()
    return value


def request(case, **values):
    result = {
        "feature_key": storage.FEATURE_KEY,
        "patient_id": None,
        "encounter_ref": None,
        "preview": True,
        "input": {"document_change_scope_id": case["scope"].snapshot.scope_id, "question": "\ufeff完整问题\r\n😀"},
    }
    result.update(values)
    return SimpleNamespace(**result)


def queued(case):
    run = changes.create_change_run(case["db"], case["actor"], request(case))
    return inspect(run).identity[0]


def claim(case, run_id):
    result = runtime.claim_next_run(case["db"])
    assert result and result[0] == run_id
    return result


def model_transport(case, *, mutate=None, usage="complete"):
    app, packets, active = FastAPI(), [], set()
    engine = case["db"].get_bind()

    def begin(connection):
        active.add(id(connection))

    def end(connection):
        active.discard(id(connection))

    event.listen(engine, "begin", begin)
    event.listen(engine, "commit", end)
    event.listen(engine, "rollback", end)

    @app.post("/v1/chat/completions")
    @app.post("/v1/responses")
    async def provider(req: Request):
        assert not active, "No SQL transaction may survive into provider await"
        packet = await req.json()
        packets.append(packet)
        kind = "chat" if req.url.path.endswith("completions") else "responses"
        public = json.loads(packet["messages"][1]["content"] if kind == "chat" else packet["input"][0]["content"])
        assert set(public) == {"document_change_source", "question"} and packet["store"] is False
        assert public["document_change_source"] == case["source"].model_dump(mode="json")
        assert "private rule body" not in json.dumps(packet) and "私有目标标题禁止外发" not in json.dumps(packet, ensure_ascii=False)
        src = public["document_change_source"]
        proposal = {
            "kind": "paired_wording_question",
            "baseline_spans": [{"start": 0, "end": 1, "quote": src["baseline"]["text"][:1]}],
            "candidate_spans": [{"start": 0, "end": 1, "quote": src["candidate"]["text"][:1]}],
            "review_note": "模型问题仍未核实。",
            "clarification_question": "请人工核对原文适用性？",
        }
        if mutate:
            mutate()
        value = envelope(kind, c.e.canonical_json({"changes": [proposal]}))
        if usage == "partial":
            value["usage"].pop("completion_tokens" if kind == "chat" else "output_tokens")
        elif usage == "missing":
            value.pop("usage")
        return JSONResponse(value)

    def close():
        event.remove(engine, "begin", begin)
        event.remove(engine, "commit", end)
        event.remove(engine, "rollback", end)

    return httpx.ASGITransport(app=app), packets, close


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["chat", "responses"])
async def test_actual_complete_source_short_queue_claim_asgi_blob_and_current_frozen_read(pipeline, kind):
    case, db = pipeline, pipeline["db"]
    case["provider"].kind = kind
    db.commit()
    run_id = queued(case)
    claim_value = claim(case, run_id)
    transport, packets, close = model_transport(case)
    try:
        await changes.execute_change_claimed(*claim_value, transport=transport)
    finally:
        close()
    db.expire_all()
    run = db.get(AIRun, run_id)
    assert run.status == "succeeded", run.error_message
    assert len(packets) == 1 and storage.usage_receipt(db, run).model_dump(mode="json") == {"input_tokens": 11, "output_tokens": 13, "complete": True, "model_call_attempted": True}
    result = storage.expand_result(db, case["actor"], run)
    assert result.document_change.requires_human_review is True and result.document_change.automatic_changes is False
    assert result.document_change.changes[0].baseline_spans[0].quote == case["source"].baseline.text[:1]
    assert db.get(AIDocumentChangeRunResult, run_id).result_json == c.e.canonical_json(result)
    assert case["source"].baseline.text not in run.input_json and len(c.e.utf8(run.input_json)) < 65535
    assert storage.artifact_record(db, case["actor"], run).recorded_at == NOW
    assert storage.expanded_private_scope(db, case["actor"], run).scope_snapshot == case["scope"].snapshot
    assert_exact_usage_event(db, run_id, "document_change", storage.usage_receipt(db, run).model_dump(mode="json"))


@pytest.mark.asyncio
async def test_unclaimed_cancel_is_known_zero_no_source_reads_and_is_not_claimed(pipeline):
    case, db = pipeline, pipeline["db"]
    run_id = queued(case)
    statements = []

    def sql(conn, cursor, statement, parameters, context, many):
        statements.append(statement)

    event.listen(db.get_bind(), "before_cursor_execute", sql)
    try:
        changes.cancel_change_run(db, case["actor"], run_id)
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", sql)
    assert not any("FROM hoimsystem_ai_document_change_scope" in stmt or "FROM hoimsystem_ai_document_original" in stmt for stmt in statements)
    assert runtime.claim_next_run(db) is None
    run = db.get(AIRun, run_id)
    assert run.status == "cancelled" and storage.usage_receipt(db, run).model_dump(mode="json") == changes.ZERO


@pytest.mark.asyncio
@pytest.mark.parametrize("usage", ["partial", "missing"])
async def test_real_asgi_rejected_draft_retains_only_actual_nullable_usage(pipeline, usage):
    case, db = pipeline, pipeline["db"]
    run_id = queued(case)
    claimed = claim(case, run_id)
    transport, packets, close = model_transport(case, usage=usage)
    try:
        await changes.execute_change_claimed(*claimed, transport=transport)
    finally:
        close()
    db.expire_all()
    run = db.get(AIRun, run_id)
    receipt = storage.usage_receipt(db, run)
    assert len(packets) == 1 and run.status == "failed" and run.result_json == "{}"
    assert receipt.input_tokens == (11 if usage == "partial" else None) and receipt.output_tokens is None and receipt.complete is False and receipt.model_call_attempted is True
    assert db.get(AIDocumentChangeRunResult, run_id) is None


def mutate_current(case, kind, run_id):
    with database.SessionLocal() as db:
        actor = db.get(User, case["actor_id"])
        if kind == "scope":
            sources.revoke_scope(db, actor, case["scope"].snapshot.scope_id, {**cas(case["scope"]), "basis_note": NOTE})
        elif kind == "role":
            actor.user_role = "admin"
        elif kind == "provider":
            db.get(AIProvider, case["provider_id"]).revision += 1
        elif kind == "cancel":
            changes.cancel_change_run(db, actor, run_id)
            return
        db.commit()


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["scope", "role", "provider", "cancel"])
async def test_current_authority_or_cancel_changed_during_actual_model_call_keeps_paid_receipt_not_body(pipeline, mutation):
    case, db = pipeline, pipeline["db"]
    run_id = queued(case)
    claimed = claim(case, run_id)
    transport, packets, close = model_transport(case, mutate=lambda: mutate_current(case, mutation, run_id))
    try:
        await changes.execute_change_claimed(*claimed, transport=transport)
    finally:
        close()
    db.expire_all()
    run = db.get(AIRun, run_id)
    assert len(packets) == 1 and run.status == ("cancelled" if mutation == "cancel" else "failed")
    assert run.result_json == "{}" and db.get(AIDocumentChangeRunResult, run_id) is None
    assert storage.usage_receipt(db, run).model_dump(mode="json") == {"input_tokens": 11, "output_tokens": 13, "complete": True, "model_call_attempted": True}


@pytest.mark.asyncio
async def test_revoked_scope_before_call_records_proven_no_call_without_invoking_provider(pipeline):
    case, db = pipeline, pipeline["db"]
    run_id = queued(case)
    mutate_current(case, "scope", run_id)
    claimed = claim(case, run_id)
    transport, packets, close = model_transport(case)
    try:
        await changes.execute_change_claimed(*claimed, transport=transport)
    finally:
        close()
    db.expire_all()
    run = db.get(AIRun, run_id)
    assert not packets and run.status == "failed" and storage.usage_receipt(db, run).model_dump(mode="json") == changes.ZERO


@pytest.mark.asyncio
async def test_claimed_then_cancelled_before_dispatch_never_calls_or_reauthorizes_revoked_source(pipeline):
    case, db = pipeline, pipeline["db"]
    run_id = queued(case)
    claimed = claim(case, run_id)
    changes.cancel_change_run(db, case["actor"], run_id)
    run = db.get(AIRun, run_id)
    assert storage.usage_receipt(db, run).model_call_attempted is None
    db.commit()
    mutate_current(case, "scope", run_id)
    transport, packets, close = model_transport(case)
    try:
        await changes.execute_change_claimed(*claimed, transport=transport)
    finally:
        close()
    db.expire_all()
    run = db.get(AIRun, run_id)
    assert not packets and run.status == "cancelled" and storage.usage_receipt(db, run).model_dump(mode="json") == changes.ZERO


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["accept_audit", "blob"])
async def test_actual_sql_acceptance_failure_rolls_back_success_and_blob_then_preserves_known_paid_failure(pipeline, fault):
    case, db = pipeline, pipeline["db"]
    run_id = queued(case)
    claimed = claim(case, run_id)
    trigger = (
        "BEFORE INSERT ON hoimsystem_ai_audit_event WHEN NEW.action='run.document_change.accept' BEGIN SELECT RAISE(ABORT,'actual accept failure'); END"
        if fault == "accept_audit"
        else "AFTER INSERT ON hoimsystem_ai_document_change_run_result BEGIN UPDATE hoimsystem_ai_document_change_run_result SET result_json='{}' WHERE run_id=NEW.run_id; END"
    )
    db.execute(text("CREATE TRIGGER change_runtime_fault " + trigger))
    db.commit()
    transport, packets, close = model_transport(case)
    try:
        await changes.execute_change_claimed(*claimed, transport=transport)
    finally:
        close()
        db.execute(text("DROP TRIGGER IF EXISTS change_runtime_fault"))
        db.commit()
    db.expire_all()
    run = db.get(AIRun, run_id)
    assert len(packets) == 1 and run.status == "failed" and run.result_json == "{}" and run.error_code == "RESULT_NOT_ACCEPTED"
    assert db.get(AIDocumentChangeRunResult, run_id) is None
    assert storage.usage_receipt(db, run).input_tokens == 11 and storage.usage_receipt(db, run).output_tokens == 13
    assert db.query(AIAuditEvent).filter_by(target=run_id, action="run.document_change.accept").count() == 0
    assert db.query(AIAuditEvent).filter_by(target=run_id, action="run.document_change.usage").count() == 1


@pytest.mark.parametrize("phase", ["queued", "running"])
def test_real_cancel_audit_mutation_cannot_leave_partial_status_or_receipt(pipeline, phase):
    case, db = pipeline, pipeline["db"]
    run_id = queued(case)
    if phase == "running":
        claim(case, run_id)
    db.execute(
        text(
            "CREATE TRIGGER change_cancel_fault AFTER INSERT ON hoimsystem_ai_audit_event WHEN NEW.action='run.cancel' BEGIN UPDATE hoimsystem_ai_document_change_run_artifact SET member_count=member_count+1 WHERE run_id=NEW.target; END"
        )
    )
    db.commit()
    try:
        with pytest.raises(HTTPException):
            changes.cancel_change_run(db, case["actor"], run_id)
    finally:
        db.execute(text("DROP TRIGGER IF EXISTS change_cancel_fault"))
        db.commit()
    db.expire_all()
    run = db.get(AIRun, run_id)
    assert run.status == phase and db.get(AIDocumentChangeRunArtifact, run_id).usage_event_id is None
    assert db.query(AIAuditEvent).filter_by(target=run_id, action="run.cancel").count() == 0
    assert db.query(AIAuditEvent).filter_by(target=run_id, action="run.document_change.usage").count() == 0


def test_standalone_creation_refuses_pending_caller_writes_without_discarding_them(pipeline):
    case, db = pipeline, pipeline["db"]
    pending = AIAuditEvent(actor_id=case["actor_id"], action="pending.caller", target="not-created-by-runtime", detail_json="{}")
    db.add(pending)
    with pytest.raises(HTTPException):
        changes.create_change_run(db, case["actor"], request(case))
    assert pending in db.new
    db.rollback()


def test_actual_author_quota_is_enforced_without_creating_second_partial_task(pipeline):
    case, db = pipeline, pipeline["db"]
    config = db.get(AIFeatureConfig, storage.FEATURE_KEY)
    config.daily_limit = 1
    config.revision += 1
    db.commit()
    run_id = queued(case)
    with pytest.raises(HTTPException) as info:
        queued(case)
    assert info.value.status_code == 429
    assert db.query(AIRun).filter_by(feature_key=storage.FEATURE_KEY).count() == 1
    assert db.query(AIDocumentChangeRunArtifact).count() == 1 and db.get(AIRun, run_id).status == "queued"


@pytest.mark.asyncio
async def test_actual_packaged_catalog_prompt_is_frozen_and_accepted_at_version_zero(pipeline):
    from app.ai.catalog import FEATURE_BY_KEY
    from app.ai.document_change_draft import SYSTEM_PROMPT

    case, db = pipeline, pipeline["db"]
    db.get(AIFeatureConfig, storage.FEATURE_KEY).active_prompt_id = None
    db.commit()
    run_id = queued(case)
    run = db.get(AIRun, run_id)
    prompt = FEATURE_BY_KEY[storage.FEATURE_KEY].task_prompt
    snapshot = json.loads(run.input_json)
    assert run.prompt_version == 0 and snapshot["task_prompt"] == prompt
    assert run.prompt_hash == c.e.digest([SYSTEM_PROMPT, prompt])
    assert json.loads(run.context_metadata_json)["instructions_digest"] == c.e.bytes_hash(SYSTEM_PROMPT + "\n\n" + prompt)
    claim_value = claim(case, run_id)
    transport, packets, close = model_transport(case)
    try:
        await changes.execute_change_claimed(*claim_value, transport=transport)
    finally:
        close()
    db.expire_all()
    assert db.get(AIRun, run_id).status == "succeeded"
    assert len(packets) == 1 and packets[0]["messages"][0]["content"] == SYSTEM_PROMPT + "\n\n" + prompt
    assert storage.expand_result(db, case["actor"], db.get(AIRun, run_id)).document_change.requires_human_review
