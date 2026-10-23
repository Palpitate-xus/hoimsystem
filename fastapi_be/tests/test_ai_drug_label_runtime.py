"""Actual governed Source → SQL task/claim → MockTransport → atomic receipts.

No shared dispatch, real remote provider, HTTP/JWT API or MySQL is claimed here.
"""

import hashlib
import json

import httpx
import pytest
from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder
from sqlalchemy import event, text
from sqlalchemy.dialects import mysql

from app import database
from app.ai import document_evidence_contract as d
from app.ai import drug_label_runtime as runtime
from app.ai import drug_label_sources as sources
from app.ai import drug_label_storage as storage
from app.ai.catalog import FEATURE_BY_KEY
from app.ai.drug_label_draft import SYSTEM_PROMPT
from app.ai.drug_label_run_contract import ACCEPT_ACTION, CREATE_ACTION, USAGE_ACTION
from app.ai.models import AIAuditEvent, AIFeatureConfig, AIPromptVersion, AIRun
from app.ai.schemas import RunRequest
from app.config import settings
from app.models import User
from tests.ai_admin_usage_assertions import assert_exact_usage_event
from tests.test_ai_drug_label_gateway import envelope
from tests.test_ai_drug_label_sources import NOTE, cas
from tests.test_ai_drug_label_sources import label_case as _label_case
from tests.test_ai_drug_label_storage import make_task

label_case = _label_case


@pytest.fixture
def case(label_case, monkeypatch):
    value = make_task(label_case)
    monkeypatch.setattr(settings, "AI_PROVIDER_ALLOWED_HOSTS", "synthetic.invalid")
    value.config.daily_limit = 10000
    value.prompt.task_prompt = FEATURE_BY_KEY[runtime.FEATURE_KEY].task_prompt
    value.db.commit()
    real_factory = database.SessionLocal
    value.worker_sessions = []

    def observed_session():
        session = real_factory()
        value.worker_sessions.append(session)
        return session

    monkeypatch.setattr(database, "SessionLocal", observed_session)
    value.request = RunRequest(feature_key=runtime.FEATURE_KEY, input={"drug_label_source_binding_id": value.source.snapshot.source_binding_id, "question": " \t\u2003"})
    return value


def queued(case):
    row = runtime.create_drug_label_run(case.db, case.actor, case.request)
    case.id = row.run_id
    return row


def stored(case):
    case.db.expire_all()
    return storage.load_snapshot(case.db, case.id, writing=True)


def view(case, *, user=None, audit=False):
    return runtime.describe_drug_label_run(case.db, user or case.actor, case.id, frozen_audit=audit)


def revoke(case):
    before = sources.source_current(case.db, case.users["super_admin_user"], case.source.snapshot.source_binding_id)
    sources.revoke_source(case.db, case.users["super_admin_user"], before.snapshot.source_binding_id, {**cas(before), "basis_note": NOTE})
    case.db.commit()


def mutate(case, axis):
    if axis == "source":
        revoke(case)
    elif axis == "role":
        case.db.query(User).filter_by(user_id=case.actor.user_id).update({"user_role": "patient"}, synchronize_session=False)
    elif axis == "token":
        case.db.query(User).filter_by(user_id=case.actor.user_id).update({"token_invalid_before": sources.utcnow()}, synchronize_session=False)
    elif axis == "prompt":
        case.db.query(AIPromptVersion).filter_by(prompt_id=case.prompt.prompt_id).update({"task_prompt": "实际Prompt已改变"}, synchronize_session=False)
    elif axis == "configuration":
        case.db.query(AIFeatureConfig).filter_by(feature_key=runtime.FEATURE_KEY).update({"enabled": 0}, synchronize_session=False)
    elif axis == "config_deleted":
        case.db.query(AIFeatureConfig).filter_by(feature_key=runtime.FEATURE_KEY).delete(synchronize_session=False)
    else:
        raise AssertionError(axis)
    case.db.commit()


