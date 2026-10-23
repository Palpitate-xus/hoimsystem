"""Trusted delivery accounting after source loss; ordinary bodies stay denied."""

import datetime as dt

import pytest
from fastapi import HTTPException
from sqlalchemy import text, update

from app.ai import operations_support_attempts as attempts
from app.ai import operations_support_receipts as receipts
from app.ai import operations_support_registry as registry
from app.ai import operations_support_storage as storage
from app.ai.models import AIAuditEvent, AIRun
from app.ai.operations_support_models import AIOperationsOriginal
from app.ai.operations_support_run_models import AIOperationsRunArtifact
from app.ai.operations_support_usage_contract import usage
from tests.ai_admin_usage_assertions import assert_exact_usage_event
from tests.test_ai_operations_support_attempts import actors as actors
from tests.test_ai_operations_support_attempts import configured as configured
from tests.test_ai_operations_support_attempts import queued as queued
from tests.test_ai_operations_support_attempts import source as source
from tests.test_ai_operations_support_registry import request
from tests.test_ai_operations_support_storage import no_body


def settle(db, claim, dispatch_id, reported=usage(11, None, True), **extra):
    return receipts.stage_terminal(db, claim, dispatch_event_id=dispatch_id, usage=reported, status="failed", error_code="SOURCE_NOT_CURRENT", latency_ms=71, **extra)


@pytest.fixture
def claimed(queued):
    configured, identifier = queued
    return configured, attempts.stage_claim(configured[0][0], configured[0][-1], identifier)


def capture_without_body(db, operation):
    from sqlalchemy import event

    returned = []

    def capture(conn, cursor, statement, params, context, many):
        if statement.lstrip().lower().startswith("select"):
            returned.extend(column[0] for column in cursor.description or [])

    event.listen(db.bind, "after_cursor_execute", capture)
    try:
        value = operation()
    finally:
        event.remove(db.bind, "after_cursor_execute", capture)
    protected = [
        "input_json",
        "evidence_json",
        "context_metadata_json",
        "result_json",
        "source_json",
        "prompt_snapshot_json",
        "execution_snapshot_json",
        "private_json",
        "public_json",
        "identity_json",
        "content_text",
        "draft_json",
        "review_basis",
        "published_review_json",
    ]
    assert not any(name == part or name.endswith("_" + part) for name in returned for part in protected), returned
    return value


@pytest.mark.parametrize("reported", [usage(11, 13, True), usage(11, None, True), usage(None, 13, True), usage(None, None, True), usage(0, 0, True)])
def test_actual_paid_or_unknown_components_survive_source_withdrawal_without_any_body(claimed, reported):
    configured, claim = claimed
    actors, original, release, case, provider, config = configured
    db, registrar, creator, reviewer, admin = actors
    dispatch = attempts.stage_dispatch(db, admin, claim)
    registry.revoke_original(db, registrar, original["original_id"], {"revision": 1, "reason": "在途来源撤回"})
    before = db.query(AIAuditEvent).count()
    value = capture_without_body(db, lambda: settle(db, claim, dispatch.dispatch_event_id, reported))
    assert value.usage.model_dump() == reported and value.status == "failed"
    assert_exact_usage_event(db, claim.run_id, "operations_support", reported)
    attempt = attempts.technical_attempt(db, claim)
    assert capture_without_body(db, lambda: receipts.read_receipt(db, attempt)) == value
    assert attempt.header["input_tokens"] == (reported["input_tokens"] if reported["input_tokens"] is not None else 0)
    assert attempt.header["output_tokens"] == (reported["output_tokens"] if reported["output_tokens"] is not None else 0)
    assert db.query(AIAuditEvent).count() == before + 1 and attempt.artifact["usage_event_id"] not in {claim.created_audit_event_id, claim.claim_event_id, dispatch.dispatch_event_id}
    no_body(db, lambda: storage.load_artifact(db, admin, claim.run_id), 403)
    no_body(db, lambda: storage.load_artifact(db, registrar, claim.run_id), 403)
    # A duplicate owner delivery never adds another receipt or changes counts.
    assert settle(db, claim, dispatch.dispatch_event_id, reported) is None
    assert db.query(AIAuditEvent).count() == before + 1


