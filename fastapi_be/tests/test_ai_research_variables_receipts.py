"""Actual original dispatch settlement after Source/role loss, without BODY.

No provider inference or successful result is claimed by these terminal tests.
Controlled receipts stand for the original worker's received counters only.
"""

from dataclasses import replace

import pytest
from fastapi import HTTPException
from sqlalchemy import event, text

from app.ai import research_variables_attempts as attempts
from app.ai import research_variables_receipts as receipts
from app.ai.models import AIAuditEvent
from app.ai.research_cohort_registry import review_registry_original
from app.ai.research_variables_storage_contract import VariableUsageReceipt
from tests.test_ai_research_cohort_contract import BASIS
from tests.test_ai_research_variables_attempts import claimed
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
    db_session.execute(text("DROP TRIGGER IF EXISTS variable_receipt_fault"))
    db_session.commit()


def delivered(db, actual_task):
    case = actual_task[0]
    claim = claimed(db, actual_task)
    delivery = attempts.stage_dispatch(db, case["admin_user"], claim)
    db.commit()
    assert isinstance(delivery, attempts.VariableDelivery)
    return delivery


def terminate(db, claim, delivery, receipt, **kwargs):
    return receipts.stage_terminal(
        db,
        claim,
        delivery=delivery,
        receipt=receipt,
        status="failed",
        error_code=kwargs.get("error_code", "SOURCE_NO_LONGER_CURRENT"),
        error_message="实际原分派完成后当前授权不再满足，仅结算本次实际用量，未返回正文。",
        latency_ms=321,
    )


@pytest.mark.parametrize("counts", [(11, 13), (11, None), (None, None)])
def test_actual_original_paid_delivery_source_loss_nullable_receipt_commits_exact_pk_and_duplicate_is_inert_without_any_task_or_source_body(db_session, actual_task, counts):
    case, permissions, _, _ = actual_task
    delivery = delivered(db_session, actual_task)
    review_registry_original(db_session, case["super_admin_user"], "authorization", permissions[1]["source_record_id"], {"expected_revision": 2, "basis_note": BASIS}, revoke=True)
    receipt = VariableUsageReceipt(input_tokens=counts[0], output_tokens=counts[1], complete=all(value is not None for value in counts), model_call_attempted=True)
    before = db_session.query(AIAuditEvent).count()
    columns, sql, seen, emitted = observations(db_session)
    try:
        recorded = terminate(db_session, delivery.claim, delivery, receipt)
        db_session.commit()
        assert terminate(db_session, delivery.claim, delivery, receipt) is None
    finally:
        stop(db_session, seen, emitted)
    assert not any(key in TASK_TEXT for _, key in columns)
    assert not any(key in statement for key in PRIVATE for statement in sql)
    assert recorded.receipt == receipt and recorded.dispatch_event_id == delivery.dispatch_event_id
    assert recorded.claim_event_id == delivery.claim.claim_event_id and recorded.claim_lease == delivery.claim.lease
    assert db_session.query(AIAuditEvent).count() == before + 1
    task = receipts.technical_task(db_session, delivery.claim)
    verified = receipts.verify_receipt(db_session, task)
    assert verified == recorded and task.run.status == "failed" and task.run.latency_ms == 321
    assert (verified.receipt.input_tokens, verified.receipt.output_tokens) == counts
    assert (task.run.input_tokens, task.run.output_tokens) == tuple(value if value is not None else 0 for value in counts)


def test_role_lost_after_original_dispatch_can_only_settle_paid_usage_without_loading_source_or_task_or_restoring_role(db_session, actual_task):
    case = actual_task[0]
    delivery = delivered(db_session, actual_task)
    case["admin_user"].user_role = "nurse"
    db_session.commit()
    receipt = VariableUsageReceipt(input_tokens=11, output_tokens=None, complete=False, model_call_attempted=True)
    columns, sql, seen, emitted = observations(db_session)
    try:
        recorded = terminate(db_session, delivery.claim, delivery, receipt)
        db_session.commit()
    finally:
        stop(db_session, seen, emitted)
    assert recorded.receipt == receipt and case["admin_user"].user_role == "nurse"
    assert not any(key in TASK_TEXT for _, key in columns)
    assert not any(key in statement for key in PRIVATE for statement in sql)