async def execute(case, handler):
    lease = runtime.claim_drug_label_run(case.db, case.id)
    assert lease
    await runtime.execute_drug_label_claimed(case.id, lease, transport=httpx.MockTransport(handler))
    return stored(case)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["chat", "responses"])
async def test_actual_task_source_seed_prompt_two_digests_wire_and_three_exact_audits(case, kind):
    case.provider.kind = kind
    case.db.commit()
    row = queued(case)
    assert row.status == "queued" and row.create_time.microsecond == 0
    before = storage.load_snapshot(case.db, row)
    assert before.artifact.created_at.microsecond == 123456
    assert before.artifact.mapping_seed not in row.input_json
    assert row.prompt_hash == d.digest([SYSTEM_PROMPT, case.prompt.task_prompt])
    assert before.metadata["instructions_digest"] == hashlib.sha256((SYSTEM_PROMPT + "\n\n" + case.prompt.task_prompt).encode()).hexdigest() != row.prompt_hash
    seen = []

    def handler(request):
        assert case.worker_sessions and all(not session.in_transaction() for session in case.worker_sessions)
        value = json.loads(request.content)
        public = json.loads(value["input"][0]["content"] if kind == "responses" else value["messages"][1]["content"])
        assert set(public) == {"drug_label_source", "question"} and public["question"] == " \t\u2003"
        assert public["drug_label_source"] == before.public_source.model_dump(mode="json")
        assert before.artifact.mapping_seed not in request.content.decode()
        assert '"basis_note":' not in request.content.decode() and '"signed_by":' not in request.content.decode()
        seen.append(value)
        start = before.public_source.text.index("合成成分")
        reply = {"fields": [{"field": "composition", "spans": [{"start": start, "end": start + 4, "quote": "合成成分"}], "review_question": "请药师逐字核对该字段与原文条件。"}]}
        return httpx.Response(200, json=envelope(kind, reply))

    after = await execute(case, handler)
    assert after.run.status == "succeeded" and len(seen) == 1
    ids = (after.artifact.create_event_id, after.artifact.receipt_event_id, after.artifact.accept_event_id)
    assert len(set(ids)) == 3
    for identifier, action in zip(ids, (CREATE_ACTION, USAGE_ACTION, ACCEPT_ACTION)):
        audit = case.db.get(AIAuditEvent, identifier)
        assert (audit.action, audit.target, audit.actor_id) == (action, case.id, case.actor.user_id)
    assert after.artifact.accepted_at.microsecond == 123456 and after.run.finish_time.microsecond == 0
    dto = view(case)
    assert dto["result"]["drug_label_extraction"]["fields"][0]["spans"][0]["quote"] == "合成成分"
    assert dto["input_tokens"] == 13 and dto["output_tokens"] == 7 and dto["usage_receipt"]["model_call_attempted"] is True
    assert after.artifact.mapping_seed not in d.canonical_json(jsonable_encoder(dto))
    assert "accepted_lease" not in dto["drug_label_artifact"]
    assert_exact_usage_event(case.db, case.id, "drug_label", dto["usage_receipt"])


@pytest.mark.parametrize("question", [None, "", " \t\r\n\u2003"])
def test_real_optional_question_is_preserved_without_review_basis_rules(case, question):
    case.request.input["question"] = question
    row = queued(case)
    assert storage.load_snapshot(case.db, row).snapshot["payload"]["input"]["question"] == question


@pytest.mark.asyncio
async def test_queued_cancel_is_actual_zero_and_never_claimed(case):
    queued(case)
    runtime.cancel_drug_label_run(case.db, case.actor, case.id)
    after = stored(case)
    assert after.run.status == "cancelled" and after.run.lease_token is None and after.run.result_json == "{}"
    assert after.artifact.result_json is after.artifact.accept_event_id is after.artifact.accepted_at is None
    receipt = storage.usage_receipt(case.db, after)
    assert (receipt.input_tokens, receipt.output_tokens, receipt.model_call_attempted) == (0, 0, False)
    assert runtime.claim_drug_label_run(case.db, case.id) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("timing", ["before_http", "during_http"])
