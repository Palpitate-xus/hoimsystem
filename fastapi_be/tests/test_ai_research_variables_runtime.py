"""Actual Source/current SQL creation, quota and concrete queue ownership.

This layer makes no HTTP/model call and is not Main/JWT or MySQL lock proof.
"""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import inspect

from app.ai import research_variables_receipts as receipts
from app.ai import research_variables_runtime as runtime
from app.ai import research_variables_task_reader as reader
from app.ai.models import AIAuditEvent, AIRun
from app.ai.research_cohort_registry import review_registry_original
from app.ai.research_variables_run_models import AIResearchVariableRunArtifact
from app.ai.research_variables_task_contract import FEATURE_KEY
from tests.test_ai_research_cohort_contract import BASIS
from tests.test_ai_research_variables_configuration import configured as configured
from tests.test_ai_research_variables_task_context import research_case as research_case
from tests.test_ai_research_variables_task_context import task_factory as task_factory
from tests.test_ai_research_variables_task_reader import TASK_TEXT, observations, stop
from tests.test_ai_research_variables_task_reader import actual_task as actual_task


def request(batch_id, **overrides):
    return SimpleNamespace(
        feature_key=FEATURE_KEY, patient_id=None, encounter_ref=None, preview=False, input={"research_variable_batch_id": batch_id, "question": "\ufeff原始问题\r\n🧪e\u0301"}, **overrides
    )


def test_actual_source_to_queue_to_authentic_claim_is_atomic_without_model_call_or_fake_usage(db_session, configured, task_factory):
    case, _, _, _, batch, _ = task_factory()
    before = db_session.query(AIAuditEvent).count()
    run = runtime.create_variable_run(db_session, case["admin_user"], request(batch["batch_id"]))
    identifier = inspect(run).identity[0]
    artifact = db_session.get(AIResearchVariableRunArtifact, identifier)
    assert run.status == "queued" and artifact.claim_event_id is None and artifact.dispatch_event_id is None and artifact.usage_event_id is None
    assert db_session.query(AIAuditEvent).count() == before + 1
    lease = runtime.claim_variable_run(db_session, identifier)
    task = reader.load_task(db_session, case["admin_user"], identifier)
    assert task.run.status == "running" and task.run.lease_token == lease and task.artifact.claim_lease == lease
    assert task.artifact.claim_event_id != artifact.create_event_id and task.artifact.dispatch_event_id is None and task.artifact.usage_event_id is None
    count = db_session.query(AIAuditEvent).count()
    assert runtime.claim_variable_run(db_session, identifier) is None
    assert db_session.query(AIAuditEvent).count() == count


def test_explicit_quota_counts_only_same_feature_owner_and_day_and_rejects_without_partial_rows(db_session, configured, task_factory):
    case, _, _, _, batch, _ = task_factory()
    # This repository intentionally preserves transactions between cases in a
    # module. Earlier real runs remain real quota consumers, not fixture noise.
    configured[1].daily_limit = runtime.current_daily_count(db_session, case["admin_user"].user_id, runtime.utcnow()) + 1
    db_session.commit()
    runtime.create_variable_run(db_session, case["admin_user"], request(batch["batch_id"]))
    before = (db_session.query(AIRun).count(), db_session.query(AIResearchVariableRunArtifact).count(), db_session.query(AIAuditEvent).count())
    with pytest.raises(HTTPException) as error:
        runtime.create_variable_run(db_session, case["admin_user"], request(batch["batch_id"]))
    assert error.value.status_code == 429
    assert (db_session.query(AIRun).count(), db_session.query(AIResearchVariableRunArtifact).count(), db_session.query(AIAuditEvent).count()) == before


@pytest.mark.parametrize("change", ["patient", "role", "config"])
def test_current_authority_lost_before_queue_claim_closes_only_original_pristine_task_with_exact_known_uncalled_usage_and_zero_task_body(db_session, actual_task, change):
    case, permissions, _, staged = actual_task
    identifier = inspect(staged.run).identity[0]
    if change == "patient":
        review_registry_original(db_session, case["super_admin_user"], "authorization", permissions[1]["source_record_id"], {"expected_revision": 2, "basis_note": BASIS}, revoke=True)
    elif change == "role":
        case["admin_user"].user_role = "nurse"
        db_session.commit()
    else:
        from app.ai.models import AIFeatureConfig

        db_session.get(AIFeatureConfig, FEATURE_KEY).enabled = 0
        db_session.commit()
    columns, _, seen, emitted = observations(db_session)
    try:
        assert runtime.claim_variable_run(db_session, identifier) is None
    finally:
        stop(db_session, seen, emitted)
    assert not any(name in TASK_TEXT for _, name in columns)
    header, artifact = reader._headers(db_session, (identifier, staged.artifact.batch_id, staged.artifact.requested_by), exclusive=False)
    reader._creation_audit(db_session, header, artifact)
    task = SimpleNamespace(run=SimpleNamespace(**header), artifact=SimpleNamespace(**artifact))
    record = receipts.verify_receipt(db_session, task)
    assert header["status"] == "failed" and header["lease_token"] is None and header["start_time"] is None
    assert artifact["claim_event_id"] is None and artifact["dispatch_event_id"] is None
    assert (record.receipt.input_tokens, record.receipt.output_tokens, record.receipt.model_call_attempted) == (0, 0, False)


@pytest.mark.parametrize("axis,value", [("feature_key", "operations_qa"), ("patient_id", 1), ("encounter_ref", "private"), ("preview", 1)])
def test_foreign_task_scope_is_rejected_before_any_sql(db_session, configured, axis, value):
    req = request("00000000-0000-0000-0000-000000000001")
    setattr(req, axis, value)
    columns, statements, seen, emitted = observations(db_session)
    try:
        with pytest.raises(HTTPException) as error:
            runtime.create_variable_run(db_session, configured[0]["super_admin_user"], req)
        assert error.value.status_code == 422
    finally:
        stop(db_session, seen, emitted)
    assert not columns and not statements