def test_old_no_dispatch_observation_cannot_seize_another_actual_dispatch_or_write_fake_zero_receipt(db_session, actual_task):
    delivery = delivered(db_session, actual_task)
    before = db_session.query(AIAuditEvent).count()
    false_zero = VariableUsageReceipt(input_tokens=0, output_tokens=0, complete=True, model_call_attempted=False)
    assert terminate(db_session, delivery.claim, None, false_zero) is None
    assert db_session.query(AIAuditEvent).count() == before
    actual = receipts.technical_task(db_session, delivery.claim)
    assert actual.artifact.dispatch_event_id == delivery.dispatch_event_id and actual.artifact.usage_event_id is None and actual.run.status == "running"


def test_claimed_no_dispatch_source_loss_is_known_uncalled_zero_without_fake_dispatch_or_successful_result(db_session, actual_task):
    case, permissions, _, _ = actual_task
    claim = claimed(db_session, actual_task)
    review_registry_original(db_session, case["super_admin_user"], "authorization", permissions[1]["source_record_id"], {"expected_revision": 2, "basis_note": BASIS}, revoke=True)
    uncalled = VariableUsageReceipt(input_tokens=0, output_tokens=0, complete=True, model_call_attempted=False)
    recorded = terminate(db_session, claim, None, uncalled)
    db_session.commit()
    assert recorded.receipt == uncalled and recorded.dispatch_event_id is None
    actual = receipts.technical_task(db_session, claim)
    assert actual.artifact.dispatch_event_id is None and actual.run.status == "failed"
    assert actual.artifact.usage_event_id == recorded.usage_event_id


def test_wrong_claim_lease_or_original_dispatch_pk_cannot_take_ownership_of_terminal_receipt(db_session, actual_task):
    delivery = delivered(db_session, actual_task)
    before = db_session.query(AIAuditEvent).count()
    usage = VariableUsageReceipt(input_tokens=11, output_tokens=13, complete=True, model_call_attempted=True)
    assert terminate(db_session, replace(delivery.claim, lease="00000000-0000-0000-0000-000000000001"), delivery, usage) is None
    with pytest.raises(HTTPException) as error:
        terminate(db_session, delivery.claim, replace(delivery, dispatch_event_id=delivery.claim.create_event_id), usage)
    assert error.value.status_code == 409 and db_session.query(AIAuditEvent).count() == before
    assert receipts.technical_task(db_session, delivery.claim).artifact.usage_event_id is None


def test_only_explicit_worker_interrupted_can_keep_attempt_itself_unknown_and_cannot_invent_token_zero(db_session, actual_task):
    delivery = delivered(db_session, actual_task)
    unknown = VariableUsageReceipt(input_tokens=None, output_tokens=None, complete=False, model_call_attempted=None)
    with pytest.raises(HTTPException) as error:
        terminate(db_session, delivery.claim, delivery, unknown)
    assert error.value.status_code == 422
    recorded = terminate(db_session, delivery.claim, delivery, unknown, error_code="WORKER_INTERRUPTED")
    db_session.commit()
    assert recorded.receipt == unknown and recorded.receipt.model_call_attempted is None
    assert not recorded.receipt.complete


