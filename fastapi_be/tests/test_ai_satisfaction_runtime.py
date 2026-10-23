"""Actual synthetic creation and dedicated durable MockTransport execution."""

import datetime as dt
import json

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy import event, text
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import sessionmaker

from app.ai import satisfaction_execution as execution
from app.ai import satisfaction_receipts as receipts
from app.ai import satisfaction_runtime as runtime
from app.ai.models import AIAuditEvent, AIPromptVersion, AIRun
from app.ai.satisfaction_artifact_models import AISatisfactionRunArtifact
from app.ai.satisfaction_sources import revoke_case, utcnow
from app.ai.satisfaction_storage import RECEIPT_ACTION, load_snapshot
from app.models import Review, User
from tests.ai_admin_usage_assertions import assert_exact_usage_event
from tests.test_ai_satisfaction_gateway import envelope
from tests.test_ai_satisfaction_sources import BASIS
from tests.test_ai_satisfaction_sources import satisfaction_case as satisfaction_case  # noqa: F401
from tests.test_ai_satisfaction_storage import configured_run


@pytest.fixture
def runtime_case(db_session, satisfaction_case):
    case = configured_run(db_session, satisfaction_case)
    case["provider"].api_base = "http://127.0.0.1:11434/v1"
    case["config"].daily_limit = 10000
    db_session.commit()
    case["db"] = db_session
    case["factory"] = sessionmaker(bind=db_session.get_bind(), autoflush=False)
    case["req"] = {"feature_key": "feedback_analysis", "input": {"satisfaction_case_id": case["made"]["case_id"], "question": "请提出待人工核查的原摘录主题。"}}
    return case


def prepared(case, *, claimed=True):
    db = case["db"]
    run = runtime.create_satisfaction_run(db, case["admin_user"], case["req"])
    identifier = run.run_id
    lease = execution.claim_satisfaction_run(db, identifier) if claimed else None
    item = {
        "run_id": identifier,
        "lease": lease,
        "actor_id": case["admin_user"].user_id,
        "provider_id": case["provider"].provider_id,
        "review_id": case["review"].review_id,
        "case_id": case["made"]["case_id"],
        "draft": case["result"]["satisfaction_analysis"],
    }
    db.rollback()
    return item


def saved(case, item):
    db = case["db"]
    db.expire_all()
    run = db.get(AIRun, item["run_id"])
    result, usage = receipts.load_terminal(db, run)
    return run, result, usage


def test_create_uses_real_current_quota_full_anchor_and_short_queued_description(runtime_case):
    case, db = runtime_case, runtime_case["db"]
    statements = []

    def seen(state):
        if state.is_select:
            statements.append(str(state.statement.compile(dialect=mysql.dialect())))

    event.listen(db, "do_orm_execute", seen)
    try:
        item = prepared(case, claimed=False)
    finally:
        event.remove(db, "do_orm_execute", seen)
    assert any("count(" in sql.lower() and "hoimsystem_ai_run" in sql and ("FOR SHARE" in sql or "LOCK IN SHARE MODE" in sql) for sql in statements)
    run = db.get(AIRun, item["run_id"])
    short = runtime.describe_satisfaction_run(db, case["admin_user"], run, include_result=False)
    assert short["status"] == "queued" and "result" not in short and "satisfaction_findings" not in short
    assert short["usage"] == receipts.usage()
    assert db.get(AISatisfactionRunArtifact, run.run_id).usage_event_id is None
    assert all(len(getattr(run, name).encode()) <= 65535 for name in ("input_json", "evidence_json", "context_metadata_json"))
    assert "satisfaction_source" not in json.loads(run.input_json)["payload"]["context"]