async def test_running_cancel_pending_then_proven_uncalled_or_paid_without_accepted_draft(case, timing):
    queued(case)
    lease = runtime.claim_drug_label_run(case.db, case.id)
    calls = []
    if timing == "before_http":
        runtime.cancel_drug_label_run(case.db, case.actor, case.id)
    else:
        assert view(case)["usage_receipt"] is None
        case.db.rollback()

    def handler(request):
        calls.append(request)
        runtime.cancel_drug_label_run(case.db, case.actor, case.id)
        dto = view(case)
        assert dto["status"] == "cancelled" and dto["input_tokens"] is dto["output_tokens"] is None
        case.db.rollback()
        return httpx.Response(200, json=envelope("chat"))

    await runtime.execute_drug_label_claimed(case.id, lease, transport=httpx.MockTransport(handler))
    after = stored(case)
    receipt = storage.usage_receipt(case.db, after)
    assert after.run.status == "cancelled" and after.run.result_json == "{}" and after.artifact.result_json is None
    assert (receipt.input_tokens, receipt.output_tokens, receipt.model_call_attempted) == ((0, 0, False) if timing == "before_http" else (13, 7, True))
    assert len(calls) == (0 if timing == "before_http" else 1)


@pytest.mark.parametrize("axis", ["source", "role", "token", "prompt", "configuration", "config_deleted"])
def test_queued_current_changes_fail_with_proven_zero_without_granting_source(case, axis):
    queued(case)
    mutate(case, axis)
    assert runtime.claim_drug_label_run(case.db, case.id) is None
    after = stored(case)
    receipt = storage.usage_receipt(case.db, after)
    assert after.run.status == "failed" and after.artifact.result_json is None
    assert (receipt.input_tokens, receipt.output_tokens, receipt.model_call_attempted) == (0, 0, False)


@pytest.mark.asyncio
@pytest.mark.parametrize("axis", ["source", "role", "token", "prompt", "configuration", "config_deleted"])
async def test_inflight_current_changes_preserve_real_paid_usage_but_never_accept(case, axis):
    queued(case)

    def handler(request):
        mutate(case, axis)
        return httpx.Response(200, json=envelope("chat"))

    after = await execute(case, handler)
    receipt = storage.usage_receipt(case.db, after)
    assert after.run.status == "failed" and after.run.result_json == "{}" and after.artifact.accept_event_id is None
    assert (receipt.input_tokens, receipt.output_tokens, receipt.model_call_attempted) == (13, 7, True)


@pytest.mark.asyncio
@pytest.mark.parametrize("axis", ["partial_usage", "wrong_literal", "timeout"])
async def test_http_failure_nullable_components_are_not_invented_zero_or_retried(case, axis):
    queued(case)
    calls = []

    def handler(request):
        calls.append(request)
        if axis == "timeout":
            raise httpx.ReadTimeout("synthetic", request=request)
        value = envelope("chat")
        if axis == "partial_usage":
            del value["usage"]["completion_tokens"]
            del value["usage"]["total_tokens"]
        else:
            value = envelope("chat", {"fields": [{"field": "composition", "spans": [{"start": 0, "end": 1, "quote": "伪"}], "review_question": "请药师逐字核对。"}]})
        return httpx.Response(200, json=value)

    after = await execute(case, handler)
    dto = view(case)
    assert after.run.status == "failed" and after.artifact.result_json is None and len(calls) == 1
    expected = (13, None) if axis == "partial_usage" else (13, 7) if axis == "wrong_literal" else (None, None)
    assert (dto["input_tokens"], dto["output_tokens"]) == expected and dto["usage_receipt"]["model_call_attempted"] is True


