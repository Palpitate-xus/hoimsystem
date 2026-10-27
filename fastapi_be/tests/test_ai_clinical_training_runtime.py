"""Committed native runtime, closed SQL across await and honest cancellation."""

import asyncio
import datetime as dt
import json
from contextlib import contextmanager

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy.orm import sessionmaker

from app.ai import clinical_training_attempts as a
from app.ai import clinical_training_execution as execution
from app.ai import clinical_training_receipts as r
from app.ai import clinical_training_reviews as reviews
from app.ai import clinical_training_runtime as runtime
from app.ai import clinical_training_storage as s
from app.ai.clinical_training_run_models import AITrainingRunResult
from tests.test_ai_clinical_training_configuration import configured as configured
from tests.test_ai_clinical_training_gateway import envelope
from tests.test_ai_clinical_training_practice import practice_case as practice_case
from tests.test_ai_clinical_training_reference_sql import reference_case as reference_case
from tests.test_ai_clinical_training_reviews import reviewed_case as reviewed_case
from tests.test_ai_clinical_training_storage import stored as stored
from tests.test_ai_clinical_training_task_contract import draft


def sessions(db):
    maker, active, completed = sessionmaker(bind=db.get_bind(), autoflush=False, expire_on_commit=True), [], []

    @contextmanager
    def factory():
        session = maker()
        active.append(session)
        try:
            yield session
        finally:
            session.close()
            active.remove(session)
            completed.append(session)

    return factory, active, completed


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["chat", "responses"])
@pytest.mark.parametrize("mode", ["known", "input", "output", "unknown"])
async def test_one_committed_native_dispatch_both_protocols_nullable_receipt_and_zero_live_sql_during_await(stored, kind, mode):
    case, key = stored
    db = case["db"]
    # This is a current configuration change before the task's own immutable
    # creation, so create a fresh task with that exact protocol snapshot.
    if kind == "responses":
        case["provider"].kind = kind
        case["provider"].revision += 1
        db.commit()
        from tests.test_ai_clinical_training_configuration import selected

        key = runtime.create_training_run(db, case["actor"], selected(case))
    source = s.load_artifact(db, case["actor"], key)[2]
    db.commit()
    lease = runtime.claim_training_run(db, key)
    assert lease and runtime.claim_training_run(db, key) is None
    db.commit()
    factory, active, completed = sessions(db)
    calls = []
    ikey, okey = ("prompt_tokens", "completion_tokens") if kind == "chat" else ("input_tokens", "output_tokens")
    counters = {"known": {ikey: 11, okey: 7}, "input": {ikey: 11}, "output": {okey: 7}, "unknown": {}}[mode]

    async def handler(incoming):
        calls.append(incoming)
        assert not active and not db.in_transaction()
        await asyncio.sleep(0)
        assert not active and not db.in_transaction()
        packet = json.loads(incoming.content)
        visible = json.loads(packet["messages"][1]["content"] if kind == "chat" else packet["input"])
        assert visible["source"] == source.model_dump(mode="json")
        return httpx.Response(200, json=envelope(kind, draft(source.model_dump(mode="json")), counters))

    await execution.execute_training_claimed(key, lease, session_factory=factory, transport=httpx.MockTransport(handler))
    actual = a.technical_header(db, key)
    receipt = r.read_receipt(db, actual)
    assert actual.header["status"] == "succeeded" and receipt.usage.model_call_attempted is True
    assert (receipt.usage.input_tokens, receipt.usage.output_tokens) == (counters.get(ikey), counters.get(okey))
    assert len(calls) == 1 and not active and len(completed) >= 3
    db.commit()
    await execution.execute_training_claimed(key, lease, session_factory=factory, transport=httpx.MockTransport(handler))
    assert len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["unclaimed", "claimed", "inflight"])
