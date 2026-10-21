"""Actual staged Super stop and unclaimed worker failure; never body access."""

import datetime as dt

import pytest
from fastapi import HTTPException
from sqlalchemy import text, update

from app.ai import operations_support_attempts as attempts
from app.ai import operations_support_cancellation as cancellation
from app.ai import operations_support_receipts as receipts
from app.ai import operations_support_registry as registry
from app.ai import operations_support_storage as storage
from app.ai.models import AIAuditEvent, AIRun
from app.ai.operations_support_run_models import AIOperationsRunArtifact
from app.ai.operations_support_usage_contract import usage
from app.models import User
from tests.test_ai_operations_support_attempts import actors as actors
from tests.test_ai_operations_support_attempts import configured as configured
from tests.test_ai_operations_support_attempts import queued as queued
from tests.test_ai_operations_support_attempts import source as source
from tests.test_ai_operations_support_receipts import capture_without_body
from tests.test_ai_operations_support_storage import no_body


def reach(configured, identifier, phase):
    db, *_, admin = configured[0]
    claim = attempts.stage_claim(db, admin, identifier) if phase != "queued" else None
    dispatch = attempts.stage_dispatch(db, admin, claim) if phase == "dispatched" else None
    return claim, dispatch


@pytest.mark.parametrize("phase", ["queued", "claimed", "dispatched"])
@pytest.mark.parametrize("withdrawn", [False, True])
def test_actual_super_stop_all_three_phases_does_not_authorize_any_body(queued, phase, withdrawn):
    configured, identifier = queued
    actors, original, release, case, provider, config = configured
    db, registrar, creator, reviewer, admin = actors
    claim, dispatch = reach(configured, identifier, phase)
    if withdrawn:
        registry.revoke_original(db, registrar, original["original_id"], {"revision": 1, "reason": "撤回仍可仅停止"})
        db.execute(update(User).where(User.user_id == admin.user_id).values(user_role="doctor"), execution_options={"synchronize_session": False})
    before = db.query(AIAuditEvent).count()
    ack = capture_without_body(db, lambda: cancellation.stage_cancel(db, registrar, identifier))
    assert ack.status == "cancelled" and ack.receipt_pending is (phase == "dispatched") and ack.automatic_legacy_write is False
    actual = capture_without_body(db, lambda: attempts.technical_header(db, identifier))
    assert actual.header["status"] == "cancelled" and actual.claim == claim and actual.dispatch == dispatch
    assert actual.artifact["usage_event_id"] == ack.usage_event_id
    assert db.query(AIAuditEvent).count() == before + (1 if dispatch else 2)
    if dispatch is None:
        receipt = capture_without_body(db, lambda: receipts.read_receipt(db, actual))
        assert receipt.status == "cancelled" and receipt.usage.model_dump() == usage(0, 0, False)
        assert receipt.claim_event_id == (claim.claim_event_id if claim else None)
        assert receipt.lease_token == (claim.lease_token if claim else None)
        assert len({actual.artifact["created_audit_event_id"], ack.cancel_event_id, ack.usage_event_id}) == 3
        if claim is None:
            assert actual.header["lease_token"] is None and actual.header["start_time"] is None and actual.artifact["claim_event_id"] is None
    else:
        assert ack.usage_event_id is None and capture_without_body(db, lambda: receipts.read_receipt(db, actual)) is None
        paid = capture_without_body(
            db,
            lambda: receipts.stage_terminal(db, claim, dispatch_event_id=dispatch.dispatch_event_id, usage=usage(11, None, True), status="failed", error_code="SOURCE_NOT_CURRENT", latency_ms=87),
        )
        assert paid.status == "cancelled" and paid.error_code == "TASK_CANCELLED" and paid.usage.model_dump() == usage(11, None, True)
    if withdrawn:
        no_body(db, lambda: storage.load_artifact(db, registrar, identifier), 403)
    count = db.query(AIAuditEvent).count()
    no_body(db, lambda: cancellation.stage_cancel(db, registrar, identifier), 409)
    assert db.query(AIAuditEvent).count() == count


def test_current_admin_cannot_use_super_technical_stop_even_for_own_task(queued):
    configured, identifier = queued
    db, *_, admin = configured[0]
    count = db.query(AIAuditEvent).count()
    no_body(db, lambda: cancellation.stage_cancel(db, admin, identifier), 403)
    assert db.query(AIAuditEvent).count() == count and attempts.technical_header(db, identifier).header["status"] == "queued"


def test_changed_request_login_epoch_is_denied_before_any_body(queued):
    configured, identifier = queued
    db, registrar, *_ = configured[0]
    db.execute(update(User).where(User.user_id == registrar.user_id).values(token_invalid_before=registry.utcnow()), execution_options={"synchronize_session": False})
    no_body(db, lambda: cancellation.stage_cancel(db, registrar, identifier), 403)
    assert attempts.technical_header(db, identifier).header["status"] == "queued"


