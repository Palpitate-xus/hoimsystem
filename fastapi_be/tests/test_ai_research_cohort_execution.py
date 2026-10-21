"""Dedicated current Source -> real SQL queue/claim -> isolated model HTTP."""

import asyncio
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy.orm import sessionmaker

from app.ai.models import AIProvider
from app.ai.research_cohort_contract import canonical_json
from app.ai.research_cohort_execution import claim_research_run, execute_research_claimed
from app.ai.research_cohort_runtime import create_research_run, read_research_part
from tests.test_ai_research_cohort_result_storage import draft_for
from tests.test_ai_research_cohort_storage import artifact_foreign_keys as artifact_foreign_keys  # noqa: F401
from tests.test_ai_research_cohort_storage import configured as configured  # noqa: F401
from tests.test_ai_research_cohort_storage import research_case as research_case  # noqa: F401
from tests.test_ai_research_cohort_storage import storage_rows as storage_rows  # noqa: F401


@pytest.fixture
def runtime_case(configured):
    db, actor, _, source, values, case = configured
    identifier = actor.user_id
    provider = db.get(AIProvider, values["provider_id"])
    provider.api_base = "http://127.0.0.1:8825/v1"
    db.commit()
    sessions = []
    make = sessionmaker(bind=db.bind, autoflush=False, expire_on_commit=True)

    def factory():
        value = make()
        sessions.append(value)
        return value

    return {"db": db, "actor": actor, "actor_id": identifier, "source": source, "case_id": values["case_id"], "values": values, "identities": case, "factory": factory, "sessions": sessions}


def reply(source, kind="chat"):
    if kind == "responses":
        return {
            "status": "completed",
            "output": [{"type": "message", "role": "assistant", "status": "completed", "content": [{"type": "output_text", "text": canonical_json(draft_for(source))}]}],
            "usage": {"input_tokens": 32, "output_tokens": 6},
        }
    return {"choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": canonical_json(draft_for(source))}}], "usage": {"prompt_tokens": 32, "completion_tokens": 6}}


def created_claim(case):
    run_id = create_research_run(case["db"], case["actor"], {"research_cohort_case_id": case["case_id"], "question": "明确原研究问题🧪"})
    claim = claim_research_run(case["db"], run_id)
    return run_id, claim


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["chat", "responses"])
async def test_actual_dedicated_create_claim_http_complete_result_uses_no_sql_transaction_across_await(runtime_case, kind):
    case = runtime_case
    case["db"].get(AIProvider, case["values"]["provider_id"]).kind = kind
    case["db"].commit()
    run_id, claim = created_claim(case)
    calls = []

    def handler(incoming):
        assert all(not session.in_transaction() for session in case["sessions"])
        calls.append(incoming)
        return httpx.Response(200, json=reply(case["source"], kind))

    assert await execute_research_claimed(run_id, claim.lease_token, claim_event_id=claim.claim_event_id, transport=httpx.MockTransport(handler), session_factory=case["factory"])
    result = read_research_part(case["db"], SimpleNamespace(user_id=case["actor_id"]), run_id, "result")
    assert result["deterministic_evaluation"]["counts"] == case["source"]["counts"] and len(calls) == 1


@pytest.mark.asyncio
async def test_same_claim_delivered_twice_cannot_dispatch_the_model_twice(runtime_case):
    case = runtime_case
    run_id, claim = created_claim(case)
    entered, release = asyncio.Event(), asyncio.Event()
    calls = []

    async def handler(incoming):
        calls.append(incoming)
        entered.set()
        if len(calls) == 1:
            await release.wait()
        return httpx.Response(200, json=reply(case["source"]))

    async def execute():
        return await execute_research_claimed(run_id, claim.lease_token, claim_event_id=claim.claim_event_id, transport=httpx.MockTransport(handler), session_factory=case["factory"])

    first = asyncio.create_task(execute())
    await asyncio.wait_for(entered.wait(), 10)
    try:
        await execute()
    finally:
        release.set()
        await first
    assert len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["authorization", "provider", "prompt", "role", "token_epoch"])