async def test_current_super_can_stop_without_other_learner_answer_access_and_paid_use_is_not_fake_zero(stored, mode):
    case, key = stored
    db = case["db"]
    source = s.load_artifact(db, case["actor"], key)[2]
    db.commit()
    lease = runtime.claim_training_run(db, key) if mode != "unclaimed" else None
    factory, active, completed = sessions(db)
    calls, arrived, release = [], asyncio.Event(), asyncio.Event()

    async def handler(incoming):
        calls.append(incoming)
        assert not active and not db.in_transaction()
        arrived.set()
        await release.wait()
        assert not active
        return httpx.Response(200, json=envelope("chat", draft(source.model_dump(mode="json")), {"prompt_tokens": 11}))

    if mode == "inflight":
        task = asyncio.create_task(execution.execute_training_claimed(key, lease, session_factory=factory, transport=httpx.MockTransport(handler)))
        await asyncio.wait_for(arrived.wait(), 5)
        assert not active
    else:
        task = None
    try:
        ack = runtime.cancel_training_run(db, case["author"], key)
        assert ack.receipt_pending is (mode == "inflight")
        if mode == "inflight":
            assert r.read_receipt(db, a.technical_header(db, key)) is None
            db.commit()
            await execution.execute_training_claimed(key, lease, session_factory=factory, transport=httpx.MockTransport(handler))
            assert len(calls) == 1
        with pytest.raises(HTTPException) as error:
            s.load_artifact(db, case["author"], key)
        assert error.value.status_code == 403
        db.rollback()
    finally:
        release.set()
        if task is not None:
            await task
    if mode == "claimed":
        db.commit()
        await execution.execute_training_claimed(key, lease, session_factory=factory, transport=httpx.MockTransport(handler))
    actual = a.technical_header(db, key)
    receipt = r.read_receipt(db, actual)
    assert actual.header["status"] == "cancelled" and db.query(AITrainingRunResult).filter_by(run_id=key).count() == 0
    assert receipt.usage.input_tokens == (11 if mode == "inflight" else 0)
    assert receipt.usage.output_tokens == (None if mode == "inflight" else 0)
    assert receipt.usage.model_call_attempted is (mode == "inflight")
    assert len(calls) == (1 if mode == "inflight" else 0)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["unavailable_before_claim", "withdraw_during_call", "http503"])
async def test_current_source_loss_and_transport_failure_never_accept_results_or_replay(stored, mode):
    case, key = stored
    db = case["db"]
    source = s.load_artifact(db, case["actor"], key)[2]
    db.commit()
    if mode == "unavailable_before_claim":
        reviews.revoke_review(db, case["author"], case["review"]["review_id"], dict(revision=1, reason="排队期间明确来源模型许可撤回"))
        db.commit()
        assert runtime.claim_training_run(db, key) is None
        receipt = r.read_receipt(db, a.technical_header(db, key))
        assert receipt.usage.model_call_attempted is False and receipt.usage.input_tokens == receipt.usage.output_tokens == 0
        return
    lease = runtime.claim_training_run(db, key)
    factory, active, completed = sessions(db)
    calls = []

    async def handler(incoming):
        calls.append(incoming)
        assert not active and not db.in_transaction()
        if mode == "withdraw_during_call":
            reviews.revoke_review(db, case["author"], case["review"]["review_id"], dict(revision=1, reason="实际调用期间明确来源撤回"))
            db.commit()
            return httpx.Response(200, json=envelope("chat", draft(source.model_dump(mode="json")), {"prompt_tokens": 11}))
        return httpx.Response(503, content=b"private-provider-error-sentinel")

    await execution.execute_training_claimed(key, lease, session_factory=factory, transport=httpx.MockTransport(handler))
    actual = a.technical_header(db, key)
    receipt = r.read_receipt(db, actual)
    assert actual.header["status"] == "failed" and receipt.usage.model_call_attempted is True
    assert (receipt.usage.input_tokens, receipt.usage.output_tokens) == ((11, None) if mode == "withdraw_during_call" else (None, None))
    assert len(calls) == (3 if mode == "http503" else 1) and db.query(AITrainingRunResult).filter_by(run_id=key).count() == 0


@pytest.mark.parametrize("dispatched", [False, True])
def test_interrupted_recovery_uses_original_attempt_and_exact_unknown_not_automatic_model_retry(stored, dispatched, monkeypatch):
    case, key = stored
    db = case["db"]
    lease = runtime.claim_training_run(db, key)
    actual = a.technical_header(db, key)
    if dispatched:
        a.stage_dispatch(db, case["actor"], actual.claim)
    db.commit()
    future = s.registry.utcnow() + dt.timedelta(minutes=20)
    monkeypatch.setattr(s.registry, "utcnow", lambda: future)
    assert runtime.expire_interrupted_training_runs(db) >= 1
    actual = a.technical_header(db, key)
    receipt = r.read_receipt(db, actual)
    assert actual.header["status"] == "failed" and actual.header["lease_token"] == lease
    assert receipt.error_code == "WORKER_INTERRUPTED" and receipt.usage.model_call_attempted is (None if dispatched else False)
    assert (receipt.usage.input_tokens, receipt.usage.output_tokens) == ((None, None) if dispatched else (0, 0))
    assert runtime.expire_interrupted_training_runs(db) == 0
