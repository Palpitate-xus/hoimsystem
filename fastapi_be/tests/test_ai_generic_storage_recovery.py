"""Fresh SQL transactions settle generic task failures without another model call."""

import datetime
import json
import logging
import sys
import time
import uuid

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy import event

from app import database
from app.ai import runtime, worker
from app.ai.gateway import AIExecutionError
from app.ai.governance import encode_json
from app.ai.models import AIAuditEvent, AIRun, utcnow
from app.ai.schemas import RunRequest
from tests.test_ai_runtime import clean_ai_tasks as clean_ai_tasks  # noqa: F401
from tests.test_ai_runtime import configure, successful_transport
from tests.test_ai_worker_failure_reporting import PRIVATE_ERROR, interrupted_task


def queue(db, users):
    configure(db, users)
    row = runtime.create_run(db, users["doctor_user"], RunRequest(feature_key="patient_summary", patient_id=users["patient"].patient_id))
    return row, runtime.claim_next_run(db)


@pytest.mark.asyncio
@pytest.mark.parametrize("counters", [(5, 7), (0, 0), (None, None), (7, None), (None, 9)])
async def test_one_failed_terminal_transaction_uses_fresh_session_and_exact_usage(db_session, seed_data, monkeypatch, counters):
    row, claim = queue(db_session, seed_data)
    original, sessions, requests = runtime._record_text_retry_usage, [], []
    baseline = successful_transport(requests)

    def respond(request):
        content = baseline.handle_request(request).json()
        content["usage"] = {"prompt_tokens": counters[0], "completion_tokens": counters[1]}
        return httpx.Response(200, json=content)

    def first_transaction_fails(db, run, details):
        sessions.append(db)
        original(db, run, details)
        db.flush()
        if len(sessions) == 1:
            raise RuntimeError(PRIVATE_ERROR)

    monkeypatch.setattr(runtime, "_record_text_retry_usage", first_transaction_fails)
    await runtime.execute_claimed(*claim, transport=httpx.MockTransport(respond))
    assert len(requests) == 1 and len(sessions) == 2 and sessions[0] is not sessions[1]
    db_session.refresh(row)
    assert row.status == "failed" and row.error_code == "RESULT_STORAGE_ERROR"
    assert row.result_json == "{}" and (row.input_tokens, row.output_tokens) == counters
    assert row.finish_time is not None and row.latency_ms >= 0 and row.lease_token == claim[1]
    failure = db_session.query(AIAuditEvent).filter_by(target=row.run_id, action="run.result_storage.failed").one()
    assert json.loads(failure.detail_json)["input_tokens"] == counters[0]
    usage = db_session.query(AIAuditEvent).filter_by(target=row.run_id, action="run.text_model.usage").one()
    assert json.loads(usage.detail_json)["output_tokens"] == counters[1]
    assert PRIVATE_ERROR not in failure.detail_json + usage.detail_json + row.error_message
    assert runtime.claim_next_run(db_session) is None


@pytest.mark.asyncio
async def test_cancelled_inflight_storage_failure_preserves_cancellation_and_paid_usage(db_session, seed_data, monkeypatch):
    row, claim = queue(db_session, seed_data)
    original, calls, requests = runtime._record_text_retry_usage, [], []
    baseline = successful_transport(requests)

    def respond(request):
        with database.SessionLocal() as other:
            other.query(AIRun).filter_by(run_id=row.run_id).update({"status": "cancelled"})
            other.commit()
        return baseline.handle_request(request)

    def first_transaction_fails(db, run, details):
        calls.append(db)
        if len(calls) == 1:
            raise RuntimeError(PRIVATE_ERROR)
        original(db, run, details)

    monkeypatch.setattr(runtime, "_record_text_retry_usage", first_transaction_fails)
    await runtime.execute_claimed(*claim, transport=httpx.MockTransport(respond))
    db_session.refresh(row)
    assert row.status == "cancelled" and row.result_json == "{}"
    assert (row.input_tokens, row.output_tokens) == (5, 7) and row.latency_ms is not None
    assert len(requests) == 1 and len(calls) == 2 and calls[0] is not calls[1]
    assert db_session.query(AIAuditEvent).filter_by(target=row.run_id, action="run.result_storage.failed").count() == 1


