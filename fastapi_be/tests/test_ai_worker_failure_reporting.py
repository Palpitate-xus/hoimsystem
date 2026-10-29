"""Real task recovery and redacted worker diagnostics under infrastructure faults."""

import asyncio
import datetime
import logging
import uuid

import pytest

from app.ai import runtime, worker
from app.ai.governance import encode_json
from app.ai.models import AIAuditEvent, AIRun, utcnow
from app.ai.schemas import RunRequest
from tests.test_ai_runtime import clean_ai_tasks as clean_ai_tasks  # noqa: F401
from tests.test_ai_runtime import configure, successful_transport

PRIVATE_ERROR = "SQL parameters: patient chart; prompt; credential=private-test-sentinel"


def interrupted_task(db, users, counters=(0, 0), *, status="running", minutes=11):
    row = AIRun(
        feature_key="patient_summary",
        requested_by=users["doctor_user"].user_id,
        patient_id=users["patient"].patient_id,
        prompt_hash="0" * 64,
        context_digest="0" * 64,
        status=status,
        lease_token=str(uuid.uuid4()),
        start_time=utcnow() - datetime.timedelta(minutes=minutes),
    )
    db.add(row)
    db.flush()
    # Assign after insertion so SQLAlchemy's INSERT defaults cannot replace NULL.
    row.input_tokens, row.output_tokens = counters
    db.commit()
    return row


@pytest.mark.parametrize("counters", [(0, 0), (7, 0), (0, 9), (7, 9), (None, None), (None, 0), (0, None), (7, None), (None, 9)])
def test_expiry_changes_only_the_unreceipted_default_pair_to_unknown(db_session, seed_data, counters):
    row = interrupted_task(db_session, seed_data, counters)
    lease = row.lease_token
    assert runtime.expire_interrupted_runs(db_session) == 1
    db_session.refresh(row)
    assert (row.input_tokens, row.output_tokens) == ((None, None) if counters == (0, 0) else counters)
    assert row.status == "failed" and row.error_code == "WORKER_INTERRUPTED"
    assert row.finish_time is not None and row.lease_token == lease
    assert row.latency_ms is None and row.result_json == "{}"
    assert runtime.expire_interrupted_runs(db_session) == 0
    assert runtime.claim_next_run(db_session) is None


@pytest.mark.parametrize("receipt", ["current_zero", "current_partial", "current_unknown", "old_lease", "other_schema", "other_action", "malformed"])
def test_expiry_preserves_current_independent_receipts_without_rewriting_them(db_session, seed_data, receipt):
    row = interrupted_task(db_session, seed_data)
    details = encode_json(
        {
            "schema_version": "other" if receipt == "other_schema" else "text_model_retry_usage_v1",
            "lease_token": str(uuid.uuid4()) if receipt == "old_lease" else row.lease_token,
            "terminal_status": "failed",
            "input_tokens": None if receipt == "current_unknown" else 0,
            "output_tokens": None if receipt in {"current_unknown", "current_partial"} else 0,
            "complete": receipt not in {"current_unknown", "current_partial"},
            "model_call_attempted": True,
            "attempts": 1,
            "max_attempts": 3,
            "earlier_usage_unknown": receipt == "current_unknown",
        }
    )
    if receipt == "malformed":
        details = '{"invalid-json":'
    event = AIAuditEvent(
        actor_id=seed_data["doctor_user"].user_id,
        action="run.native.usage" if receipt == "other_action" else "run.text_model.usage",
        target=row.run_id,
        detail_json=details,
    )
    db_session.add(event)
    db_session.commit()
    event_id = event.event_id
    assert runtime.expire_interrupted_runs(db_session) == 1
    db_session.refresh(row)
    assert (row.input_tokens, row.output_tokens) == ((0, 0) if receipt.startswith("current_") else (None, None))
    assert db_session.get(AIAuditEvent, event_id).detail_json == details
    assert db_session.query(AIAuditEvent).filter_by(target=row.run_id).count() == 1


@pytest.mark.parametrize("status,minutes", [("cancelled", 1), ("succeeded", 11), ("running", 1)])
def test_expiry_keeps_other_statuses_and_live_leases_unchanged(db_session, seed_data, status, minutes):
    row = interrupted_task(db_session, seed_data, status=status, minutes=minutes)
    assert runtime.expire_interrupted_runs(db_session) == 0
    db_session.refresh(row)
    assert row.status == status and (row.input_tokens, row.output_tokens) == (0, 0)
    assert row.finish_time is None