async def test_inflight_current_changes_reject_result_but_keep_actual_paid_usage_and_no_super_clinical_escape(runtime_case, change):
    from sqlalchemy import func, text

    from app.ai.models import AIFeatureConfig, AIPromptVersion, AIRun
    from app.ai.research_cohort_artifact_models import AIResearchCohortRunResult
    from app.ai.research_cohort_cases import case_current
    from app.ai.research_cohort_receipts import read_usage_event, usage
    from app.ai.research_cohort_registry import review_registry_original
    from app.ai.research_cohort_runtime import describe_research_run
    from tests.test_ai_research_cohort_contract import BASIS

    case = runtime_case
    full = case_current(case["db"], case["actor"], case["case_id"])
    authorization_id = full["snapshot"]["capture"]["patient_authorizations"][0]["identity"]["source_record_id"]
    case["db"].commit()
    run_id, claim = created_claim(case)
    calls = []

    def handler(incoming):
        assert all(not session.in_transaction() for session in case["sessions"])
        calls.append(incoming)
        db = case["db"]
        if change == "authorization":
            review_registry_original(db, case["identities"]["super_admin_user"], "authorization", authorization_id, {"expected_revision": 2, "basis_note": BASIS}, revoke=True)
        elif change == "provider":
            row = db.get(AIProvider, case["values"]["provider_id"])
            row.enabled, row.revision = 0, row.revision + 1
            db.commit()
        elif change == "prompt":
            next_version = db.query(func.max(AIPromptVersion.version)).filter_by(feature_key="research_cohort").scalar() + 1
            prompt = AIPromptVersion(
                feature_key="research_cohort",
                version=next_version,
                task_prompt="明确由人工新增的完整自定义研究Task版本，不改旧版本。",
                change_note="Synthetic explicit current version change",
                created_by=case["actor_id"],
            )
            db.add(prompt)
            db.flush()
            config = db.get(AIFeatureConfig, "research_cohort")
            config.active_prompt_id, config.revision = prompt.prompt_id, config.revision + 1
            db.commit()
        else:
            db.execute(
                text("UPDATE hoimsystem_users SET " + ("user_role='patient'" if change == "role" else "token_invalid_before='2030-01-01 00:00:00'") + " WHERE user_id=:id"), {"id": case["actor_id"]}
            )
            db.commit()
        return httpx.Response(200, json=reply(case["source"]))

    assert await execute_research_claimed(run_id, claim.lease_token, claim_event_id=claim.claim_event_id, transport=httpx.MockTransport(handler), session_factory=case["factory"])
    assert len(calls) == 1 and case["db"].get(AIRun, run_id).status == "failed"
    assert case["db"].query(AIResearchCohortRunResult).filter_by(run_id=run_id).count() == 0
    assert read_usage_event(case["db"], run_id)["usage"] == usage(32, 6, True)
    super_id = case["identities"]["super_admin_user"].user_id
    short = describe_research_run(case["db"], SimpleNamespace(user_id=super_id), run_id, audit_only=True)
    assert not short["clinical_parts_available"] and short["binding"] is None and short["usage"] == usage(32, 6, True)
    assert "否认胸痛" not in canonical_json(short)
    from fastapi import HTTPException

    with pytest.raises(HTTPException):
        read_research_part(case["db"], SimpleNamespace(user_id=super_id), run_id, "result", audit_only=True)


@pytest.mark.asyncio
async def test_queued_and_claimed_before_call_cancellation_never_invent_paid_usage(runtime_case):
    from app.ai.research_cohort_execution import cancel_research_run
    from app.ai.research_cohort_receipts import read_usage_event, usage

    case = runtime_case
    queued = create_research_run(case["db"], case["actor"], {"research_cohort_case_id": case["case_id"]})
    cancel_research_run(case["db"], case["actor"], queued)
    assert claim_research_run(case["db"], queued) is None
    assert read_usage_event(case["db"], queued)["usage"] == usage(0, 0, False)
    case["db"].commit()
    run_id, claim = created_claim(case)
    cancel_research_run(case["db"], case["actor"], run_id)
    calls = []

    def handler(incoming):
        calls.append(incoming)
        return httpx.Response(200, json=reply(case["source"]))

    assert await execute_research_claimed(run_id, claim.lease_token, claim_event_id=claim.claim_event_id, transport=httpx.MockTransport(handler), session_factory=case["factory"])
    assert not calls and read_usage_event(case["db"], run_id)["usage"] == usage(0, 0, False)