@pytest.mark.parametrize("fault", ["audit", "header", "abort"])
def test_actual_sql_receipt_audit_failure_or_postflush_tamper_rolls_back_entire_terminal_and_preserves_original_dispatch(db_session, actual_task, fault):
    delivery = delivered(db_session, actual_task)
    before = db_session.query(AIAuditEvent).count()
    if fault == "audit":
        trigger = "CREATE TRIGGER variable_receipt_fault AFTER UPDATE OF detail_json ON hoimsystem_ai_audit_event WHEN NEW.action='research_variable_run.usage' BEGIN UPDATE hoimsystem_ai_audit_event SET detail_json='{}' WHERE event_id=NEW.event_id; END"
    elif fault == "header":
        trigger = "CREATE TRIGGER variable_receipt_fault AFTER UPDATE OF usage_event_id ON hoimsystem_ai_research_variable_run_artifact WHEN NEW.usage_event_id IS NOT NULL BEGIN UPDATE hoimsystem_ai_run SET status='succeeded' WHERE run_id=NEW.run_id; END"
    else:
        trigger = "CREATE TRIGGER variable_receipt_fault BEFORE INSERT ON hoimsystem_ai_audit_event WHEN NEW.action='research_variable_run.usage' BEGIN SELECT RAISE(ABORT,'controlled actual usage audit failure'); END"
    db_session.execute(text(trigger))
    inserts = []

    def emitted(conn, cursor, statement, params, context, many):
        if statement.startswith("INSERT INTO hoimsystem_ai_audit_event"):
            inserts.append(statement)

    event.listen(db_session.bind, "before_cursor_execute", emitted)
    try:
        from sqlalchemy.exc import IntegrityError

        with pytest.raises((HTTPException, IntegrityError)) as error:
            terminate(db_session, delivery.claim, delivery, VariableUsageReceipt(input_tokens=11, output_tokens=None, complete=False, model_call_attempted=True))
        assert inserts
        if fault == "abort":
            assert isinstance(error.value, IntegrityError) and "controlled actual usage audit failure" in str(error.value)
        else:
            assert isinstance(error.value, HTTPException) and error.value.status_code == 409
    finally:
        event.remove(db_session.bind, "before_cursor_execute", emitted)
    assert db_session.query(AIAuditEvent).count() == before
    actual = receipts.technical_task(db_session, delivery.claim)
    assert actual.run.status == "running" and actual.run.finish_time is None
    assert actual.artifact.dispatch_event_id == delivery.dispatch_event_id and actual.artifact.usage_event_id is None


def test_before_claim_source_loss_has_real_known_uncalled_usage_pk_without_fake_claim_or_any_body(db_session, actual_task):
    case, permissions, _, staged = actual_task
    identifier, create_pk = staged.run.run_id, staged.artifact.create_event_id
    review_registry_original(db_session, case["super_admin_user"], "authorization", permissions[1]["source_record_id"], {"expected_revision": 2, "basis_note": BASIS}, revoke=True)
    columns, sql, seen, emitted = observations(db_session)
    try:
        recorded = receipts.stage_queued_terminal(
            db_session, identifier, expected_create_event_id=create_pk, status="failed", error_code="SOURCE_NO_LONGER_CURRENT", error_message="实际领取前来源失效，确定未调用。"
        )
        db_session.commit()
    finally:
        stop(db_session, seen, emitted)
    assert recorded.claim_event_id is None and recorded.dispatch_event_id is None and recorded.claim_lease is None
    assert recorded.receipt.model_call_attempted is False and (recorded.receipt.input_tokens, recorded.receipt.output_tokens) == (0, 0)
    assert not any(key in TASK_TEXT for _, key in columns)
    assert not any(key in statement for key in PRIVATE for statement in sql)


def test_stale_queued_observation_after_actual_claim_cannot_cancel_or_replace_claim_with_fake_uncalled_zero(db_session, actual_task):
    staged = actual_task[3]
    identifier, create_pk = staged.run.run_id, staged.artifact.create_event_id
    claim = claimed(db_session, actual_task)
    before = db_session.query(AIAuditEvent).count()
    assert (
        receipts.stage_queued_terminal(db_session, identifier, expected_create_event_id=create_pk, status="cancelled", error_code="CANCELLED", error_message="原观察已过时，不能覆盖实际领取。") is None
    )
    assert db_session.query(AIAuditEvent).count() == before
    current = receipts.technical_task(db_session, claim)
    assert current.run.status == "running" and current.artifact.claim_event_id == claim.claim_event_id and current.artifact.usage_event_id is None
