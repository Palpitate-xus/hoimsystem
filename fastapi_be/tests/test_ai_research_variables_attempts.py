"""Actual SQL claim/dispatch ownership and whole-transaction failure cases."""

from dataclasses import replace

import pytest
from fastapi import HTTPException
from sqlalchemy import event, inspect, text

from app.ai import research_variables_attempts as attempts
from app.ai import research_variables_task_reader as reader
from app.ai.models import AIAuditEvent
from app.ai.research_cohort_registry import review_registry_original
from tests.test_ai_research_cohort_contract import BASIS
from tests.test_ai_research_variables_configuration import configured as configured
from tests.test_ai_research_variables_task_context import PRIVATE
from tests.test_ai_research_variables_task_context import research_case as research_case
from tests.test_ai_research_variables_task_context import task_factory as task_factory
from tests.test_ai_research_variables_task_reader import TASK_TEXT, observations, stop
from tests.test_ai_research_variables_task_reader import actual_task as actual_task


@pytest.fixture(autouse=True)
def cleanup_trigger(db_session):
    yield
    db_session.rollback()
    db_session.execute(text("DROP TRIGGER IF EXISTS variable_task_phase_fault"))
    db_session.commit()


def claimed(db, actual_task):
    case, _, _, staged = actual_task
    identifier = inspect(staged.run).identity[0]
    value = attempts.stage_claim(db, case["admin_user"], identifier)
    assert isinstance(value, attempts.VariableClaim)
    db.commit()
    return value


def test_actual_queued_claim_commit_dispatch_commit_exact_two_audit_pks_and_duplicate_after_source_loss_is_inert(db_session, actual_task):
    case, permissions, _, staged = actual_task
    original = staged.artifact.create_event_id
    claim = claimed(db_session, actual_task)
    assert claim.create_event_id == original
    loaded = reader.load_task(db_session, case["admin_user"], claim.run_id)
    assert loaded.run.status == "running" and loaded.run.lease_token == claim.lease
    assert attempts.verify_claim(db_session, loaded, claim) == claim
    before = db_session.query(AIAuditEvent).count()
    assert attempts.stage_claim(db_session, case["admin_user"], claim.run_id) is None
    assert db_session.query(AIAuditEvent).count() == before
    delivery = attempts.stage_dispatch(db_session, case["admin_user"], claim)
    db_session.commit()
    assert isinstance(delivery, attempts.VariableDelivery)
    assert len({original, claim.claim_event_id, delivery.dispatch_event_id}) == 3
    loaded = reader.load_task(db_session, case["admin_user"], claim.run_id)
    assert attempts.verify_delivery(db_session, loaded, delivery) == delivery
    assert loaded.artifact.usage_event_id is None and loaded.run.result_json == "{}"
    review_registry_original(db_session, case["super_admin_user"], "authorization", permissions[1]["source_record_id"], {"expected_revision": 2, "basis_note": BASIS}, revoke=True)
    before = db_session.query(AIAuditEvent).count()
    columns, sql, seen, emitted = observations(db_session)
    try:
        assert attempts.stage_dispatch(db_session, case["admin_user"], claim) is None
        assert attempts.stage_claim(db_session, case["admin_user"], claim.run_id) is None
    finally:
        stop(db_session, seen, emitted)
    assert not any(key in TASK_TEXT for _, key in columns)
    assert not any(key in statement for key in PRIVATE for statement in sql)
    assert db_session.query(AIAuditEvent).count() == before
    actual = db_session.execute(text("SELECT dispatch_event_id,usage_event_id FROM hoimsystem_ai_research_variable_run_artifact WHERE run_id=:id"), {"id": claim.run_id}).one()
    assert tuple(actual) == (delivery.dispatch_event_id, None)


@pytest.mark.parametrize("wrong", ["lease", "claim_pk"])
def test_wrong_original_lease_or_concrete_claim_pk_cannot_send_or_read_source_or_task_body(db_session, actual_task, wrong):
    case, _, _, _ = actual_task
    claim = claimed(db_session, actual_task)
    false = replace(claim, lease="00000000-0000-0000-0000-000000000001") if wrong == "lease" else replace(claim, claim_event_id=claim.create_event_id)
    before = db_session.query(AIAuditEvent).count()
    columns, sql, seen, emitted = observations(db_session)
    try:
        assert attempts.stage_dispatch(db_session, case["admin_user"], false) is None
    finally:
        stop(db_session, seen, emitted)
    assert not any(key in TASK_TEXT for _, key in columns)
    assert not any(key in statement for key in PRIVATE for statement in sql)
    assert db_session.query(AIAuditEvent).count() == before


