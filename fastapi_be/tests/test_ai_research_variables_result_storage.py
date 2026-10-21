"""Actual SQL whole result/short pointer/acceptance and usage atomicity.

Model result and counters below are explicit controlled literal/receipt inputs;
no provider inference or complete runtime pipeline is claimed here.
"""

import datetime as dt
import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import event, text
from sqlalchemy.exc import IntegrityError

from app.ai import research_variables_result_storage as results
from app.ai import research_variables_task_reader as reader
from app.ai.models import AIAuditEvent
from app.ai.research_variables_run_models import AIResearchVariableRunResult
from app.ai.research_variables_storage_contract import VariableUsageReceipt
from app.ai.research_variables_task_contract import canonical
from app.ai.research_variables_task_result import bind_draft, result_for_draft
from app.models import MedicalRecord
from tests.test_ai_research_variables_configuration import configured as configured
from tests.test_ai_research_variables_receipts import delivered, terminate
from tests.test_ai_research_variables_storage import prepare
from tests.test_ai_research_variables_task_context import research_case as research_case
from tests.test_ai_research_variables_task_context import task_factory as task_factory
from tests.test_ai_research_variables_task_reader import actual_task as actual_task


@pytest.fixture(autouse=True)
def cleanup_trigger(db_session):
    yield
    db_session.rollback()
    db_session.execute(text("DROP TRIGGER IF EXISTS variable_result_fault"))
    db_session.commit()


def material(db, case, delivery):
    loaded = reader.load_task(db, case["admin_user"], delivery.claim.run_id)
    candidates = []
    for original in loaded.source.documents:
        row = original.model_dump(mode="json")
        literal = row.pop("literal")
        if literal is not None and literal.replace("\ufeff", "").strip() and len(literal) <= 4000:
            candidates.append({**row, "classification": "value_quote_candidate", "start": 0, "end": len(literal), "quote": literal})
    draft = {"schema_version": "research_variable_draft_v1", "coverage": "partial_candidates_only", "candidates": candidates}
    return result_for_draft(bind_draft(draft, loaded.source, loaded.artifact.instructions_digest), loaded.source, loaded.artifact.instructions_digest)


@pytest.mark.parametrize("counts", [(11, 13), (11, None), (None, None)])
def test_complete_valid_literal_result_succeeds_with_full_partial_or_absent_actual_usage_and_five_distinct_audit_pks(db_session, actual_task, counts):
    case = actual_task[0]
    delivery = delivered(db_session, actual_task)
    value = material(db_session, case, delivery)
    usage = VariableUsageReceipt(input_tokens=counts[0], output_tokens=counts[1], complete=all(number is not None for number in counts), model_call_attempted=True)
    reference = results.stage_result(db_session, case["admin_user"], delivery, value, usage, latency_ms=123)
    db_session.commit()
    assert isinstance(reference, results.VariableResultReference)
    loaded = reader.load_task(db_session, case["admin_user"], delivery.claim.run_id)
    assert loaded.run.status == "succeeded" and len(loaded.run.result_json.encode()) < 1000
    assert len({loaded.artifact.create_event_id, loaded.artifact.claim_event_id, loaded.artifact.dispatch_event_id, loaded.artifact.usage_event_id, reference.accept_audit_event_id}) == 5
    part = results.result_piece(db_session, case["admin_user"], delivery.claim.run_id)
    assert part["result"] == value.model_dump(mode="json") and part["usage_receipt"] == usage.model_dump(mode="json")
    assert part["reference"] == reference.model_dump(mode="json")
    assert results.stage_result(db_session, case["admin_user"], delivery, value, usage, latency_ms=123) is None
    assert db_session.query(AIResearchVariableRunResult).filter_by(run_id=delivery.claim.run_id).count() == 1


def test_actual_legacy_text_fields_with_whole_published_batch_produce_over65k_result_in_separate_blob_not_run_text(db_session, research_case, configured, task_factory):
    case = research_case
    db_session.add_all(
        [
            MedicalRecord(
                medical_record_id=str(uuid.uuid4()),
                patient_id=case["patient"].patient_id,
                doctor_id=case["doctor"].doctor_id,
                consultation_time=dt.datetime(2026, 10, 11, 9, index),
                symptom="🧪" * 4000,
                status=1,
            )
            for index in range(5)
        ]
    )
    db_session.commit()
    from app.ai import research_variables_storage as storage
    from app.ai.models import AIRun

    case, permissions, batch, prepared, snapshot = prepare(db_session, configured, task_factory)
    staged = storage.stage_run(db_session, case["admin_user"], AIRun(run_id=str(uuid.uuid4()), preview=0), prepared, snapshot)
    db_session.commit()
    delivery = delivered(db_session, (case, permissions, batch, staged))
    value = material(db_session, case, delivery)
    assert len(canonical(value).encode()) > 65535
    usage = VariableUsageReceipt(input_tokens=None, output_tokens=None, complete=False, model_call_attempted=True)
    reference = results.stage_result(db_session, case["admin_user"], delivery, value, usage, latency_ms=123)
    db_session.commit()
    assert reference.result_bytes > 65535
    loaded = reader.load_task(db_session, case["admin_user"], delivery.claim.run_id)
    assert len(loaded.run.result_json.encode()) < 1000
    part = results.result_piece(db_session, case["admin_user"], delivery.claim.run_id)
    assert len(canonical(part).encode()) > 65535 and part["result"] == value.model_dump(mode="json")


