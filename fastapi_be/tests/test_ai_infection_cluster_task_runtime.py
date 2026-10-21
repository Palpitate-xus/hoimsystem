"""Actual local worker/cancel/authority/fault paths; no remote inference."""

# ruff: noqa: F811 -- actual Source/Task fixtures are registered by import.

import asyncio
import threading

import pytest
from fastapi import HTTPException
from sqlalchemy import event, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker

from app.ai import infection_cluster_registry as registry
from app.ai import infection_cluster_task_runtime as runtime
from app.ai import infection_cluster_task_storage as storage
from app.ai.infection_cluster_models import AIInfectionPurposeGrant
from app.ai.infection_cluster_run_models import AIInfectionRunArtifact as Artifact
from app.ai.models import AIAuditEvent, AIRun
from app.models import User
from tests.test_ai_infection_cluster_sources import NOTE, cas
from tests.test_ai_infection_cluster_task_storage import finish, profile_case, stage, task_case, task_text_queries  # noqa: F401


def factory(case):
    case["db"].rollback()
    return sessionmaker(bind=case["db"].get_bind(), expire_on_commit=False, autoflush=False)


@pytest.mark.asyncio
async def test_actual_async_local_worker_releases_all_sql_before_cpu_and_accepts_only_complete_result(task_case, monkeypatch):
    case, db = task_case, task_case["db"]
    rid = stage(case)
    sessions = factory(case)
    active = set()
    calls = []

    def checkout(conn, record, proxy):
        active.add(id(conn))

    def checkin(conn, record):
        active.discard(id(conn))

    pool = db.get_bind().pool
    event.listen(pool, "checkout", checkout)
    event.listen(pool, "checkin", checkin)
    calculate = runtime._calculate

    def guarded(value):
        assert not active, "SQL connection/transaction is still checked out during local CPU await"
        calls.append(True)
        return calculate(value)

    monkeypatch.setattr(runtime, "_calculate", guarded)
    try:
        await runtime.execute_run(sessions, rid)
    finally:
        event.remove(pool, "checkout", checkout)
        event.remove(pool, "checkin", checkin)
    assert calls == [True]
    with sessions() as current:
        run, artifact = current.get(AIRun, rid), current.get(Artifact, rid)
        assert run.status == "succeeded" and artifact.result_json is not None
        assert storage.load_result(current, current.get(User, case["author"].user_id), rid).family_size == 2


@pytest.mark.asyncio
async def test_actual_cpu_exception_records_unknown_attempt_without_external_tokens_or_partial_result(task_case, monkeypatch):
    case = task_case
    rid, sessions = stage(case), factory(case)

    def fault(value):
        raise RuntimeError("synthetic CPU/thread observation failure")

    monkeypatch.setattr(runtime, "_calculate", fault)
    await runtime.execute_run(sessions, rid)
    with sessions() as db:
        run, artifact = db.get(AIRun, rid), db.get(Artifact, rid)
        assert run.status == "failed" and run.result_json == "{}" and artifact.result_json is None
        usage = storage.usage(db, artifact, run)
        assert usage.calculation_attempted is None and usage.calculation_completed is None
        assert usage.input_tokens == usage.output_tokens == 0 and usage.model_call_attempted is False