def test_undispatched_proven_zero_is_distinct_from_reported_zero_and_interrupted_unknown(claimed):
    configured, claim = claimed
    db = configured[0][0]
    value = settle(db, claim, None, usage(0, 0, False))
    assert value.usage.model_call_attempted is False and value.usage.complete is True
    assert attempts.technical_attempt(db, claim).dispatch is None


@pytest.mark.parametrize("reported", [usage(None, None, True), usage(None, None, None), usage(0, 0, True)])
def test_no_dispatch_cannot_claim_paid_or_interrupted_attempt(claimed, reported):
    configured, claim = claimed
    db = configured[0][0]
    before = db.query(AIAuditEvent).count()
    with pytest.raises(HTTPException) as exc:
        settle(db, claim, None, reported)
    assert exc.value.status_code == 409 and db.query(AIAuditEvent).count() == before


def test_second_delivery_without_its_own_dispatch_cannot_terminate_first_inflight_owner(claimed):
    configured, claim = claimed
    actors, original, release, case, provider, config = configured
    db, registrar, creator, reviewer, admin = actors
    dispatch = attempts.stage_dispatch(db, admin, claim)
    registry.revoke_original(db, registrar, original["original_id"], {"revision": 1, "reason": "邻近交付等待期间撤回"})
    before = db.query(AIAuditEvent).count()
    for other in [None, dispatch.dispatch_event_id + 1000]:
        assert capture_without_body(db, lambda: settle(db, claim, other, usage(0, 0, False))) is None
    current = attempts.technical_attempt(db, claim)
    assert current.header["status"] == "running" and current.artifact["usage_event_id"] is None and db.query(AIAuditEvent).count() == before
    assert settle(db, claim, dispatch.dispatch_event_id, usage(11, 13, True)).usage.model_dump() == usage(11, 13, True)


def test_cancelled_inflight_awaits_actual_original_delivery_and_retains_partial_paid_use(claimed):
    configured, claim = claimed
    db = configured[0][0]
    admin = configured[0][-1]
    dispatch = attempts.stage_dispatch(db, admin, claim)
    # Cancellation service is a later integration; this fixture mutates only
    # the actual cancellation state, never pretends its handler was exercised.
    db.execute(update(AIRun).where(AIRun.run_id == claim.run_id).values(status="cancelled").execution_options(synchronize_session=False))
    value = settle(db, claim, dispatch.dispatch_event_id, usage(11, None, True))
    assert value.status == "cancelled" and value.error_code == "TASK_CANCELLED" and value.usage.model_dump() == usage(11, None, True)


def test_interrupted_original_dispatch_preserves_unknown_without_inventing_zero(claimed):
    configured, claim = claimed
    db = configured[0][0]
    dispatch = attempts.stage_dispatch(db, configured[0][-1], claim)
    value = receipts.stage_terminal(db, claim, dispatch_event_id=dispatch.dispatch_event_id, usage=usage(None, None, None), status="failed", error_code="WORKER_INTERRUPTED", latency_ms=123)
    assert value.usage.model_dump() == usage(None, None, None)
    assert attempts.technical_attempt(db, claim).header["input_tokens"] == 0  # compatibility placeholder only