@pytest.mark.asyncio
async def test_super_cancel_during_http_is_pending_then_paid_without_restoring_clinical_grants(runtime_case):
    from app.ai.research_cohort_artifact_models import AIResearchCohortRunResult
    from app.ai.research_cohort_cases import case_current
    from app.ai.research_cohort_execution import cancel_research_run
    from app.ai.research_cohort_receipts import read_usage_event, usage
    from app.ai.research_cohort_registry import review_registry_original
    from app.ai.research_cohort_runtime import describe_research_run
    from tests.test_ai_research_cohort_contract import BASIS

    case = runtime_case
    super_id = case["identities"]["super_admin_user"].user_id
    full = case_current(case["db"], case["actor"], case["case_id"])
    authorization = full["snapshot"]["capture"]["patient_authorizations"][0]["identity"]["source_record_id"]
    case["db"].commit()
    run_id, claim = created_claim(case)

    def handler(incoming):
        review_registry_original(case["db"], SimpleNamespace(user_id=super_id), "authorization", authorization, {"expected_revision": 2, "basis_note": BASIS}, revoke=True)
        cancel_research_run(case["db"], SimpleNamespace(user_id=super_id), run_id)
        pending = describe_research_run(case["db"], SimpleNamespace(user_id=super_id), run_id, audit_only=True)
        assert pending["cancellation_pending"] and pending["usage"] == usage(None, None, None)
        case["db"].commit()
        return httpx.Response(200, json=reply(case["source"]))

    assert await execute_research_claimed(run_id, claim.lease_token, claim_event_id=claim.claim_event_id, transport=httpx.MockTransport(handler), session_factory=case["factory"])
    actual = read_usage_event(case["db"], run_id)
    assert actual["status"] == "cancelled" and actual["usage"] == usage(32, 6, True)
    assert case["db"].query(AIResearchCohortRunResult).filter_by(run_id=run_id).count() == 0


@pytest.mark.parametrize("reserved", [False, True])
def test_interrupted_before_dispatch_is_known_zero_reserved_dispatch_is_unknown_and_never_replayed(runtime_case, reserved, monkeypatch):
    import datetime as dt

    from app.ai import research_cohort_execution as service
    from app.ai.research_cohort_receipts import read_usage_event, usage
    from app.ai.research_cohort_sources import utcnow

    case = runtime_case
    run_id, claim = created_claim(case)
    if reserved:
        service.reserve_research_dispatch(case["db"], run_id, claim.lease_token, claim.claim_event_id)
        case["db"].commit()
    future = utcnow() + dt.timedelta(minutes=20)
    monkeypatch.setattr(service, "utcnow", lambda: future)
    assert service.recover_interrupted_research_runs(case["db"], older_than_seconds=600) == 1
    receipt = read_usage_event(case["db"], run_id)
    assert receipt["error_code"] == "WORKER_INTERRUPTED"
    assert receipt["usage"] == (usage(None, None, None) if reserved else usage(0, 0, False))
    assert claim_research_run(case["db"], run_id) is None