@pytest.mark.asyncio
async def test_current_super_can_stop_withdrawn_task_as_frozen_without_executing_or_reviving_owner(case):
    queued(case)
    revoke(case)
    with pytest.raises(HTTPException):
        runtime.cancel_drug_label_run(case.db, case.actor, case.id)
    runtime.cancel_drug_label_run(case.db, case.users["super_admin_user"], case.id, frozen_audit=True)
    dto = view(case, user=case.users["super_admin_user"], audit=True)
    assert dto["status"] == "cancelled" and dto["usage_receipt"]["model_call_attempted"] is False
    assert dto["drug_label_findings"]["drug_label_source_record"]["audit_only"]
    assert not dto["drug_label_findings"]["drug_label_source_record"]["eligible"]
    with pytest.raises(HTTPException):
        view(case)


def test_current_count_uses_existing_feature_index_and_includes_broken_native_rows(case):
    queued(case)
    extra = AIRun(
        feature_key=runtime.FEATURE_KEY,
        requested_by=case.actor.user_id,
        provider_id=case.provider.provider_id,
        prompt_hash="0" * 64,
        context_digest="0" * 64,
        create_time=runtime._second(sources.utcnow()),
    )
    case.db.add(extra)
    case.db.commit()
    observed = []

    def inspect(state):
        if state.is_select:
            observed.append(str(state.statement.compile(dialect=mysql.dialect())))

    event.listen(case.db, "do_orm_execute", inspect)
    try:
        assert runtime.current_daily_count(case.db, case.actor.user_id, sources.utcnow()) >= 2
    finally:
        event.remove(case.db, "do_orm_execute", inspect)
    sql = next(value for value in observed if "count(" in value)
    assert "FORCE INDEX (idx_ai_run_feature_time)" in sql and "LOCK IN SHARE MODE" in sql


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["run_tokens", "run_error", "artifact_bytes", "delete_accept", "delete_usage"])
async def test_actual_terminal_sql_fault_never_commits_success_or_bad_receipt(case, fault):
    queued(case)
    lease = runtime.claim_drug_label_run(case.db, case.id)
    if fault in {"run_tokens", "run_error"}:
        assignment = "input_tokens=999" if fault == "run_tokens" else "error_code='forged'"
        trigger = f"AFTER UPDATE ON hoimsystem_ai_run WHEN NEW.run_id='{case.id}' AND NEW.status='succeeded' BEGIN UPDATE hoimsystem_ai_run SET {assignment} WHERE run_id=NEW.run_id; END"
    elif fault == "artifact_bytes":
        trigger = (
            "AFTER UPDATE ON hoimsystem_ai_drug_label_run_artifact WHEN NEW.result_json IS NOT NULL BEGIN UPDATE hoimsystem_ai_drug_label_run_artifact SET result_hash='"
            + "ab" * 32
            + "' WHERE run_id=NEW.run_id; END"
        )
    else:
        action = ACCEPT_ACTION if fault == "delete_accept" else USAGE_ACTION
        trigger = f"AFTER INSERT ON hoimsystem_ai_audit_event WHEN NEW.action='{action}' AND NEW.target='{case.id}' BEGIN DELETE FROM hoimsystem_ai_audit_event WHERE event_id=NEW.event_id; END"
    case.db.execute(text("CREATE TRIGGER label_runtime_fault " + trigger))
    case.db.commit()
    try:
        failure = None
        try:
            await runtime.execute_drug_label_claimed(case.id, lease, transport=httpx.MockTransport(lambda request: httpx.Response(200, json=envelope("chat"))))
        except HTTPException as exc:
            failure = exc
        after = stored(case)
        if fault == "delete_usage":
            assert failure is not None and failure.status_code == 409
            assert after.run.status == "running" and after.artifact.receipt_event_id is None
        else:
            assert failure is None and after.run.status == "failed" and after.run.error_code == "RESULT_STORAGE_ERROR"
            assert storage.usage_receipt(case.db, after).input_tokens == 13
        assert after.artifact.result_json is None and after.artifact.accept_event_id is None and after.run.result_json == "{}"
        assert case.db.query(AIAuditEvent).filter_by(action=ACCEPT_ACTION, target=case.id).count() == 0
    finally:
        case.db.rollback()
        case.db.execute(text("DROP TRIGGER label_runtime_fault"))
        case.db.commit()