@pytest.mark.parametrize("damage", ["action", "detail", "foreign_pk", "run_counter", "run_result"])
def test_actual_receipt_pk_and_complete_terminal_state_are_verified_without_body(claimed, damage):
    configured, claim = claimed
    db = configured[0][0]
    dispatch = attempts.stage_dispatch(db, configured[0][-1], claim)
    settle(db, claim, dispatch.dispatch_event_id)
    artifact = db.get(AIOperationsRunArtifact, claim.run_id)
    if damage == "action":
        db.execute(update(AIAuditEvent).where(AIAuditEvent.event_id == artifact.usage_event_id).values(action="different").execution_options(synchronize_session=False))
    elif damage == "detail":
        db.execute(update(AIAuditEvent).where(AIAuditEvent.event_id == artifact.usage_event_id).values(detail_json="{}").execution_options(synchronize_session=False))
    elif damage == "foreign_pk":
        other = AIAuditEvent(actor_id=claim.requested_by, action=receipts.USAGE_ACTION, target=claim.run_id, detail_json="{}")
        db.add(other)
        db.flush()
        db.execute(update(AIOperationsRunArtifact).where(AIOperationsRunArtifact.run_id == claim.run_id).values(usage_event_id=other.event_id).execution_options(synchronize_session=False))
    elif damage == "run_counter":
        db.execute(update(AIRun).where(AIRun.run_id == claim.run_id).values(input_tokens=999).execution_options(synchronize_session=False))
    else:
        db.execute(update(AIRun).where(AIRun.run_id == claim.run_id).values(result_json='{"ghost":"not accepted"}').execution_options(synchronize_session=False))
    attempt = attempts.technical_attempt(db, claim)
    no_body(db, lambda: receipts.read_receipt(db, attempt), 409)


def test_backwards_terminal_clock_leaves_original_owner_unchanged(claimed, monkeypatch):
    configured, claim = claimed
    db = configured[0][0]
    dispatch = attempts.stage_dispatch(db, configured[0][-1], claim)
    monkeypatch.setattr(registry, "utcnow", lambda: attempts.clock(dispatch.dispatched_at) - dt.timedelta(microseconds=1))
    before = db.query(AIAuditEvent).count()
    with pytest.raises(HTTPException) as exc:
        settle(db, claim, dispatch.dispatch_event_id)
    assert exc.value.status_code == 409 and db.query(AIAuditEvent).count() == before and attempts.technical_attempt(db, claim).artifact["usage_event_id"] is None


@pytest.mark.parametrize("damage", ["source", "receipt", "run_counter", "phase_pk"])
def test_actual_usage_audit_insert_trigger_rolls_back_entire_terminal_state(claimed, damage):
    configured, claim = claimed
    actors, original, release, case, provider, config = configured
    db, registrar, creator, reviewer, admin = actors
    dispatch = attempts.stage_dispatch(db, admin, claim)
    db.commit()
    if damage == "source":
        command = "UPDATE hoimsystem_ai_operations_original SET content_text='changed' WHERE original_id='" + original["original_id"] + "';"
    elif damage == "receipt":
        command = "UPDATE hoimsystem_ai_audit_event SET detail_json='{}' WHERE event_id=NEW.event_id;"
    elif damage == "run_counter":
        command = "UPDATE hoimsystem_ai_run SET prompt_hash='" + "0" * 64 + "' WHERE run_id='" + claim.run_id + "';"
    else:
        command = "UPDATE hoimsystem_ai_operations_run_artifact SET dispatch_event_id=NULL WHERE run_id='" + claim.run_id + "';"
    db.execute(text("CREATE TRIGGER ops_after_usage AFTER INSERT ON hoimsystem_ai_audit_event WHEN NEW.action='" + receipts.USAGE_ACTION + "' BEGIN " + command + " END"))
    before = db.query(AIAuditEvent).count()
    try:
        if damage == "source":
            # Accounting deliberately survives Source changes and never reads
            # its body; the source mutation itself is caller-rollback tested.
            with db.begin_nested() as nested:
                assert settle(db, claim, dispatch.dispatch_event_id).usage.input_tokens == 11
                nested.rollback()
        else:
            with pytest.raises(HTTPException), db.begin_nested():
                settle(db, claim, dispatch.dispatch_event_id)
        assert db.query(AIAuditEvent).count() == before
        actual = attempts.technical_attempt(db, claim)
        assert actual.header["status"] == "running" and actual.artifact["usage_event_id"] is None and actual.dispatch == dispatch
        assert db.query(AIOperationsOriginal.content_text).filter_by(original_id=original["original_id"]).scalar() == request()["content_text"]
    finally:
        db.rollback()
        db.execute(text("DROP TRIGGER IF EXISTS ops_after_usage"))
        db.commit()