def test_actual_queued_cancel_has_known_unattempted_zero_receipt_and_no_accepted_draft(task_case):
    case, db = task_case, task_case["db"]
    rid = stage(case)
    out = runtime.cancel(db, case["author"], rid)
    db.commit()
    assert out["status"] == "cancelled"
    run, artifact = db.get(AIRun, rid), db.get(Artifact, rid)
    usage = storage.usage(db, artifact, run)
    assert usage.calculation_attempted is usage.calculation_completed is False and usage.lease is None
    assert run.result_json == "{}" and artifact.result_json is artifact.accepted_lease is artifact.accepted_at is artifact.accept_event_id is None
    with pytest.raises(HTTPException):
        runtime.claim(db, rid)


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["cancel", "processing_withdrawal"])
async def test_actual_held_cpu_completion_cannot_restore_cancelled_or_withdrawn_source(task_case, monkeypatch, change):
    case = task_case
    rid, sessions = stage(case), factory(case)
    entered, release = threading.Event(), threading.Event()
    calculate = runtime._calculate

    def held(value):
        entered.set()
        assert release.wait(10)
        return calculate(value)

    monkeypatch.setattr(runtime, "_calculate", held)
    work = asyncio.create_task(runtime.execute_run(sessions, rid))
    assert await asyncio.to_thread(entered.wait, 10)
    try:
        with sessions() as other:
            if change == "cancel":
                runtime.cancel(other, other.get(User, case["author"].user_id), rid)
                other.commit()
                assert other.get(AIRun, rid).status == "cancelled" and other.get(Artifact, rid).usage_event_id is None
            else:
                grant = registry.record(other, other.get(AIInfectionPurposeGrant, case["grants"][0].record_id), "grant")
                registry.revoke_record(other, other.get(User, case["reviewer"].user_id), "grant", grant.record_id, cas(grant))
                other.commit()
    finally:
        release.set()
    await work
    with sessions() as current:
        run, artifact = current.get(AIRun, rid), current.get(Artifact, rid)
        assert run.status == ("cancelled" if change == "cancel" else "failed") and run.result_json == "{}"
        assert artifact.result_json is artifact.accept_event_id is None
        usage = storage.usage(current, artifact, run)
        assert usage.calculation_attempted is usage.calculation_completed is True and usage.input_tokens == usage.output_tokens == 0


@pytest.mark.parametrize("phase", ["success_tokens", "success_pointer", "usage_audit", "accept_audit", "fail_audit", "cancel_audit"])
def test_actual_after_write_trigger_faults_rollback_terminal_run_artifact_and_specific_audits(task_case, phase):
    case, db = task_case, task_case["db"]
    rid = stage(case)
    lease, source, frozen = runtime.claim(db, rid)
    db.commit()
    n = db.query(AIAuditEvent).count()
    if phase in {"success_tokens", "success_pointer"}:
        body = "UPDATE hoimsystem_ai_run SET input_tokens=9 WHERE run_id=NEW.run_id;" if phase == "success_tokens" else "UPDATE hoimsystem_ai_run SET result_json='{}' WHERE run_id=NEW.run_id;"
        trigger = "CREATE TRIGGER infection_terminal_bad AFTER UPDATE ON hoimsystem_ai_run WHEN NEW.status='succeeded' BEGIN " + body + " END"
    else:
        action = storage.ACCEPT if phase == "accept_audit" else storage.USAGE
        trigger = (
            "CREATE TRIGGER infection_terminal_bad AFTER INSERT ON hoimsystem_ai_audit_event WHEN NEW.action='"
            + action
            + "' BEGIN UPDATE hoimsystem_ai_audit_event SET detail_json='{}' WHERE event_id=NEW.event_id; END"
        )
    db.execute(text(trigger))
    db.commit()
    status = "failed" if phase == "fail_audit" else "cancelled" if phase == "cancel_audit" else "succeeded"
    try:
        with pytest.raises((HTTPException, ValueError, SQLAlchemyError)):
            runtime.terminal(
                db,
                rid,
                lease,
                status=status,
                result=runtime.engine.evaluate(source) if status == "succeeded" else None,
                attempted=True,
                completed=status == "succeeded",
                milliseconds=1,
                error_code=None if status == "succeeded" else "SYNTHETIC_FAILURE",
            )
        assert db.get(AIRun, rid).status == "running" and db.get(AIRun, rid).input_tokens == 0
        assert db.get(Artifact, rid).result_json is db.get(Artifact, rid).usage_event_id is db.get(Artifact, rid).accept_event_id is None
        assert db.query(AIAuditEvent).count() == n
    finally:
        db.rollback()
        db.execute(text("DROP TRIGGER infection_terminal_bad"))
        db.commit()


def test_actual_allowed_to_allowed_requester_role_change_rejects_id_only_worker_before_task_text(task_case):
    case, db = task_case, task_case["db"]
    admin = db.query(User).filter_by(user_role="admin").first()
    grant = registry.create_grant(
        db,
        case["author"],
        dict(
            patient_id=case["patient"].patient_id,
            user_id=admin.user_id,
            purpose="infection_surveillance_processing",
            valid_from="2026-10-01T00:00:00.000000Z",
            valid_to="2026-11-01T00:00:00.000000Z",
            basis_note=NOTE,
        ),
    )
    db.commit()
    registry.review_record(db, case["reviewer"], "grant", grant.record_id, {**cas(grant), "decision": "publish", "privacy_review": "confirmed", "faithfulness_review": "confirmed"})
    db.commit()
    rid = runtime.create_run(db, admin, case["task_request"])["run_id"]
    db.commit()
    uid = admin.user_id
    db.execute(text("UPDATE hoimsystem_users SET user_role='director' WHERE user_id=:id"), {"id": uid})
    db.commit()
    queries = []

    def capture(conn, cursor, sql, params, ctx, many):
        queries.append(sql)

    event.listen(db.get_bind(), "before_cursor_execute", capture)
    try:
        with pytest.raises(HTTPException):
            runtime.claim(db, rid)
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", capture)
    assert task_text_queries(queries) == []