def test_cancelled_during_http_acceptance_none_must_still_settle_original_paid_delivery_without_result_or_fake_zero(db_session, actual_task):
    case = actual_task[0]
    delivery = delivered(db_session, actual_task)
    value = material(db_session, case, delivery)
    # Controlled actual SQL cancellation state, not an HTTP cancel proof. The
    # upcoming Runtime/API tests own that endpoint and cancellation timing.
    db_session.execute(text("UPDATE hoimsystem_ai_run SET status='cancelled' WHERE run_id=:id"), {"id": delivery.claim.run_id})
    db_session.commit()
    usage = VariableUsageReceipt(input_tokens=11, output_tokens=None, complete=False, model_call_attempted=True)
    assert results.stage_result(db_session, case["admin_user"], delivery, value, usage, latency_ms=222) is None
    db_session.rollback()
    recorded = terminate(db_session, delivery.claim, delivery, usage)
    db_session.commit()
    assert recorded.receipt == usage
    assert results.receipts.technical_task(db_session, delivery.claim).run.status == "cancelled"
    assert db_session.query(AIResearchVariableRunResult).filter_by(run_id=delivery.claim.run_id).count() == 0


@pytest.mark.parametrize("fault", ["accept_abort", "usage_abort", "blob", "pointer", "source_loss"])
def test_real_sql_acceptance_fault_rolls_back_blob_pointer_success_both_audits_and_trigger_side_effects(db_session, actual_task, fault):
    case = actual_task[0]
    delivery = delivered(db_session, actual_task)
    value = material(db_session, case, delivery)
    before = db_session.query(AIAuditEvent).count()
    if fault in {"accept_abort", "usage_abort"}:
        action = "accept" if fault == "accept_abort" else "usage"
        trigger = f"CREATE TRIGGER variable_result_fault BEFORE INSERT ON hoimsystem_ai_audit_event WHEN NEW.action='research_variable_run.{action}' BEGIN SELECT RAISE(ABORT,'controlled actual full result audit failure'); END"
    elif fault == "blob":
        trigger = "CREATE TRIGGER variable_result_fault AFTER INSERT ON hoimsystem_ai_research_variable_run_result BEGIN UPDATE hoimsystem_ai_research_variable_run_result SET result_json='{}',result_bytes=2 WHERE run_id=NEW.run_id; END"
    elif fault == "pointer":
        trigger = "CREATE TRIGGER variable_result_fault AFTER INSERT ON hoimsystem_ai_research_variable_run_result BEGIN UPDATE hoimsystem_ai_run SET result_json='{}' WHERE run_id=NEW.run_id; END"
    else:
        trigger = "CREATE TRIGGER variable_result_fault AFTER INSERT ON hoimsystem_ai_research_variable_run_result BEGIN UPDATE hoimsystem_users SET user_role='nurse' WHERE user_id=(SELECT requested_by FROM hoimsystem_ai_run WHERE run_id=NEW.run_id); END"
    db_session.execute(text(trigger))
    statements = []

    def emitted(conn, cursor, statement, params, context, many):
        if statement.startswith("INSERT INTO hoimsystem_ai_"):
            statements.append(statement)

    event.listen(db_session.bind, "before_cursor_execute", emitted)
    try:
        with pytest.raises((HTTPException, IntegrityError)) as error:
            results.stage_result(db_session, case["admin_user"], delivery, value, VariableUsageReceipt(input_tokens=11, output_tokens=None, complete=False, model_call_attempted=True), latency_ms=123)
        assert any(statement.startswith("INSERT INTO hoimsystem_ai_audit_event") for statement in statements)
        if fault in {"accept_abort", "usage_abort"}:
            assert isinstance(error.value, IntegrityError) and "controlled actual full result audit failure" in str(error.value)
        else:
            assert isinstance(error.value, HTTPException) and error.value.status_code == (403 if fault == "source_loss" else 409)
    finally:
        event.remove(db_session.bind, "before_cursor_execute", emitted)
    assert db_session.query(AIAuditEvent).count() == before
    assert db_session.query(AIResearchVariableRunResult).filter_by(run_id=delivery.claim.run_id).count() == 0
    assert case["admin_user"].user_role == "admin"
    loaded = reader.load_task(db_session, case["admin_user"], delivery.claim.run_id)
    assert loaded.run.status == "running" and loaded.run.result_json == "{}" and loaded.artifact.usage_event_id is None
    assert loaded.artifact.dispatch_event_id == delivery.dispatch_event_id
