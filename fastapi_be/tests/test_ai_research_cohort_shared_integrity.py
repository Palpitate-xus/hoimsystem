"""Current Source and exact audit headers must precede private Task/Result TEXT."""

import pytest
from fastapi import HTTPException
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError

from app.ai.models import AIAuditEvent, AIRun
from app.ai.research_cohort_artifact_models import AIResearchCohortRunArtifact, AIResearchCohortRunResult
from app.ai.research_cohort_receipts import usage
from app.ai.research_cohort_result_storage import load_result, stage_result
from app.ai.research_cohort_storage import freeze_artifact, load_artifact
from tests.test_ai_research_cohort_result_storage import claimed as claimed  # noqa: F401
from tests.test_ai_research_cohort_result_storage import draft_for
from tests.test_ai_research_cohort_storage import artifact_foreign_keys as artifact_foreign_keys  # noqa: F401
from tests.test_ai_research_cohort_storage import capture_sql, task_body_selects
from tests.test_ai_research_cohort_storage import configured as configured  # noqa: F401
from tests.test_ai_research_cohort_storage import research_case as research_case  # noqa: F401
from tests.test_ai_research_cohort_storage import storage_rows as storage_rows  # noqa: F401


@pytest.mark.parametrize("fault", ["feature", "run_owner", "provider_revision", "source_hash", "binding_hash", "source_bytes", "creation_receipt"])
def test_changed_short_headers_and_creation_receipt_reject_before_private_task_text(configured, fault):
    db, actor, run_id, _, values, case = configured
    artifact = freeze_artifact(db, actor, run_id, values["case_id"], question="完整原问题\ufeff\r\n🧪")
    db.commit()
    if fault in {"feature", "run_owner", "provider_revision"}:
        model, key, identifier = AIRun, "run_id", run_id
        field = {"feature": "feature_key", "run_owner": "requested_by", "provider_revision": "provider_revision"}[fault]
        before = db.query(getattr(model, field)).filter_by(run_id=run_id).scalar()
        changed = "patient_summary" if fault == "feature" else case["super_admin_user"].user_id if fault == "run_owner" else before + 1
    elif fault == "creation_receipt":
        model, key, identifier, field = AIAuditEvent, "event_id", artifact.created_audit_event_id, "detail_json"
        before, changed = db.query(AIAuditEvent.detail_json).filter_by(event_id=identifier).scalar(), '{"corrupt":true}'
    else:
        model, key, identifier = AIResearchCohortRunArtifact, "run_id", run_id
        field = {"source_hash": "source_projection_hash", "binding_hash": "source_binding_hash", "source_bytes": "source_bytes"}[fault]
        before = db.query(getattr(model, field)).filter_by(run_id=run_id).scalar()
        changed = before - 1 if fault == "source_bytes" else "0" * 64
    try:
        if fault == "source_bytes":
            with pytest.raises(IntegrityError, match="ck_rcr_artifact_exact_bytes"):
                db.execute(update(model).where(getattr(model, key) == identifier).values({field: changed}).execution_options(synchronize_session=False))
            db.rollback()
            assert db.query(getattr(model, field)).filter(getattr(model, key) == identifier).scalar() == before
            return
        db.execute(update(model).where(getattr(model, key) == identifier).values({field: changed}).execution_options(synchronize_session=False))
        db.commit()
        db.expire_all()
        statements, close = capture_sql(db)
        try:
            with pytest.raises(HTTPException) as denied:
                load_artifact(db, actor, run_id)
        finally:
            close()
        assert denied.value.status_code == 409
        assert task_body_selects(statements) == []
    finally:
        db.rollback()
        db.execute(update(model).where(getattr(model, key) == identifier).values({field: before}).execution_options(synchronize_session=False))
        db.commit()


@pytest.mark.parametrize("fault", ["binding_hash", "content_hash", "accept_receipt"])
def test_accepted_result_parent_and_specific_receipt_reject_before_result_text(claimed, fault):
    (db, actor, run_id, source, _, _), lease = claimed
    row, _ = stage_result(db, actor, run_id, lease, draft_for(source), usage(12, None, True))
    db.commit()
    if fault == "accept_receipt":
        model, key, identifier, field = AIAuditEvent, "event_id", row.accept_audit_event_id, "detail_json"
        before, changed = db.query(AIAuditEvent.detail_json).filter_by(event_id=identifier).scalar(), '{"corrupt":true}'
    else:
        model, key, identifier = AIResearchCohortRunResult, "run_id", run_id
        field = "source_binding_hash" if fault == "binding_hash" else "content_hash"
        before, changed = db.query(getattr(model, field)).filter_by(run_id=run_id).scalar(), "0" * 64
    try:
        db.execute(update(model).where(getattr(model, key) == identifier).values({field: changed}).execution_options(synchronize_session=False))
        db.commit()
        db.expire_all()
        statements, close = capture_sql(db)
        try:
            with pytest.raises(HTTPException) as denied:
                load_result(db, actor, run_id)
        finally:
            close()
        assert denied.value.status_code == 409
        assert not any("hoimsystem_ai_research_cohort_run_result.result_json" in sql.lower() for sql in statements)
    finally:
        db.rollback()
        db.execute(update(model).where(getattr(model, key) == identifier).values({field: before}).execution_options(synchronize_session=False))
        db.commit()