@pytest.mark.parametrize("status", ["queued", "running", "cancelled"])
def test_interrupted_tasks_close_technical_receipts_after_purpose_withdrawal_without_task_body_or_retry(task_case, monkeypatch, status):
    import datetime as dt

    case, db = task_case, task_case["db"]
    rid = stage(case)
    if status != "queued":
        runtime.claim(db, rid)
        db.commit()
    if status == "cancelled":
        runtime.cancel(db, case["author"], rid)
        db.commit()
    grant = case["grants"][0]
    registry.revoke_record(db, case["reviewer"], "grant", grant.record_id, cas(grant))
    db.commit()
    original = registry.utcnow()
    monkeypatch.setattr(registry, "utcnow", lambda: original + dt.timedelta(days=2))
    queries = []

    def capture(conn, cursor, sql, params, ctx, many):
        queries.append(sql)

    event.listen(db.get_bind(), "before_cursor_execute", capture)
    try:
        assert runtime.expire_interrupted_runs(db) == 1
        assert runtime.expire_interrupted_runs(db) == 0
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", capture)
    assert task_text_queries(queries) == []
    artifact, raw = storage.verify_technical_run(db, rid)
    from types import SimpleNamespace

    usage = storage.usage(db, artifact, SimpleNamespace(**{key: value for key, value in raw.items() if key not in runtime.t.RAW_FIELDS}))
    assert usage.terminal_status == ("cancelled" if status == "cancelled" else "failed")
    assert usage.calculation_attempted is (False if status == "queued" else None)
    assert usage.model_call_attempted is False and usage.input_tokens == usage.output_tokens == 0


@pytest.mark.asyncio
async def test_cancel_after_actual_claim_before_dispatch_records_known_no_cpu_and_does_not_calculate(task_case, monkeypatch):
    case, db = task_case, task_case["db"]
    rid = stage(case)
    lease = runtime.claim_for_shared(db, rid)
    assert lease is not None
    runtime.cancel(db, case["author"], rid)
    db.commit()

    def forbidden(value):
        raise AssertionError("Cancelled-before-dispatch task attempted CPU calculation")

    monkeypatch.setattr(runtime, "_calculate", forbidden)
    await runtime.execute_claimed(factory(case), rid, lease)
    artifact, run = db.get(Artifact, rid), db.get(AIRun, rid)
    receipt = storage.usage(db, artifact, run)
    assert run.status == "cancelled" and receipt.calculation_attempted is False and receipt.calculation_completed is False


@pytest.mark.parametrize("status", ["queued", "running"])
def test_actual_cancel_request_specific_audit_deleted_after_insert_rolls_back_the_status(task_case, status):
    case, db = task_case, task_case["db"]
    rid = stage(case)
    if status == "running":
        runtime.claim(db, rid)
        db.commit()
    before = db.query(AIAuditEvent).count()
    db.execute(
        text(
            "CREATE TRIGGER remove_infection_cancel_audit AFTER INSERT ON hoimsystem_ai_audit_event WHEN NEW.action='run.infection_cluster.cancel_request' BEGIN DELETE FROM hoimsystem_ai_audit_event WHERE event_id=NEW.event_id; END"
        )
    )
    db.commit()
    try:
        with pytest.raises(HTTPException) as exc:
            runtime.cancel(db, case["author"], rid)
        assert exc.value.status_code == 409
        db.expire_all()
        assert db.get(AIRun, rid).status == status and db.get(Artifact, rid).usage_event_id is None
        assert db.query(AIAuditEvent).count() == before
    finally:
        db.rollback()
        db.execute(text("DROP TRIGGER remove_infection_cancel_audit"))
        db.commit()