def test_actual_saved_prompt_version_is_supported_then_changed_version_blocks_recheck(runtime_case):
    case, db = runtime_case, runtime_case["db"]
    version = AIPromptVersion(
        feature_key="feedback_analysis",
        version=9021,
        task_prompt="这是实际Super保存的完整自定义Task版本，仍遵守固定安全System和闭集结果。",
        change_note=BASIS,
        created_by=case["super_admin_user"].user_id,
    )
    db.add(version)
    db.flush()
    case["config"].active_prompt_id = version.prompt_id
    db.commit()
    item = prepared(case)
    run = db.get(AIRun, item["run_id"])
    assert load_snapshot(db, run)[0]["task_prompt"] == version.task_prompt and run.prompt_version == 9021
    case["config"].active_prompt_id = None
    db.commit()
    with pytest.raises(HTTPException) as error:
        runtime.recheck(db, run)
    assert error.value.status_code == 409


def test_daily_quota_is_not_refunded_by_cancellation_or_old_rr_count(runtime_case):
    case, db = runtime_case, runtime_case["db"]
    used = db.query(AIRun).filter_by(feature_key="feedback_analysis", requested_by=case["admin_user"].user_id).count()
    case["config"].daily_limit = used + 1
    db.commit()
    item = prepared(case, claimed=False)
    execution.cancel_satisfaction_run(db, case["admin_user"], item["run_id"])
    with pytest.raises(HTTPException) as error:
        runtime.create_satisfaction_run(db, case["admin_user"], case["req"])
    assert error.value.status_code == 429


@pytest.mark.parametrize("mutation", ["source", "actor", "task", "config"])
def test_actual_create_audit_sql_mutation_rolls_back_run_anchor_and_changed_original(runtime_case, mutation):
    case, db = runtime_case, runtime_case["db"]
    rid, uid = case["review"].review_id, case["admin_user"].user_id
    original = case["review"].comment
    before = db.query(AIRun).count()
    body = {
        "source": f"UPDATE hoimsystem_review SET comment='changed-in-create-audit' WHERE review_id={rid};",
        "actor": f"UPDATE hoimsystem_users SET user_role='patient' WHERE user_id={uid};",
        "task": "UPDATE hoimsystem_ai_run SET evidence_json='[]' WHERE run_id=NEW.target;",
        "config": "UPDATE hoimsystem_ai_feature_config SET validation_note='changed-in-audit' WHERE feature_key='feedback_analysis';",
    }[mutation]
    db.execute(text("CREATE TRIGGER satisfaction_create_fault AFTER INSERT ON hoimsystem_ai_audit_event WHEN NEW.action='run.satisfaction.create' BEGIN " + body + " END"))
    db.commit()
    try:
        with pytest.raises(HTTPException):
            runtime.create_satisfaction_run(db, case["admin_user"], case["req"])
        assert db.query(AIRun).count() == before and db.get(Review, rid).comment == original and db.get(User, uid).user_role == "admin"
    finally:
        db.rollback()
        db.execute(text("DROP TRIGGER satisfaction_create_fault"))
        db.commit()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["chat", "responses"])
async def test_complete_execution_has_zero_checked_out_sql_at_http_and_two_specific_audits(runtime_case, kind):
    case, db = runtime_case, runtime_case["db"]
    case["provider"].kind = kind
    db.commit()
    item = prepared(case)
    checked_out, calls = [], []
    engine = db.get_bind()

    def checkout(*_):
        checked_out.append(True)

    def checkin(*_):
        checked_out.pop()

    def handle(req):
        assert checked_out == []
        calls.append(req)
        return httpx.Response(200, json=envelope(kind, item["draft"]))

    event.listen(engine, "checkout", checkout)
    event.listen(engine, "checkin", checkin)
    try:
        await execution.execute_satisfaction_claimed(item["run_id"], item["lease"], transport=httpx.MockTransport(handle), session_factory=case["factory"])
        assert checked_out == []
    finally:
        event.remove(engine, "checkout", checkout)
        event.remove(engine, "checkin", checkin)
    run, result, receipt = saved(case, item)
    assert len(calls) == 1 and run.status == "succeeded" and result["satisfaction_analysis"] == item["draft"]
    assert receipt == receipts.usage(13, 7, True)
    artifact = db.get(AISatisfactionRunArtifact, run.run_id)
    assert artifact.receipt_event_id != artifact.usage_event_id
    assert db.get(AIAuditEvent, artifact.receipt_event_id).action == RECEIPT_ACTION
    assert db.get(AIAuditEvent, artifact.usage_event_id).action == receipts.ACTIONS["succeeded"]
    db.rollback()
    await execution.execute_satisfaction_claimed(item["run_id"], item["lease"], transport=httpx.MockTransport(handle), session_factory=case["factory"])
    assert len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["partial_usage", "invalid_draft", "timeout", "http_error"])