@pytest.mark.asyncio
async def test_second_storage_failure_is_redacted_and_existing_recovery_finishes_without_replay(db_session, seed_data, monkeypatch, caplog):
    row, claim = queue(db_session, seed_data)
    requests = []

    def unavailable(*args, **kwargs):
        raise RuntimeError(PRIVATE_ERROR)

    monkeypatch.setattr(runtime, "_record_text_retry_usage", unavailable)
    with caplog.at_level(logging.WARNING, logger="ai.runtime"):
        await runtime.execute_claimed(*claim, transport=successful_transport(requests))
    db_session.refresh(row)
    assert row.status == "running" and row.result_json == "{}"
    assert len(requests) == 1 and PRIVATE_ERROR not in caplog.text
    assert "phase=store_failure error_type=RuntimeError" in caplog.text
    assert db_session.query(AIAuditEvent).filter_by(target=row.run_id, action="run.result_storage.failed").count() == 0
    row.start_time = utcnow() - datetime.timedelta(minutes=11)
    db_session.commit()
    assert runtime.expire_interrupted_runs(db_session) == 1
    db_session.refresh(row)
    assert row.status == "failed" and row.error_code == "WORKER_INTERRUPTED"
    assert (row.input_tokens, row.output_tokens) == (None, None)
    assert runtime.claim_next_run(db_session) is None and len(requests) == 1


@pytest.mark.asyncio
async def test_final_session_creation_failure_also_settles_in_a_fresh_session(db_session, seed_data, monkeypatch, caplog):
    row, claim = queue(db_session, seed_data)
    factory, requests, fail_next = database.SessionLocal, [], False
    baseline = successful_transport(requests)

    def sessions():
        nonlocal fail_next
        if fail_next:
            fail_next = False
            raise RuntimeError(PRIVATE_ERROR)
        return factory()

    def respond(request):
        nonlocal fail_next
        fail_next = True
        return baseline.handle_request(request)

    monkeypatch.setattr(database, "SessionLocal", sessions)
    with caplog.at_level(logging.WARNING, logger="ai.runtime"):
        await runtime.execute_claimed(*claim, transport=httpx.MockTransport(respond))
    db_session.refresh(row)
    assert row.status == "failed" and row.error_code == "RESULT_STORAGE_ERROR"
    assert row.result_json == "{}" and (row.input_tokens, row.output_tokens) == (5, 7)
    assert len(requests) == 1 and "phase=store_transaction error_type=RuntimeError" in caplog.text
    assert PRIVATE_ERROR not in caplog.text