@pytest.mark.parametrize("phase", ["claim", "dispatch"])
def test_real_postflush_specific_audit_mutation_rolls_back_entire_phase_preserving_original_claim(db_session, actual_task, phase):
    case, _, _, staged = actual_task
    identifier = inspect(staged.run).identity[0]
    claim = claimed(db_session, actual_task) if phase == "dispatch" else None
    before = db_session.query(AIAuditEvent).count()
    db_session.execute(
        text(
            "CREATE TRIGGER variable_task_phase_fault AFTER UPDATE OF detail_json ON hoimsystem_ai_audit_event "
            f"WHEN NEW.action='research_variable_run.{phase}' BEGIN UPDATE hoimsystem_ai_audit_event SET detail_json='{{}}' WHERE event_id=NEW.event_id; END"
        )
    )
    inserts = []

    def emitted(conn, cursor, statement, params, context, many):
        if statement.startswith("INSERT INTO hoimsystem_ai_audit_event"):
            inserts.append(statement)

    event.listen(db_session.bind, "before_cursor_execute", emitted)
    try:
        with pytest.raises(HTTPException) as error:
            if phase == "claim":
                attempts.stage_claim(db_session, case["admin_user"], identifier)
            else:
                attempts.stage_dispatch(db_session, case["admin_user"], claim)
        assert error.value.status_code == 409 and inserts
    finally:
        event.remove(db_session.bind, "before_cursor_execute", emitted)
    assert db_session.query(AIAuditEvent).count() == before
    loaded = reader.load_task(db_session, case["admin_user"], identifier)
    assert loaded.run.status == ("queued" if phase == "claim" else "running")
    assert loaded.artifact.dispatch_event_id is None and loaded.artifact.usage_event_id is None
    assert loaded.artifact.claim_event_id == (None if claim is None else claim.claim_event_id)
    assert loaded.run.lease_token == (None if claim is None else claim.lease)


def test_real_claim_postflush_role_mutation_rolls_back_run_original_actor_and_new_specific_audit(db_session, actual_task):
    case, _, _, staged = actual_task
    identifier = inspect(staged.run).identity[0]
    before = db_session.query(AIAuditEvent).count()
    db_session.execute(
        text(
            "CREATE TRIGGER variable_task_phase_fault AFTER UPDATE OF claim_event_id ON hoimsystem_ai_research_variable_run_artifact "
            "WHEN NEW.claim_event_id IS NOT NULL BEGIN UPDATE hoimsystem_users SET user_role='nurse' WHERE user_id=NEW.requested_by; END"
        )
    )
    with pytest.raises(HTTPException) as error:
        attempts.stage_claim(db_session, case["admin_user"], identifier)
    assert error.value.status_code == 403
    assert case["admin_user"].user_role == "admin" and db_session.query(AIAuditEvent).count() == before
    loaded = reader.load_task(db_session, case["admin_user"], identifier)
    assert loaded.run.status == "queued" and loaded.artifact.claim_event_id is None


@pytest.mark.parametrize("loss", ["source", "config"])
def test_before_dispatch_current_source_or_enabled_config_loss_blocks_task_body_and_never_creates_dispatch_or_usage(db_session, actual_task, configured, loss):
    case, permissions, _, _ = actual_task
    claim = claimed(db_session, actual_task)
    if loss == "source":
        review_registry_original(db_session, case["super_admin_user"], "authorization", permissions[1]["source_record_id"], {"expected_revision": 2, "basis_note": BASIS}, revoke=True)
    else:
        configured[1].enabled = 0
        db_session.commit()
    before = db_session.query(AIAuditEvent).count()
    columns, _, seen, emitted = observations(db_session)
    try:
        with pytest.raises(HTTPException) as error:
            attempts.stage_dispatch(db_session, case["admin_user"], claim)
        assert error.value.status_code == (403 if loss == "source" else 409)
    finally:
        stop(db_session, seen, emitted)
    assert not any(key in TASK_TEXT for _, key in columns)
    assert db_session.query(AIAuditEvent).count() == before
    actual = db_session.execute(text("SELECT claim_event_id,dispatch_event_id,usage_event_id FROM hoimsystem_ai_research_variable_run_artifact WHERE run_id=:id"), {"id": claim.run_id}).one()
    assert tuple(actual) == (claim.claim_event_id, None, None)
