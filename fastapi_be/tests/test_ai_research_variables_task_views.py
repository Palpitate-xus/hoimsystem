"""Actual SQL split receipts, raw byte trace and current-purpose read boundary."""

import hashlib

import pytest
from fastapi import HTTPException
from sqlalchemy import inspect, text

from app.ai import research_variables_result_storage as results
from app.ai import research_variables_task_views as views
from app.ai.research_cohort_registry import review_registry_original
from app.ai.research_variables_batches import review_batch
from app.ai.research_variables_storage_contract import VariableUsageReceipt
from app.ai.research_variables_task_contract import canonical
from tests.test_ai_research_cohort_contract import BASIS
from tests.test_ai_research_variables_configuration import configured as configured
from tests.test_ai_research_variables_receipts import delivered
from tests.test_ai_research_variables_result_storage import material
from tests.test_ai_research_variables_task_context import research_case as research_case
from tests.test_ai_research_variables_task_context import task_factory as task_factory
from tests.test_ai_research_variables_task_reader import TASK_TEXT, observations, stop
from tests.test_ai_research_variables_task_reader import actual_task as actual_task


def test_queued_receipt_does_not_present_legacy_physical_zero_as_received_usage_and_returns_complete_independent_parts(db_session, actual_task):
    case, _, _, staged = actual_task
    identifier = inspect(staged.run).identity[0]
    value = views.describe_variable_run(db_session, case["admin_user"], identifier, False)
    assert value["status"] == "queued" and value["result"] is None and value["result_reference"] is None
    assert value["usage_receipt"] is None and value["input_tokens"] is None and value["output_tokens"] is None and value["usage_receipt_status"] == "pending"
    assert "source_json" not in canonical(value) and "private_scope" not in value
    for part in ("binding", "source", "scope", "receipt"):
        actual = views.read_variable_part(db_session, case["admin_user"], identifier, part)
        assert len(canonical(actual).encode()) <= 8388608
    with pytest.raises(HTTPException) as error:
        views.read_variable_part(db_session, case["admin_user"], identifier, "result")
    assert error.value.status_code == 409


def test_accepted_partial_usage_stays_nullable_result_is_only_its_own_complete_piece_and_trace_anchors_actual_raw_json(db_session, actual_task):
    case, _, _, _ = actual_task
    delivery = delivered(db_session, actual_task)
    accepted = material(db_session, case, delivery)
    usage = VariableUsageReceipt(input_tokens=11, output_tokens=None, complete=False, model_call_attempted=True)
    reference = results.stage_result(db_session, case["admin_user"], delivery, accepted, usage, latency_ms=123)
    db_session.commit()
    detail = views.describe_variable_run(db_session, case["admin_user"], delivery.claim.run_id)
    assert detail["status"] == "succeeded" and detail["result"] is None and detail["result_reference"] == reference.model_dump(mode="json")
    assert detail["usage_receipt"] == usage.model_dump() and detail["output_tokens"] is None
    assert views.read_variable_part(db_session, case["admin_user"], delivery.claim.run_id, "result")["result"] == accepted.model_dump(mode="json")
    trace = views.trace_variable_run(db_session, case["super_admin_user"], delivery.claim.run_id)
    for raw, anchor in (("input_json", "input_hash"), ("evidence_json", "evidence_hash"), ("context_metadata_json", "metadata_hash")):
        assert hashlib.sha256(trace["raw_frozen_json"][raw].encode()).hexdigest() == trace["research_variable_artifact"][anchor]
    assert trace["frozen_audit"] is True and trace["execution_current"] is False
    assert trace["request_authorization_hash"] == trace["research_variable_artifact"]["request_authorization_hash"]


@pytest.mark.parametrize("part", ["detail", "source", "scope", "result", "receipt", "trace"])
def test_current_patient_purpose_loss_denies_every_piece_before_any_task_body_including_explicit_super_trace(db_session, actual_task, part):
    case, permissions, _, staged = actual_task
    identifier = inspect(staged.run).identity[0]
    review_registry_original(db_session, case["super_admin_user"], "authorization", permissions[1]["source_record_id"], {"expected_revision": 2, "basis_note": BASIS}, revoke=True)
    columns, _, seen, emitted = observations(db_session)
    try:
        with pytest.raises(HTTPException) as error:
            if part == "detail":
                views.describe_variable_run(db_session, case["admin_user"], identifier)
            elif part == "trace":
                views.trace_variable_run(db_session, case["super_admin_user"], identifier)
            else:
                views.read_variable_part(db_session, case["admin_user"], identifier, part)
        assert error.value.status_code == 403
    finally:
        stop(db_session, seen, emitted)
    assert not any(name in TASK_TEXT for _, name in columns)


def test_revoked_batch_is_not_an_ordinary_read_but_explicit_super_with_current_purposes_can_rebuild_original_frozen_trace(db_session, actual_task):
    case, _, batch, staged = actual_task
    identifier = inspect(staged.run).identity[0]
    old = staged.binding.batch_governance_hash
    review_batch(db_session, case["super_admin_user"], batch["batch_id"], {"expected_revision": 2, "basis_note": BASIS}, revoke=True)
    with pytest.raises(HTTPException) as error:
        views.describe_variable_run(db_session, case["admin_user"], identifier)
    assert error.value.status_code == 409
    trace = views.trace_variable_run(db_session, case["super_admin_user"], identifier)
    assert trace["frozen_request"]["batch_publication"]["status"] == "published"
    bound = views.read_variable_part(db_session, case["super_admin_user"], identifier, "binding", frozen_audit=True)
    assert bound["binding"]["batch_governance_hash"] == old


@pytest.mark.parametrize("raw", ["{}", '{"schema_version":"research_variable_result_ref_v1","extra":true}', '{"schema_version":null,"schema_version":"research_variable_result_ref_v1"}'])
def test_corrupt_terminal_pointer_is_409_in_short_detail_instead_of_untyped_500_or_generic_result(db_session, actual_task, raw):
    case, _, _, staged = actual_task
    identifier = inspect(staged.run).identity[0]
    db_session.execute(text("UPDATE hoimsystem_ai_run SET status='succeeded',result_json=:raw WHERE run_id=:id"), {"raw": raw, "id": identifier})
    db_session.commit()
    with pytest.raises(HTTPException) as error:
        views.describe_variable_run(db_session, case["admin_user"], identifier, False)
    assert error.value.status_code == 409