def test_technical_settlement_never_loads_patient_user_or_frozen_task_text(db_session, seed_data):
    row = interrupted_task(db_session, seed_data)
    identifier, lease, feature = row.run_id, row.lease_token, row.feature_key
    selects = []

    def technical_only(connection, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            selects.append(statement)
            assert not any(value in statement for value in ("hoimsystem_patient", "hoimsystem_users", "input_json", "result_json", "evidence_json", "context_metadata_json"))

    engine = db_session.get_bind()
    event.listen(engine, "before_cursor_execute", technical_only)
    try:
        runtime._settle_generic_storage_failure(database.SessionLocal, identifier, lease, feature, 5, 7, time.monotonic(), None)
    finally:
        event.remove(engine, "before_cursor_execute", technical_only)
    db_session.refresh(row)
    assert selects and row.status == "failed" and (row.input_tokens, row.output_tokens) == (5, 7)


@pytest.mark.parametrize("changed", ["lease", "succeeded", "failed", "settled_cancelled"])
def test_fallback_cannot_overwrite_another_lease_or_completed_task(db_session, seed_data, changed):
    row = interrupted_task(db_session, seed_data, (7, 9))
    original_lease = row.lease_token
    if changed == "lease":
        row.lease_token = str(uuid.uuid4())
    else:
        row.status = "cancelled" if changed == "settled_cancelled" else changed
        row.latency_ms = 1
    db_session.commit()
    before = (row.status, row.lease_token, row.input_tokens, row.output_tokens, row.latency_ms)
    runtime._settle_generic_storage_failure(database.SessionLocal, row.run_id, original_lease, row.feature_key, None, None, time.monotonic(), None)
    db_session.refresh(row)
    assert (row.status, row.lease_token, row.input_tokens, row.output_tokens, row.latency_ms) == before
    assert db_session.query(AIAuditEvent).filter_by(target=row.run_id).count() == 0


@pytest.mark.parametrize("kind", ["claimed", "unclaimed", "missing_lease", "live", "known_pair", "receipt", "old_receipt", "settled", "already_unknown"])
def test_only_unsettled_expired_claimed_cancellation_gets_unknown_usage(db_session, seed_data, kind):
    counters = (7, 0) if kind == "known_pair" else (None, None) if kind == "already_unknown" else (0, 0)
    row = interrupted_task(db_session, seed_data, counters, status="cancelled", minutes=1 if kind == "live" else 11)
    row.finish_time = utcnow()
    if kind == "unclaimed":
        row.start_time, row.lease_token = None, None
    elif kind == "missing_lease":
        row.lease_token = None
    elif kind == "settled":
        row.latency_ms = 0
    if kind in {"receipt", "old_receipt"}:
        db_session.add(
            AIAuditEvent(
                actor_id=row.requested_by,
                target=row.run_id,
                action="run.text_model.usage",
                detail_json=encode_json(
                    {"schema_version": "text_model_retry_usage_v1", "lease_token": row.lease_token if kind == "receipt" else str(uuid.uuid4()), "input_tokens": 0, "output_tokens": 0}
                ),
            )
        )
    db_session.commit()
    finish, lease = row.finish_time, row.lease_token
    eligible = kind in {"claimed", "old_receipt"}
    assert runtime.expire_interrupted_runs(db_session) == int(eligible)
    db_session.refresh(row)
    assert row.status == "cancelled" and row.finish_time == finish and row.lease_token == lease
    assert (row.input_tokens, row.output_tokens) == ((None, None) if eligible else counters)
    assert runtime.expire_interrupted_runs(db_session) == 0
    assert runtime.claim_next_run(db_session) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("error_type", [AIExecutionError, RuntimeError, HTTPException])
async def test_retry_error_metadata_is_preserved_in_generic_audit_only(db_session, seed_data, monkeypatch, error_type):
    row, claim = queue(db_session, seed_data)
    details = {"attempts": 2, "max_attempts": 3, "earlier_usage_unknown": True, "failure_category": "network", "http_status": 503, "stop_reason": "deadline"}
    if error_type is AIExecutionError:
        error = error_type("MODEL_RETRY_EXHAUSTED", "模型服务暂时不可用")
    elif error_type is HTTPException:
        error = error_type(503, "模型服务暂时不可用")
    else:
        error = error_type(PRIVATE_ERROR)
    error.retry_details, error.model_call_attempted = details, True

    async def fail(*args, **kwargs):
        raise error

    monkeypatch.setattr(runtime, "generate", fail)
    await runtime.execute_claimed(*claim)
    db_session.refresh(row)
    assert row.status == "failed" and (row.input_tokens, row.output_tokens) == (None, None)
    receipt = db_session.query(AIAuditEvent).filter_by(target=row.run_id, action="run.text_model.usage").one()
    assert all(json.loads(receipt.detail_json)[key] == value for key, value in details.items())


def test_once_exits_with_safe_log_and_no_exception_traceback(monkeypatch, caplog, capsys):
    async def fail():
        raise RuntimeError(PRIVATE_ERROR)

    monkeypatch.setattr(worker, "process_one", fail)
    monkeypatch.setattr(sys, "argv", ["worker", "--once"])
    with caplog.at_level(logging.WARNING, logger="ai.worker"), pytest.raises(SystemExit) as exited:
        worker.main()
    assert exited.value.code == 1 and exited.value.__suppress_context__
    assert "phase=worker_exit error_type=RuntimeError" in caplog.text
    output = capsys.readouterr()
    assert PRIVATE_ERROR not in caplog.text + output.out + output.err
    assert "Traceback" not in output.err