def test_actual_unclaimed_lost_source_worker_failure_keeps_no_fake_claim(queued):
    configured, identifier = queued
    db, registrar, *_, admin = configured[0]
    registry.revoke_original(db, registrar, configured[1]["original_id"], {"revision": 1, "reason": "领取前来源撤回"})
    value = capture_without_body(db, lambda: receipts.stage_unclaimed_failure(db, identifier, error_code="SOURCE_NOT_CURRENT"))
    actual = capture_without_body(db, lambda: attempts.technical_header(db, identifier))
    assert value.status == "failed" and value.claim_event_id is None and value.lease_token is None and value.usage.model_dump() == usage(0, 0, False)
    assert actual.claim is None and actual.dispatch is None and actual.header["start_time"] is None
    assert capture_without_body(db, lambda: receipts.read_receipt(db, actual)) == value
    assert receipts.stage_unclaimed_failure(db, identifier, error_code="SOURCE_NOT_CURRENT") is None
    no_body(db, lambda: storage.load_artifact(db, admin, identifier), 403)


@pytest.mark.parametrize("phase", ["claimed", "dispatched"])
def test_trusted_unclaimed_failure_is_inert_after_some_delivery_owns_claim(queued, phase):
    configured, identifier = queued
    db = configured[0][0]
    claim, dispatch = reach(configured, identifier, phase)
    count = db.query(AIAuditEvent).count()
    assert capture_without_body(db, lambda: receipts.stage_unclaimed_failure(db, identifier, error_code="SOURCE_NOT_CURRENT")) is None
    actual = attempts.technical_attempt(db, claim)
    assert actual.header["status"] == "running" and actual.dispatch == dispatch and actual.artifact["usage_event_id"] is None and db.query(AIAuditEvent).count() == count


@pytest.mark.parametrize("fault", ["clock", "counter", "existing_result"])
def test_cancel_rejects_backwards_clock_and_does_not_overwrite_existing_markers(queued, monkeypatch, fault):
    configured, identifier = queued
    db, registrar, *_ = configured[0]
    header = attempts.technical_header(db, identifier)
    if fault == "clock":
        monkeypatch.setattr(registry, "utcnow", lambda: header.artifact["recorded_at"] - dt.timedelta(microseconds=1))
    elif fault == "counter":
        db.execute(update(AIRun).where(AIRun.run_id == identifier).values(input_tokens=9), execution_options={"synchronize_session": False})
    else:
        db.execute(update(AIRun).where(AIRun.run_id == identifier).values(result_json='{"unexpected":true}'), execution_options={"synchronize_session": False})
    count = db.query(AIAuditEvent).count()
    no_body(db, lambda: cancellation.stage_cancel(db, registrar, identifier), 409)
    assert db.query(AIAuditEvent).count() == count


@pytest.mark.parametrize("fault", ["actor_role", "actor_epoch", "cancel_audit", "run_header", "usage_pk", "late_usage_actor_epoch"])
def test_actual_sql_trigger_after_cancel_or_usage_audit_rolls_back_entire_stop(queued, fault):
    configured, identifier = queued
    db, registrar, *_ = configured[0]
    original_epoch = registrar.token_invalid_before
    actor_id = registrar.user_id
    db.commit()
    if fault == "actor_role":
        mutation = "UPDATE hoimsystem_users SET user_role='doctor' WHERE user_id=" + str(actor_id) + ";"
    elif fault in {"actor_epoch", "late_usage_actor_epoch"}:
        mutation = "UPDATE hoimsystem_users SET token_invalid_before='2026-10-23 01:02:03.456789' WHERE user_id=" + str(actor_id) + ";"
    elif fault == "cancel_audit":
        mutation = "UPDATE hoimsystem_ai_audit_event SET detail_json='{}' WHERE event_id=NEW.event_id;"
    elif fault == "run_header":
        mutation = "UPDATE hoimsystem_ai_run SET prompt_hash='" + "0" * 64 + "' WHERE run_id='" + identifier + "';"
    else:
        mutation = "UPDATE hoimsystem_ai_operations_run_artifact SET usage_event_id=NEW.event_id WHERE run_id='" + identifier + "';"
    action = receipts.USAGE_ACTION if fault == "late_usage_actor_epoch" else cancellation.CANCEL_ACTION
    db.execute(text("CREATE TRIGGER ops_after_cancel AFTER INSERT ON hoimsystem_ai_audit_event WHEN NEW.action='" + action + "' BEGIN " + mutation + " END"))
    count = db.query(AIAuditEvent).count()
    try:
        with pytest.raises(HTTPException) as exc, db.begin_nested():
            cancellation.stage_cancel(db, registrar, identifier)
        assert exc.value.status_code == (403 if fault in {"actor_role", "actor_epoch", "late_usage_actor_epoch"} else 409)
        actual = attempts.technical_header(db, identifier)
        assert actual.header["status"] == "queued" and actual.claim is None and actual.artifact["usage_event_id"] is None and db.query(AIAuditEvent).count() == count
        current = db.query(User).populate_existing().filter_by(user_id=actor_id).one()
        assert current.user_role == "super_admin" and current.token_invalid_before == original_epoch
        assert db.get(AIOperationsRunArtifact, identifier).claim_event_id is None
    finally:
        db.rollback()
        db.execute(text("DROP TRIGGER IF EXISTS ops_after_cancel"))
        db.commit()