def test_actual_artifact_classifies_after_all_markers_removed_but_no_raw_fallback(case):
    queued(case)
    case.db.query(AIRun).filter_by(run_id=case.id).update(
        {"feature_key": "some_legacy", "input_json": "{}", "evidence_json": "[]", "context_metadata_json": "{}", "result_json": "{}"}, synchronize_session=False
    )
    case.db.commit()
    assert storage.is_drug_label_run(case.db, case.db.get(AIRun, case.id))
    with pytest.raises(HTTPException) as failure:
        runtime.guard_drug_label_run_id(case.db, case.actor, case.id)
    assert failure.value.status_code == 409


@pytest.mark.parametrize("phase", ["create", "queued_cancel", "queued_invalid"])
def test_missing_specific_queue_or_uncalled_receipt_audit_rolls_back_entire_write(case, phase):
    if phase != "create":
        queued(case)
        identifier = case.id
    else:
        identifier = None
    if phase == "queued_invalid":
        revoke(case)
    action = CREATE_ACTION if phase == "create" else USAGE_ACTION
    case.db.execute(
        text(
            f"CREATE TRIGGER label_queue_audit_fault AFTER INSERT ON hoimsystem_ai_audit_event WHEN NEW.action='{action}' BEGIN DELETE FROM hoimsystem_ai_audit_event WHERE event_id=NEW.event_id; END"
        )
    )
    case.db.commit()
    before = case.db.query(AIRun).count()
    case.db.rollback()
    try:
        with pytest.raises(HTTPException) as failure:
            if phase == "create":
                queued(case)
            elif phase == "queued_cancel":
                runtime.cancel_drug_label_run(case.db, case.actor, identifier)
            else:
                runtime.claim_drug_label_run(case.db, identifier)
        assert failure.value.status_code == 409
        assert case.db.query(AIRun).count() == before
        if identifier:
            after = storage.load_snapshot(case.db, identifier)
            assert after.run.status == "queued" and after.artifact.receipt_event_id is None
    finally:
        case.db.rollback()
        case.db.execute(text("DROP TRIGGER label_queue_audit_fault"))
        case.db.commit()


@pytest.mark.asyncio
async def test_after_accept_source_change_is_rechecked_then_atomic_rollback_and_paid_failure(case):
    queued(case)
    lease = runtime.claim_drug_label_run(case.db, case.id)
    sku_id = case.source.snapshot.identity.pharmaceutical_id
    case.db.execute(
        text(
            f"CREATE TRIGGER label_accept_source_fault AFTER INSERT ON hoimsystem_ai_audit_event WHEN NEW.action='{ACCEPT_ACTION}' AND NEW.target='{case.id}' BEGIN UPDATE hoimsystem_pharmaceutical SET barcode='forged-after-accept' WHERE pharmaceutical_id={sku_id}; END"
        )
    )
    case.db.commit()
    try:
        await runtime.execute_drug_label_claimed(case.id, lease, transport=httpx.MockTransport(lambda request: httpx.Response(200, json=envelope("chat"))))
        after = stored(case)
        assert after.run.status == "failed" and after.run.error_code == "RESULT_STORAGE_ERROR"
        assert after.artifact.result_json is None and after.artifact.accept_event_id is None
        assert storage.usage_receipt(case.db, after).input_tokens == 13
        assert case.db.scalar(text("SELECT barcode FROM hoimsystem_pharmaceutical WHERE pharmaceutical_id=:id"), {"id": sku_id}) is None
    finally:
        case.db.rollback()
        case.db.execute(text("DROP TRIGGER label_accept_source_fault"))
        case.db.commit()