@pytest.mark.parametrize("fault", ["dispatch_audit", "dispatch_fk", "source_body", "actor"])
def test_actual_dispatch_audit_or_cas_fault_rolls_back_both_receipt_and_reservation_before_http(runtime_case, fault):
    from fastapi import HTTPException
    from sqlalchemy import text
    from sqlalchemy.exc import IntegrityError

    from app.ai.models import AIAuditEvent, AIRun
    from app.ai.research_cohort_artifact_models import AIResearchCohortRunArtifact
    from app.ai.research_cohort_execution import reserve_research_dispatch

    case = runtime_case
    run_id, claim = created_claim(case)
    db = case["db"]
    before = db.query(AIAuditEvent).count()
    commands = {
        "dispatch_audit": "UPDATE hoimsystem_ai_audit_event SET action='wrong_dispatch' WHERE event_id=NEW.event_id;",
        "dispatch_fk": "UPDATE hoimsystem_ai_research_cohort_run_artifact SET dispatch_event_id=created_audit_event_id WHERE run_id=NEW.target;",
        "source_body": "UPDATE hoimsystem_medical_record SET symptom='dispatch后原记录变化' WHERE patient_id=" + str(case["identities"]["patient"].patient_id) + ";",
        "actor": "UPDATE hoimsystem_users SET user_role='patient' WHERE user_id=NEW.actor_id;",
    }
    db.execute(text("CREATE TRIGGER research_dispatch_fault AFTER INSERT ON hoimsystem_ai_audit_event WHEN NEW.action='research.task.dispatch.reserve' BEGIN " + commands[fault] + " END"))
    db.commit()
    try:
        with pytest.raises((HTTPException, IntegrityError)):
            reserve_research_dispatch(db, run_id, claim.lease_token, claim.claim_event_id)
        db.rollback()
        assert db.query(AIAuditEvent).count() == before
        assert db.get(AIResearchCohortRunArtifact, run_id).dispatch_event_id is None
        assert db.get(AIRun, run_id).status == "running"
    finally:
        db.rollback()
        db.execute(text("DROP TRIGGER research_dispatch_fault"))
        db.commit()


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["epoch", "queue_age"])
async def test_claimed_before_call_current_failure_has_true_zero_without_any_http_or_dispatch(runtime_case, change, monkeypatch):
    import datetime as dt

    from sqlalchemy import text

    from app.ai import research_cohort_execution as service
    from app.ai.research_cohort_artifact_models import AIResearchCohortRunArtifact
    from app.ai.research_cohort_receipts import read_usage_event, usage
    from app.ai.research_cohort_sources import utcnow
    from app.config import settings

    case = runtime_case
    run_id, claim = created_claim(case)
    if change == "epoch":
        case["db"].execute(text("UPDATE hoimsystem_users SET token_invalid_before='2030-01-01 00:00:00' WHERE user_id=:id"), {"id": case["actor_id"]})
        case["db"].commit()
    else:
        future = utcnow() + dt.timedelta(seconds=settings.AI_MAX_QUEUE_AGE_SECONDS + 5)
        monkeypatch.setattr(service, "utcnow", lambda: future)
    calls = []

    def handler(incoming):
        calls.append(incoming)
        return httpx.Response(200, json=reply(case["source"]))

    assert await execute_research_claimed(run_id, claim.lease_token, claim_event_id=claim.claim_event_id, transport=httpx.MockTransport(handler), session_factory=case["factory"])
    assert not calls and read_usage_event(case["db"], run_id)["usage"] == usage(0, 0, False)
    assert case["db"].get(AIResearchCohortRunArtifact, run_id).dispatch_event_id is None


@pytest.mark.asyncio
async def test_provider_http_failure_keeps_attempted_unknown_usage_without_model_body_or_retry(runtime_case):
    from app.ai.models import AIRun
    from app.ai.research_cohort_receipts import read_usage_event, usage

    case = runtime_case
    run_id, claim = created_claim(case)
    calls = []

    def handler(incoming):
        calls.append(incoming)
        return httpx.Response(503, content=b"PRIVATE_PROVIDER_ERROR_BODY_NEVER_RETAIN")

    assert await execute_research_claimed(run_id, claim.lease_token, claim_event_id=claim.claim_event_id, transport=httpx.MockTransport(handler), session_factory=case["factory"])
    row = case["db"].get(AIRun, run_id)
    assert row.status == "failed" and row.error_code == "PROVIDER_HTTP_ERROR" and len(calls) == 1
    assert "PRIVATE_PROVIDER" not in row.error_message and read_usage_event(case["db"], run_id)["usage"] == usage(None, None, True)
