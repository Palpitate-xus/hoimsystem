"""Real governed Source -> lease -> whole accepted result, never a worker claim."""

import pytest
from fastapi import HTTPException
from sqlalchemy import text

from app.ai.models import AIAuditEvent, AIRun
from app.ai.research_cohort_artifact_models import AIResearchCohortRunArtifact, AIResearchCohortRunResult
from app.ai.research_cohort_cases import case_current
from app.ai.research_cohort_draft import COVERAGE, digest
from app.ai.research_cohort_receipts import read_usage_event, stage_terminal_receipt, usage
from app.ai.research_cohort_registry import review_registry_original
from app.ai.research_cohort_result_storage import load_result, stage_result
from tests.test_ai_research_cohort_contract import BASIS
from tests.test_ai_research_cohort_receipts import claimed as claimed  # noqa: F401
from tests.test_ai_research_cohort_storage import artifact_foreign_keys as artifact_foreign_keys  # noqa: F401
from tests.test_ai_research_cohort_storage import capture_sql, task_body_selects
from tests.test_ai_research_cohort_storage import configured as configured  # noqa: F401
from tests.test_ai_research_cohort_storage import research_case as research_case  # noqa: F401
from tests.test_ai_research_cohort_storage import storage_rows as storage_rows  # noqa: F401


def draft_for(source):
    return {"schema_version": "research_cohort_questions_v1", "research_source_id": source["source_id"], "source_projection_hash": digest(source), "coverage": COVERAGE, "questions": []}


@pytest.mark.parametrize("receipt", [usage(21, 8, True), usage(21, None, True), usage(None, None, True)])
def test_complete_result_nullable_actual_usage_three_distinct_audit_keys_and_rollback(claimed, receipt):
    (db, actor, run_id, source, _, _), lease = claimed
    before = db.query(AIAuditEvent).count()
    row, value = stage_result(db, actor, run_id, lease, draft_for(source), receipt, latency_ms=17)
    own, same = load_result(db, actor, run_id)
    artifact = db.get(AIResearchCohortRunArtifact, run_id)
    assert own.run_id == row.run_id and same == value and value["deterministic_evaluation"]["counts"] == source["counts"]
    assert len({artifact.created_audit_event_id, artifact.usage_event_id, row.accept_audit_event_id}) == 3
    assert read_usage_event(db, run_id)["usage"] == receipt
    assert "question_draft" not in db.get(AIRun, run_id).result_json
    assert row.result_bytes == len(row.result_json.encode("utf-8"))
    db.rollback()
    assert db.query(AIAuditEvent).count() == before
    assert db.query(AIResearchCohortRunResult).filter_by(run_id=run_id).count() == 0
    assert db.get(AIRun, run_id).status == "running"


def test_technical_success_receipt_cannot_manufacture_a_missing_result(claimed):
    (db, _, run_id, _, _, _), lease = claimed
    before = db.query(AIAuditEvent).count()
    with pytest.raises(HTTPException):
        stage_terminal_receipt(db, run_id, lease, usage(1, 1, True), status="succeeded", result_hash="1" * 64)
    assert db.query(AIAuditEvent).count() == before
    assert db.get(AIRun, run_id).status == "running"


@pytest.mark.parametrize("who", ["ordinary", "super_audit"])
def test_withdrawal_blocks_result_text_before_any_private_run_or_result_select(claimed, who):
    (db, actor, run_id, source, values, case), lease = claimed
    full = case_current(db, actor, values["case_id"])
    authorization_id = full["snapshot"]["capture"]["patient_authorizations"][0]["identity"]["source_record_id"]
    stage_result(db, actor, run_id, lease, draft_for(source), usage(12, None, True))
    db.commit()
    review_registry_original(db, case["super_admin_user"], "authorization", authorization_id, {"expected_revision": 2, "basis_note": BASIS}, revoke=True)
    statements, close = capture_sql(db)
    try:
        with pytest.raises(HTTPException):
            load_result(db, actor if who == "ordinary" else case["super_admin_user"], run_id, audit_only=who == "super_audit")
    finally:
        close()
    assert not task_body_selects(statements)
    assert not any("hoimsystem_ai_research_cohort_run_result.result_json" in sql.lower() for sql in statements)


@pytest.mark.parametrize("fault", ["accept_audit", "result_body", "source_body", "provider", "run_lease", "usage_audit"])
def test_actual_accept_postwrite_faults_roll_back_result_usage_audits_and_terminal_header(claimed, fault):
    (db, actor, run_id, source, values, case), lease = claimed
    before = db.query(AIAuditEvent).count()
    if fault == "accept_audit":
        table, condition, command = "hoimsystem_ai_audit_event", "NEW.action='research.task.result.accept'", "UPDATE hoimsystem_ai_audit_event SET action='wrong_accept' WHERE event_id=NEW.event_id;"
    elif fault == "source_body":
        table, condition, command = (
            "hoimsystem_ai_audit_event",
            "NEW.action='research.task.result.accept'",
            "UPDATE hoimsystem_medical_record SET symptom='资料已在结果写入时变化' WHERE patient_id=" + str(case["patient"].patient_id) + ";",
        )
    elif fault == "provider":
        table, condition, command = (
            "hoimsystem_ai_audit_event",
            "NEW.action='research.task.result.accept'",
            "UPDATE hoimsystem_ai_provider SET enabled=0 WHERE provider_id=" + str(values["provider_id"]) + ";",
        )
    elif fault == "run_lease":
        table, condition, command = "hoimsystem_ai_audit_event", "NEW.action='research.task.result.accept'", "UPDATE hoimsystem_ai_run SET lease_token=NULL WHERE run_id=NEW.target;"
    elif fault == "usage_audit":
        table, condition, command = "hoimsystem_ai_audit_event", "NEW.action='research.task.usage'", "UPDATE hoimsystem_ai_audit_event SET detail_json='{}' WHERE event_id=NEW.event_id;"
    else:
        table, condition, command = "hoimsystem_ai_research_cohort_run_result", "1=1", "UPDATE hoimsystem_ai_research_cohort_run_result SET result_json='{}',result_bytes=2 WHERE run_id=NEW.run_id;"
    db.execute(text("CREATE TRIGGER research_result_fault AFTER INSERT ON " + table + " WHEN " + condition + " BEGIN " + command + " END"))
    db.commit()
    try:
        with pytest.raises(HTTPException):
            stage_result(db, actor, run_id, lease, draft_for(source), usage(17, None, True))
        db.rollback()
        assert db.query(AIAuditEvent).count() == before
        assert db.query(AIResearchCohortRunResult).filter_by(run_id=run_id).count() == 0
        assert db.get(AIRun, run_id).status == "running" and db.get(AIRun, run_id).lease_token == lease
        assert db.get(AIResearchCohortRunArtifact, run_id).usage_event_id is None
    finally:
        db.rollback()
        db.execute(text("DROP TRIGGER research_result_fault"))
        db.commit()


def test_server_owned_counts_cannot_be_replaced_by_model_and_source_id_cannot_change(claimed):
    (db, actor, run_id, source, _, _), lease = claimed
    wrong = {**draft_for(source), "deterministic_evaluation": {"counts": {"recorded_true": 999}}}
    before = db.query(AIAuditEvent).count()
    with pytest.raises(HTTPException):
        stage_result(db, actor, run_id, lease, wrong, usage(7, 2, True))
    assert db.query(AIAuditEvent).count() == before
    assert db.query(AIResearchCohortRunResult).filter_by(run_id=run_id).count() == 0
