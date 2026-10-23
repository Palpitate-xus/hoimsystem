"""Actual one-claim/one-dispatch SQL stages, no HTTP or terminal settlement."""

import datetime as dt
import uuid

import pytest
from app.ai import operations_support_attempts as attempts
from app.ai import operations_support_registry as registry
from app.ai import operations_support_storage as storage
from app.ai.models import AIAuditEvent, AIRun
from app.ai.operations_support_models import AIOperationsOriginal
from app.ai.operations_support_run_models import AIOperationsRunArtifact
from fastapi import HTTPException
from sqlalchemy import text
from tests.test_ai_operations_support_configuration import actors as actors
from tests.test_ai_operations_support_configuration import configured as configured
from tests.test_ai_operations_support_configuration import source as source
from tests.test_ai_operations_support_registry import request
from tests.test_ai_operations_support_storage import no_body, stage


@pytest.fixture
def queued(configured):
    return configured, stage(configured)


def test_one_exact_claim_and_dispatch_have_three_distinct_specific_audit_pks_and_no_commit(queued):
    configured, identifier = queued
    db = configured[0][0]
    admin = configured[0][-1]
    before = db.query(AIAuditEvent).count()
    claim = attempts.stage_claim(db, admin, identifier)
    assert claim.run_id == identifier and claim.created_audit_event_id != claim.claim_event_id
    actual = attempts.technical_attempt(db, claim)
    assert actual.claim == claim and actual.dispatch is None and actual.header["status"] == "running"
    assert actual.header["start_time"] == attempts.clock(claim.claimed_at).replace(microsecond=0)
    dispatch = attempts.stage_dispatch(db, admin, claim)
    assert dispatch.claim_event_id == claim.claim_event_id and len({claim.created_audit_event_id, claim.claim_event_id, dispatch.dispatch_event_id}) == 3
    actual = attempts.technical_attempt(db, claim)
    assert actual.dispatch == dispatch and actual.artifact["usage_event_id"] is None
    assert db.query(AIAuditEvent).count() == before + 2
    assert db.get(AIAuditEvent, claim.claim_event_id).action == attempts.CLAIM_ACTION
    assert db.get(AIAuditEvent, dispatch.dispatch_event_id).action == attempts.DISPATCH_ACTION
    db.rollback()
    assert db.get(AIRun, identifier) is None and db.get(AIOperationsRunArtifact, identifier) is None


@pytest.mark.parametrize("phase", ["claim", "dispatch"])
def test_duplicate_delivery_after_source_withdrawal_is_inert_without_body(queued, phase):
    configured, identifier = queued
    actors, original, release, case, provider, config = configured
    db, registrar, creator, reviewer, admin = actors
    claim = attempts.stage_claim(db, admin, identifier)
    dispatch = attempts.stage_dispatch(db, admin, claim) if phase == "dispatch" else None
    registry.revoke_original(db, registrar, original["original_id"], {"revision": 1, "reason": "发送者仍在途而来源已撤回"})
    before = db.query(AIAuditEvent).count()
    # The duplicate skips before the Source guard. It never settles the owner.
    returned = []
    from sqlalchemy import event

    def capture(conn, cursor, statement, params, context, many):
        if statement.lstrip().lower().startswith("select"):
            returned.extend(column[0] for column in cursor.description or [])

    event.listen(db.bind, "after_cursor_execute", capture)
    try:
        assert (attempts.stage_claim(db, admin, identifier) if phase == "claim" else attempts.stage_dispatch(db, admin, claim)) is None
    finally:
        event.remove(db.bind, "after_cursor_execute", capture)
    assert not any(any(part in name for part in ["input_json", "source_json", "content_text", "private_json", "public_json"]) for name in returned)
    assert db.query(AIAuditEvent).count() == before
    actual = attempts.technical_attempt(db, claim)
    assert actual.header["status"] == "running" and actual.dispatch == dispatch and actual.artifact["usage_event_id"] is None
    no_body(db, lambda: storage.load_artifact(db, admin, identifier), 403)


@pytest.mark.parametrize("field", ["run_id", "case_id", "requested_by", "claim_event_id", "lease_token", "source_binding_hash"])
def test_wrong_actual_claim_cannot_read_source_or_task_body_or_mutate_owner(queued, field):
    configured, identifier = queued
    db = configured[0][0]
    admin = configured[0][-1]
    claim = attempts.stage_claim(db, admin, identifier)
    changed = claim.model_dump()
    changed[field] = (
        claim.claim_event_id + 1000 if field == "claim_event_id" else claim.requested_by + 1000 if field == "requested_by" else "0" * 64 if field == "source_binding_hash" else str(uuid.uuid4())
    )
    before = db.query(AIAuditEvent).count()
    no_body(db, lambda: attempts.technical_attempt(db, changed), 409)
    if field != "run_id":
        no_body(db, lambda: attempts.stage_dispatch(db, admin, changed), 409)
    assert db.query(AIAuditEvent).count() == before and attempts.technical_attempt(db, claim).dispatch is None


