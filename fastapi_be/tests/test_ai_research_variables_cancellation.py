"""Actual SQL cancellation/receipt atomicity; no HTTP endpoint claim here."""

import datetime as dt

import pytest
from fastapi import HTTPException
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from app.ai import research_variables_cancellation as cancellation
from app.ai import research_variables_receipts as receipts
from app.ai import research_variables_task_reader as reader
from app.ai import research_variables_task_views as views
from app.ai.models import AIAuditEvent
from app.ai.research_cohort_registry import review_registry_original
from app.ai.research_variables_storage_contract import VariableUsageReceipt
from app.config import settings
from tests.test_ai_research_cohort_contract import BASIS
from tests.test_ai_research_variables_attempts import claimed
from tests.test_ai_research_variables_configuration import configured as configured
from tests.test_ai_research_variables_receipts import delivered
from tests.test_ai_research_variables_task_context import research_case as research_case
from tests.test_ai_research_variables_task_context import task_factory as task_factory
from tests.test_ai_research_variables_task_reader import TASK_TEXT, observations, stop
from tests.test_ai_research_variables_task_reader import actual_task as actual_task


@pytest.fixture(autouse=True)
def cleanup_trigger(db_session):
    yield
    db_session.rollback()
    db_session.execute(text("DROP TRIGGER IF EXISTS variable_cancel_fault"))
    db_session.commit()


@pytest.mark.parametrize("phase", ["queued", "claimed", "dispatched"])
def test_real_super_stop_is_body_free_at_all_phases_with_real_zero_only_before_dispatch_and_paid_original_receipt_after_dispatch(db_session, actual_task, phase):
    case, _, _, staged = actual_task
    identifier = inspect(staged.run).identity[0]
    delivery = delivered(db_session, actual_task) if phase == "dispatched" else None
    if phase == "claimed":
        claimed(db_session, actual_task)
    columns, _, seen, emitted = observations(db_session)
    try:
        ack = cancellation.cancel_variable_run(db_session, case["super_admin_user"], identifier)
    finally:
        stop(db_session, seen, emitted)
    assert not any(name in TASK_TEXT for _, name in columns)
    assert ack["status"] == "cancelled" and ack["receipt_pending"] is (phase == "dispatched")
    assert (ack["usage_event_id"] is None) is (phase == "dispatched")
    assert ack["automatic_clinical_write"] is False and ack["automatic_export"] is False
    view = views.describe_variable_run(db_session, case["admin_user"], identifier)
    assert view["status"] == "cancelled" and view["result_reference"] is None
    if delivery is not None:
        assert view["usage_receipt"] is None
        usage = VariableUsageReceipt(input_tokens=11, output_tokens=None, complete=False, model_call_attempted=True)
        record = receipts.stage_terminal(
            db_session, delivery.claim, delivery=delivery, receipt=usage, status="failed", error_code="VARIABLE_RESULT_NOT_ACCEPTED", error_message="已取消但原分派仍需实际用量", latency_ms=123
        )
        db_session.commit()
        assert record.receipt == usage
        view = views.describe_variable_run(db_session, case["admin_user"], identifier)
        assert view["status"] == "cancelled" and view["usage_receipt"] == usage.model_dump()
    else:
        assert view["usage_receipt"] == {"input_tokens": 0, "output_tokens": 0, "complete": True, "model_call_attempted": False}
    before = db_session.query(AIAuditEvent).count()
    with pytest.raises(HTTPException) as error:
        cancellation.cancel_variable_run(db_session, case["super_admin_user"], identifier)
    assert error.value.status_code == 409 and db_session.query(AIAuditEvent).count() == before


def test_patient_purpose_loss_denies_ordinary_stop_before_task_body_but_super_explicit_technical_stop_does_not_restore_read_rights(db_session, actual_task):
    case, permissions, _, staged = actual_task
    identifier = inspect(staged.run).identity[0]
    review_registry_original(db_session, case["super_admin_user"], "authorization", permissions[1]["source_record_id"], {"expected_revision": 2, "basis_note": BASIS}, revoke=True)
    columns, _, seen, emitted = observations(db_session)
    try:
        with pytest.raises(HTTPException) as error:
            cancellation.cancel_variable_run(db_session, case["admin_user"], identifier)
        assert error.value.status_code == 403
        ack = cancellation.cancel_variable_run(db_session, case["super_admin_user"], identifier)
    finally:
        stop(db_session, seen, emitted)
    assert not any(name in TASK_TEXT for _, name in columns) and ack["receipt_pending"] is False
    with pytest.raises(HTTPException) as error:
        views.trace_variable_run(db_session, case["super_admin_user"], identifier)
    assert error.value.status_code == 403


@pytest.mark.parametrize("fault", ["abort", "role", "detail"])
def test_actual_cancel_sql_audit_or_actor_mutation_rolls_back_status_usage_and_exact_cancel_pk(db_session, actual_task, fault):
    case, _, _, staged = actual_task
    identifier = inspect(staged.run).identity[0]
    before = db_session.query(AIAuditEvent).count()
    if fault == "abort":
        action = "SELECT RAISE(ABORT,'actual controlled cancel audit abort');"
    elif fault == "role":
        action = "UPDATE hoimsystem_users SET user_role='admin' WHERE user_id=NEW.actor_id;"
    else:
        action = "UPDATE hoimsystem_ai_audit_event SET detail_json='{}' WHERE event_id=NEW.event_id;"
    db_session.execute(text("CREATE TRIGGER variable_cancel_fault AFTER INSERT ON hoimsystem_ai_audit_event WHEN NEW.action='research_variable_run.cancel' BEGIN " + action + " END"))
    with pytest.raises((HTTPException, IntegrityError)):
        cancellation.cancel_variable_run(db_session, case["super_admin_user"], identifier)
    assert db_session.query(AIAuditEvent).count() == before
    state = db_session.execute(text("SELECT status,lease_token,finish_time FROM hoimsystem_ai_run WHERE run_id=:id"), {"id": identifier}).one()
    assert tuple(state) == ("queued", None, None)
    assert db_session.execute(text("SELECT usage_event_id FROM hoimsystem_ai_research_variable_run_artifact WHERE run_id=:id"), {"id": identifier}).scalar() is None
    assert case["super_admin_user"].user_role == "super_admin"


def test_original_task_age_is_checked_for_execution_before_task_body_but_not_used_to_remove_current_ordinary_read_access(db_session, actual_task, monkeypatch):
    case, _, _, staged = actual_task
    identifier = inspect(staged.run).identity[0]
    moment = staged.artifact.recorded_at + dt.timedelta(seconds=settings.AI_MAX_QUEUE_AGE_SECONDS + 1)
    monkeypatch.setattr(reader, "utcnow", lambda: moment)
    columns, _, seen, emitted = observations(db_session)
    try:
        with pytest.raises(HTTPException) as error:
            reader.load_task(db_session, case["admin_user"], identifier, for_execution=True)
        assert error.value.status_code == 409
    finally:
        stop(db_session, seen, emitted)
    assert not any(name in TASK_TEXT for _, name in columns)
    assert reader.load_task(db_session, case["admin_user"], identifier).run.status == "queued"