@pytest.mark.asyncio
async def test_unexpected_inference_error_has_safe_searchable_log_and_public_error(db_session, seed_data, caplog, monkeypatch):
    configure(db_session, seed_data)
    row = runtime.create_run(db_session, seed_data["doctor_user"], RunRequest(feature_key="patient_summary", patient_id=seed_data["patient"].patient_id))
    identifier = row.run_id

    async def fail(*args, **kwargs):
        raise RuntimeError(PRIVATE_ERROR)

    monkeypatch.setattr(runtime, "generate", fail)
    with caplog.at_level(logging.WARNING, logger="ai.runtime"):
        await runtime.execute_claimed(*runtime.claim_next_run(db_session))
    db_session.refresh(row)
    assert row.status == "failed" and row.error_code == "TASK_EXECUTION_ERROR"
    assert PRIVATE_ERROR not in row.error_message
    assert f"run_id={identifier} feature=patient_summary phase=inference error_type=RuntimeError" in caplog.text
    assert PRIVATE_ERROR not in caplog.text
    assert all(record.exc_info is None for record in caplog.records)


@pytest.mark.asyncio
async def test_terminal_storage_failure_logs_type_and_context_without_sql_values(db_session, seed_data, caplog, monkeypatch):
    configure(db_session, seed_data)
    row = runtime.create_run(db_session, seed_data["doctor_user"], RunRequest(feature_key="patient_summary", patient_id=seed_data["patient"].patient_id))
    identifier = row.run_id
    requests = []

    def fail(*args, **kwargs):
        raise RuntimeError(PRIVATE_ERROR)

    monkeypatch.setattr(runtime, "_record_text_retry_usage", fail)
    with caplog.at_level(logging.WARNING, logger="ai.runtime"):
        await runtime.execute_claimed(*runtime.claim_next_run(db_session), transport=successful_transport(requests))
    assert len(requests) == 1
    assert f"run_id={identifier} feature=patient_summary phase=store_result error_type=RuntimeError" in caplog.text
    assert PRIVATE_ERROR not in caplog.text
    assert all(record.exc_info is None for record in caplog.records)
    # Leave no unfinished task for subsequent tests; this is only fault injection.
    db_session.expire_all()
    row.status = "failed"
    db_session.commit()


def test_safe_log_rejects_untrusted_identifiers_and_feature_text(caplog):
    with caplog.at_level(logging.WARNING, logger="ai.worker"):
        runtime._log_execution_failure(PRIVATE_ERROR, PRIVATE_ERROR, "claim", ValueError(PRIVATE_ERROR), event_logger=worker.logger)
    assert "run_id=- feature=- phase=claim error_type=ValueError" in caplog.text
    assert PRIVATE_ERROR not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["recover_research", "recover_deidentification", "recover_tasks", "claim", "execute"])
async def test_queue_failure_identifies_phase_without_exception_body(db_session, caplog, monkeypatch, phase):
    from app.ai import deidentification_runtime, research_cohort_execution

    identifier, lease = str(uuid.uuid4()), str(uuid.uuid4())
    failure = RuntimeError(PRIVATE_ERROR)

    def fail(*args, **kwargs):
        raise failure

    async def fail_async(*args, **kwargs):
        raise failure

    def idle(*args, **kwargs):
        return None

    monkeypatch.setattr(research_cohort_execution, "recover_interrupted_research_runs", fail if phase == "recover_research" else idle)
    monkeypatch.setattr(deidentification_runtime, "expire_interrupted_deidentification_runs", fail if phase == "recover_deidentification" else idle)
    monkeypatch.setattr(worker, "expire_interrupted_runs", fail if phase == "recover_tasks" else idle)
    monkeypatch.setattr(worker, "claim_next_run", fail if phase == "claim" else lambda db: (identifier, lease))
    monkeypatch.setattr(worker, "execute_claimed", fail_async)
    with caplog.at_level(logging.WARNING, logger="ai.worker"), pytest.raises(RuntimeError) as caught:
        await worker.process_one()
    assert caught.value is failure
    assert f"run_id={identifier if phase == 'execute' else '-'} feature=- phase={phase} error_type=RuntimeError" in caplog.text
    assert PRIVATE_ERROR not in caplog.text
    assert all(record.exc_info is None for record in caplog.records)


@pytest.mark.asyncio
async def test_poll_failures_back_off_to_cap_and_reset_after_success(caplog, monkeypatch):
    attempts, sleeps = 0, []

    async def poll():
        nonlocal attempts
        attempts += 1
        if attempts == 11:
            return False
        if attempts == 13:
            raise asyncio.CancelledError
        raise RuntimeError(PRIVATE_ERROR)

    async def sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr(worker, "process_one", poll)
    monkeypatch.setattr(worker.asyncio, "sleep", sleep)
    with caplog.at_level(logging.WARNING, logger="ai.worker"), pytest.raises(asyncio.CancelledError):
        await worker.worker_loop(0.25)
    assert sleeps == [1.0, 2.0, 4.0, 8.0, 16.0, 32.0, 60.0, 60.0, 60.0, 60.0, 0.25, 1.0]
    assert "phase=poll error_type=RuntimeError retry_seconds=60.0" in caplog.text
    assert PRIVATE_ERROR not in caplog.text
    assert all(record.exc_info is None for record in caplog.records)