@pytest.mark.parametrize("phase", ["claim", "dispatch"])
def test_utc6_claim_dispatch_audit_and_legacy_start_seconds_are_exact(queued, monkeypatch, phase):
    configured, identifier = queued
    db = configured[0][0]
    admin = configured[0][-1]
    when = (db.get(AIOperationsRunArtifact, identifier).recorded_at + dt.timedelta(seconds=1)).replace(microsecond=654321)
    monkeypatch.setattr(registry, "utcnow", lambda: when)
    claim = attempts.stage_claim(db, admin, identifier)
    if phase == "dispatch":
        when = when + dt.timedelta(microseconds=77)
        value = attempts.stage_dispatch(db, admin, claim)
        identifier = value.dispatch_event_id
        assert value.dispatched_at == registry.utc_text(when)
    else:
        value = claim
        identifier = claim.claim_event_id
        assert claim.claimed_at == registry.utc_text(when)
    assert db.get(AIAuditEvent, identifier).create_time == when.replace(microsecond=0)
    assert attempts.technical_attempt(db, claim).claim == claim


@pytest.mark.parametrize("phase", ["claim", "dispatch"])
def test_backwards_phase_clock_rejects_before_new_phase_audit(queued, monkeypatch, phase):
    configured, identifier = queued
    db = configured[0][0]
    admin = configured[0][-1]
    if phase == "claim":
        when = db.get(AIOperationsRunArtifact, identifier).recorded_at - dt.timedelta(microseconds=1)

        def operation():
            return attempts.stage_claim(db, admin, identifier)
    else:
        claim = attempts.stage_claim(db, admin, identifier)
        when = attempts.clock(claim.claimed_at) - dt.timedelta(microseconds=1)

        def operation():
            return attempts.stage_dispatch(db, admin, claim)

    monkeypatch.setattr(registry, "utcnow", lambda: when)
    before = db.query(AIAuditEvent).count()
    with pytest.raises(HTTPException) as exc:
        operation()
    assert exc.value.status_code == 409 and db.query(AIAuditEvent).count() == before


@pytest.mark.parametrize("phase", ["claim", "dispatch"])
@pytest.mark.parametrize("damage", ["source", "phase_audit", "run_lease"])
def test_actual_after_phase_audit_trigger_rolls_back_entire_owned_phase_and_source(queued, phase, damage):
    configured, identifier = queued
    actors, original, release, case, provider, config = configured
    db, registrar, creator, reviewer, admin = actors
    claim = attempts.stage_claim(db, admin, identifier) if phase == "dispatch" else None
    # Commit only the synthetic queued/claimed fixture, so explicit trigger
    # cleanup cannot preserve a failed phase or roll back the intended baseline.
    db.commit()
    if damage == "source":
        command = "UPDATE hoimsystem_ai_operations_original SET content_text='changed' WHERE original_id='" + original["original_id"] + "';"
    elif damage == "phase_audit":
        command = "UPDATE hoimsystem_ai_audit_event SET detail_json='{}' WHERE event_id=NEW.event_id;"
    else:
        command = "UPDATE hoimsystem_ai_run SET lease_token='" + str(uuid.uuid4()) + "' WHERE run_id='" + identifier + "';"
    action = attempts.CLAIM_ACTION if phase == "claim" else attempts.DISPATCH_ACTION
    db.execute(text("CREATE TRIGGER ops_after_phase AFTER INSERT ON hoimsystem_ai_audit_event WHEN NEW.action='" + action + "' BEGIN " + command + " END"))
    counts = db.query(AIAuditEvent).count()
    before_run = db.query(AIRun.status, AIRun.lease_token, AIRun.start_time).filter_by(run_id=identifier).one()
    before_artifact = db.query(AIOperationsRunArtifact.claim_event_id, AIOperationsRunArtifact.dispatch_event_id).filter_by(run_id=identifier).one()
    try:
        with pytest.raises(HTTPException), db.begin_nested():
            attempts.stage_claim(db, admin, identifier) if phase == "claim" else attempts.stage_dispatch(db, admin, claim)
        assert db.query(AIAuditEvent).count() == counts
        assert db.query(AIRun.status, AIRun.lease_token, AIRun.start_time).filter_by(run_id=identifier).one() == before_run
        assert db.query(AIOperationsRunArtifact.claim_event_id, AIOperationsRunArtifact.dispatch_event_id).filter_by(run_id=identifier).one() == before_artifact
        assert db.query(AIOperationsOriginal.content_text).filter_by(original_id=original["original_id"]).scalar() == request()["content_text"]
    finally:
        db.rollback()
        db.execute(text("DROP TRIGGER IF EXISTS ops_after_phase"))
        db.commit()
