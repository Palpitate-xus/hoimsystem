"""Actual current artifacts recover interrupted leases without model replay."""

import datetime

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy import text

from app.ai import drug_label_runtime as runtime
from app.ai import drug_label_sources as sources
from app.ai import drug_label_storage as storage
from app.ai.drug_label_run_contract import USAGE_ACTION
from app.config import settings
from tests.test_ai_drug_label_gateway import envelope
from tests.test_ai_drug_label_runtime import case as runtime_case
from tests.test_ai_drug_label_runtime import mutate, queued, stored
from tests.test_ai_drug_label_sources import label_case as _label_case

label_case = _label_case


@pytest.fixture
def case(label_case, monkeypatch):
    value = runtime_case.__wrapped__(label_case, monkeypatch)
    runtime.cancel_drug_label_run(value.db, value.actor, value.run.run_id)
    return value


def overdue(monkeypatch, seconds=None):
    now = sources.utcnow()
    monkeypatch.setattr(sources, "utcnow", lambda: now + datetime.timedelta(seconds=seconds if seconds is not None else settings.AI_MAX_QUEUE_AGE_SECONDS + 601))


@pytest.mark.parametrize("phase", ["queued", "running", "cancelled"])
@pytest.mark.parametrize("authority", [None, "source", "role"])
def test_real_recovery_preserves_uncalled_vs_unknown_even_after_current_source_or_owner_loss(case, monkeypatch, phase, authority):
    queued(case)
    if phase != "queued":
        assert runtime.claim_drug_label_run(case.db, case.id)
    if phase == "cancelled":
        runtime.cancel_drug_label_run(case.db, case.actor, case.id)
    if authority:
        mutate(case, authority)
    overdue(monkeypatch)
    monkeypatch.setattr(runtime, "generate_drug_label", lambda *args, **kwargs: pytest.fail("Recovery cannot invoke a model"))
    assert runtime.expire_interrupted_drug_label_runs(case.db) == 1
    after = stored(case)
    receipt = storage.usage_receipt(case.db, after)
    assert after.run.status == ("cancelled" if phase == "cancelled" else "failed")
    assert after.run.result_json == "{}" and after.artifact.accept_event_id is after.artifact.result_json is None
    assert (receipt.input_tokens, receipt.output_tokens, receipt.model_call_attempted) == ((0, 0, False) if phase == "queued" else (None, None, None))
    assert after.run.latency_ms is None
    assert runtime.expire_interrupted_drug_label_runs(case.db) == 0


@pytest.mark.parametrize("phase", ["queued", "running"])
def test_actual_expiration_threshold_is_strict_and_preserves_utc6_vs_run_seconds(case, monkeypatch, phase):
    queued(case)
    if phase == "running":
        assert runtime.claim_drug_label_run(case.db, case.id)
    before = stored(case)
    boundary = before.artifact.created_at + datetime.timedelta(seconds=settings.AI_MAX_QUEUE_AGE_SECONDS) if phase == "queued" else before.run.start_time + datetime.timedelta(minutes=10)
    monkeypatch.setattr(sources, "utcnow", lambda: boundary)
    assert runtime.expire_interrupted_drug_label_runs(case.db) == 0
    monkeypatch.setattr(sources, "utcnow", lambda: boundary + datetime.timedelta(microseconds=1))
    assert runtime.expire_interrupted_drug_label_runs(case.db) == 1


@pytest.mark.parametrize("phase", ["queued", "running", "cancelled"])
def test_deleted_specific_recovery_receipt_rolls_back_status_usage_and_audit_atomically(case, monkeypatch, phase):
    queued(case)
    if phase != "queued":
        runtime.claim_drug_label_run(case.db, case.id)
    if phase == "cancelled":
        runtime.cancel_drug_label_run(case.db, case.actor, case.id)
    overdue(monkeypatch)
    case.db.execute(
        text(
            f"CREATE TRIGGER label_recovery_audit_fault AFTER INSERT ON hoimsystem_ai_audit_event WHEN NEW.action='{USAGE_ACTION}' AND NEW.target='{case.id}' BEGIN DELETE FROM hoimsystem_ai_audit_event WHERE event_id=NEW.event_id; END"
        )
    )
    case.db.commit()
    try:
        with pytest.raises(HTTPException) as failure:
            runtime.expire_interrupted_drug_label_runs(case.db)
        assert failure.value.status_code == 409
        after = stored(case)
        assert after.run.status == phase and after.artifact.receipt_event_id is None and after.run.result_json == "{}"
    finally:
        case.db.rollback()
        case.db.execute(text("DROP TRIGGER label_recovery_audit_fault"))
        case.db.commit()
        assert runtime.expire_interrupted_drug_label_runs(case.db) == 1


@pytest.mark.asyncio
async def test_expired_actual_lease_never_replays_http_or_overwrites_recorded_unknown(case, monkeypatch):
    queued(case)
    lease = runtime.claim_drug_label_run(case.db, case.id)
    overdue(monkeypatch)
    assert runtime.expire_interrupted_drug_label_runs(case.db) == 1
    calls = []
    await runtime.execute_drug_label_claimed(case.id, lease, transport=httpx.MockTransport(lambda request: calls.append(request) or httpx.Response(200, json=envelope("chat"))))
    assert not calls
    receipt = storage.usage_receipt(case.db, stored(case))
    assert receipt.input_tokens is receipt.output_tokens is receipt.model_call_attempted is None