async def test_failed_paid_calls_preserve_independent_actual_nullable_usage(runtime_case, fault):
    case = runtime_case
    item, calls = prepared(case), []

    def handle(req):
        calls.append(req)
        if fault == "timeout":
            raise httpx.ReadTimeout("synthetic interruption", request=req)
        if fault == "http_error":
            return httpx.Response(503)
        packet = envelope("chat", item["draft"])
        if fault == "partial_usage":
            del packet["usage"]["completion_tokens"]
        else:
            packet["choices"][0]["message"]["content"] = '{"satisfaction_rate":100}'
        return httpx.Response(200, json=packet)

    await execution.execute_satisfaction_claimed(item["run_id"], item["lease"], transport=httpx.MockTransport(handle), session_factory=case["factory"])
    run, result, receipt = saved(case, item)
    assert_exact_usage_event(case["db"], item["run_id"], "satisfaction", receipt)
    assert len(calls) == 1 and run.status == "failed" and result is None and run.result_json == "{}"
    assert (
        receipt == receipts.usage(13, None, True) if fault == "partial_usage" else receipt == receipts.usage(13, 7, True) if fault == "invalid_draft" else receipt == receipts.usage(None, None, True)
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["source", "role", "token_epoch", "provider", "validation", "prompt", "queue_age"])
async def test_pre_call_changes_are_actual_zero_usage_and_no_http(runtime_case, mutation):
    case, db = runtime_case, runtime_case["db"]
    item = prepared(case)
    run = db.get(AIRun, item["run_id"])
    if mutation == "source":
        case["review"].comment += "来源变化"
    elif mutation == "role":
        case["admin_user"].user_role = "patient"
    elif mutation == "token_epoch":
        case["admin_user"].token_invalid_before = utcnow()
    elif mutation == "provider":
        case["provider"].max_output_tokens = 1024
    elif mutation == "validation":
        case["config"].validation_note += "变化"
    elif mutation == "prompt":
        version = AIPromptVersion(feature_key="feedback_analysis", version=9342, task_prompt="另一个实际保存的自定义Task版本", change_note=BASIS, created_by=case["super_admin_user"].user_id)
        db.add(version)
        db.flush()
        case["config"].active_prompt_id = version.prompt_id
    else:
        run.create_time = utcnow() - dt.timedelta(days=1)
    db.commit()
    db.rollback()
    await execution.execute_satisfaction_claimed(item["run_id"], item["lease"], transport=httpx.MockTransport(lambda _: pytest.fail("No model call expected")), session_factory=case["factory"])
    run, result, receipt = saved(case, item)
    assert run.status == "failed" and result is None and receipt == receipts.usage(0, 0, False)


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["source", "role", "token_epoch", "provider", "validation"])
async def test_post_call_current_changes_discard_draft_but_preserve_paid_usage(runtime_case, mutation):
    case = runtime_case
    item = prepared(case)

    def handle(req):
        with case["factory"]() as db:
            if mutation == "source":
                db.get(Review, item["review_id"]).comment += "执行期间来源变化"
            elif mutation == "role":
                db.get(User, item["actor_id"]).user_role = "patient"
            elif mutation == "token_epoch":
                db.get(User, item["actor_id"]).token_invalid_before = utcnow()
            elif mutation == "provider":
                from app.ai.models import AIProvider

                db.get(AIProvider, item["provider_id"]).max_output_tokens = 1024
            else:
                from app.ai.models import AIFeatureConfig

                db.get(AIFeatureConfig, "feedback_analysis").validation_note += "执行期间变化"
            db.commit()
        return httpx.Response(200, json=envelope("chat", item["draft"]))

    await execution.execute_satisfaction_claimed(item["run_id"], item["lease"], transport=httpx.MockTransport(handle), session_factory=case["factory"])
    run, result, receipt = saved(case, item)
    assert run.status == "failed" and result is None and receipt == receipts.usage(13, 7, True)


