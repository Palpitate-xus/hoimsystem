"""Actual nullable technical usage, lease and postwrite SQL fault checks."""

import uuid

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import text

from app.ai.models import AIAuditEvent, AIProvider, AIRun
from app.ai.research_cohort_artifact_models import AIResearchCohortRunArtifact
from app.ai.research_cohort_cases import case_current
from app.ai.research_cohort_receipts import ResearchUsage, read_usage_event, stage_terminal_receipt, usage
from app.ai.research_cohort_registry import review_registry_original
from app.ai.research_cohort_storage import freeze_artifact
from tests.test_ai_research_cohort_contract import BASIS

# Import the actual fixture chain explicitly; no source/auth stub is involved.
from tests.test_ai_research_cohort_storage import artifact_foreign_keys as artifact_foreign_keys  # noqa: F401
from tests.test_ai_research_cohort_storage import capture_sql, task_body_selects
from tests.test_ai_research_cohort_storage import configured as configured  # noqa: F401
from tests.test_ai_research_cohort_storage import research_case as research_case  # noqa: F401
from tests.test_ai_research_cohort_storage import storage_rows as storage_rows  # noqa: F401


@pytest.fixture
def claimed(configured):
    db, actor, run_id, _, values, _ = configured
    from app.ai.research_cohort_execution import claim_research_run, reserve_research_dispatch

    db.get(AIProvider, values["provider_id"]).api_base = "http://127.0.0.1:8825/v1"
    db.commit()
    freeze_artifact(db, actor, run_id, values["case_id"])
    db.commit()
    claim = claim_research_run(db, run_id)
    assert claim is not None
    reserve_research_dispatch(db, run_id, claim.lease_token, claim.claim_event_id)
    db.commit()
    return configured, claim.lease_token


@pytest.mark.parametrize(
    "payload",
    [
        {"input_tokens": None, "output_tokens": 2, "complete": True, "model_call_attempted": True},
        {"input_tokens": None, "output_tokens": None, "complete": False, "model_call_attempted": False},
        {"input_tokens": 0, "output_tokens": None, "complete": False, "model_call_attempted": None},
        {"input_tokens": True, "output_tokens": 0, "complete": True, "model_call_attempted": True},
    ],
)
def test_usage_never_coerces_unknown_zero_or_boolean(payload):
    with pytest.raises(ValidationError):
        ResearchUsage.model_validate(payload)


@pytest.mark.parametrize("receipt", [usage(12, None, True), usage(None, 7, True), usage(None, None, None), usage(0, 0, False)])
def test_actual_failed_receipt_preserves_partial_unknown_and_exact_pk_without_task_text(claimed, receipt):
    (db, actor, run_id, _, _, _), lease = claimed
    statements, close = capture_sql(db)
    before = db.query(AIAuditEvent).count()
    try:
        pk = stage_terminal_receipt(db, run_id, lease, receipt, status="failed", error_code="WORKER_INTERRUPTED" if receipt["model_call_attempted"] is None else "TEST_FAILURE")
        checked = read_usage_event(db, run_id)
        assert checked["usage"] == receipt and checked["result_hash"] is None
        assert db.query(AIResearchCohortRunArtifact.usage_event_id).filter_by(run_id=run_id).scalar() == pk
        assert pk != db.query(AIResearchCohortRunArtifact.created_audit_event_id).filter_by(run_id=run_id).scalar()
    finally:
        close()
    assert not task_body_selects(statements)
    db.rollback()
    assert db.query(AIAuditEvent).count() == before
    assert db.get(AIRun, run_id).status == "running"


def test_queued_cancel_is_only_known_zero_unattempted_and_idempotent(configured):
    db, actor, run_id, _, values, _ = configured
    freeze_artifact(db, actor, run_id, values["case_id"])
    db.commit()
    with pytest.raises(HTTPException):
        stage_terminal_receipt(db, run_id, None, usage(None, None, None), status="cancelled")
    db.rollback()
    pk = stage_terminal_receipt(db, run_id, None, usage(0, 0, False), status="cancelled")
    assert stage_terminal_receipt(db, run_id, None, usage(0, 0, False), status="cancelled") == pk
    db.commit()
    assert read_usage_event(db, run_id)["usage"] == usage(0, 0, False)


def test_paid_failure_after_patient_research_withdrawal_keeps_usage_without_reading_clinical_task(claimed):
    (db, actor, run_id, _, values, case), lease = claimed
    full = case_current(db, actor, values["case_id"])
    authorization_id = full["snapshot"]["capture"]["patient_authorizations"][0]["identity"]["source_record_id"]
    review_registry_original(db, case["super_admin_user"], "authorization", authorization_id, {"expected_revision": 2, "basis_note": BASIS}, revoke=True)
    statements, close = capture_sql(db)
    try:
        stage_terminal_receipt(db, run_id, lease, usage(42, None, True), status="failed", error_code="RESEARCH_PERMISSION_CHANGED")
        db.commit()
        assert read_usage_event(db, run_id)["usage"] == usage(42, None, True)
    finally:
        close()
    assert not task_body_selects(statements)


@pytest.mark.parametrize("fault", ["usage_action", "usage_body", "terminal_header", "usage_fk"])
def test_terminal_usage_postwrite_trigger_faults_roll_back_all_header_audit_and_fk(claimed, fault):
    (db, _, run_id, _, _, _), lease = claimed
    before = db.query(AIAuditEvent).count()
    commands = {
        "usage_action": "UPDATE hoimsystem_ai_audit_event SET action='wrong' WHERE event_id=NEW.event_id;",
        "usage_body": "UPDATE hoimsystem_ai_audit_event SET detail_json='{}' WHERE event_id=NEW.event_id;",
        "terminal_header": "UPDATE hoimsystem_ai_run SET error_code='CHANGED' WHERE run_id=NEW.target;",
        "usage_fk": "UPDATE hoimsystem_ai_research_cohort_run_artifact SET usage_event_id=created_audit_event_id WHERE run_id=NEW.target;",
    }
    db.execute(text("CREATE TRIGGER research_usage_fault AFTER INSERT ON hoimsystem_ai_audit_event WHEN NEW.action='research.task.usage' BEGIN " + commands[fault] + " END"))
    db.commit()
    try:
        from sqlalchemy.exc import IntegrityError

        with pytest.raises((HTTPException, IntegrityError)):
            stage_terminal_receipt(db, run_id, lease, usage(2, None, True), status="failed", error_code="ORIGINAL")
        db.rollback()
        assert db.query(AIAuditEvent).count() == before
        assert db.get(AIRun, run_id).status == "running"
        assert db.get(AIResearchCohortRunArtifact, run_id).usage_event_id is None
    finally:
        db.rollback()
        db.execute(text("DROP TRIGGER research_usage_fault"))
        db.commit()


def test_stale_worker_lease_cannot_replace_any_usage(claimed):
    (db, _, run_id, _, _, _), _ = claimed
    before = db.query(AIAuditEvent).count()
    with pytest.raises(HTTPException):
        stage_terminal_receipt(db, run_id, str(uuid.uuid4()), usage(9, 1, True), status="failed", error_code="OLD_LEASE")
    assert db.query(AIAuditEvent).count() == before