def test_true_queued_cancel_has_zero_receipt_but_running_cancel_stays_pending(runtime_case):
    case = runtime_case
    queued = prepared(case, claimed=False)
    execution.cancel_satisfaction_run(case["db"], case["admin_user"], queued["run_id"])
    run, result, receipt = saved(case, queued)
    assert run.status == "cancelled" and run.lease_token is None and result is None and receipt == receipts.usage(0, 0, False)
    case["db"].rollback()
    running = prepared(case)
    execution.cancel_satisfaction_run(case["db"], case["admin_user"], running["run_id"])
    run, result, receipt = saved(case, running)
    assert run.status == "cancelled" and run.latency_ms is None and result is None and receipt == receipts.usage()


@pytest.mark.asyncio
async def test_claimed_cancel_before_call_finalizes_exact_zero_without_http(runtime_case):
    case = runtime_case
    item = prepared(case)
    execution.cancel_satisfaction_run(case["db"], case["admin_user"], item["run_id"])
    case["db"].rollback()
    await execution.execute_satisfaction_claimed(item["run_id"], item["lease"], transport=httpx.MockTransport(lambda _: pytest.fail("No model call expected")), session_factory=case["factory"])
    run, result, receipt = saved(case, item)
    assert run.status == "cancelled" and result is None and receipt == receipts.usage(0, 0, False)


@pytest.mark.asyncio
async def test_cancel_during_call_keeps_actual_paid_counts_without_accepting_result(runtime_case):
    case = runtime_case
    item = prepared(case)

    def handle(req):
        with case["factory"]() as db:
            execution.cancel_satisfaction_run(db, db.get(User, item["actor_id"]), item["run_id"])
        return httpx.Response(200, json=envelope("chat", item["draft"]))

    await execution.execute_satisfaction_claimed(item["run_id"], item["lease"], transport=httpx.MockTransport(handle), session_factory=case["factory"])
    run, result, receipt = saved(case, item)
    assert run.status == "cancelled" and result is None and receipt == receipts.usage(13, 7, True)


@pytest.mark.parametrize("cancelled", [False, True])
def test_interrupted_claim_recovers_unknown_and_is_not_replayed(runtime_case, cancelled):
    case, db = runtime_case, runtime_case["db"]
    item = prepared(case)
    run = db.get(AIRun, item["run_id"])
    run.start_time = utcnow() - dt.timedelta(minutes=11)
    if cancelled:
        run.status = "cancelled"
    db.commit()
    assert execution.expire_interrupted_satisfaction_runs(db) >= 1
    run, result, receipt = saved(case, item)
    assert run.status == ("cancelled" if cancelled else "failed") and run.error_code == "WORKER_INTERRUPTED" and result is None and receipt == receipts.usage()
    assert execution.claim_satisfaction_run(db, run.run_id) is None


@pytest.mark.asyncio
async def test_super_frozen_audit_after_revoke_is_explicit_and_safe_without_raw(runtime_case):
    case, db = runtime_case, runtime_case["db"]
    item = prepared(case)
    await execution.execute_satisfaction_claimed(
        item["run_id"], item["lease"], transport=httpx.MockTransport(lambda _: httpx.Response(200, json=envelope("chat", item["draft"]))), session_factory=case["factory"]
    )
    db.expire_all()
    revoke_case(db, case["super_admin_user"], item["case_id"], {"expected_revision": 2, "basis_note": BASIS})
    with pytest.raises(HTTPException):
        runtime.describe_satisfaction_run(db, case["admin_user"], item["run_id"])
    value = runtime.describe_satisfaction_run(db, case["super_admin_user"], item["run_id"], audit_only=True)
    assert value["status"] == "succeeded" and value["result"]["satisfaction_analysis"] == item["draft"]
    assert value["satisfaction_findings"]["satisfaction_case"]["snapshot"] is None
