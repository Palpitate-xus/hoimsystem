"""Current configuration/quota/selection and split clinical versus technical reads."""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import func, text

from app.ai.models import AIAuditEvent, AIFeatureConfig, AIProvider, AIRun
from app.ai.research_cohort_artifact_models import AIResearchCohortRunArtifact
from app.ai.research_cohort_cases import case_current
from app.ai.research_cohort_contract import canonical_json
from app.ai.research_cohort_registry import review_registry_original
from app.ai.research_cohort_runtime import create_research_run, describe_research_run, read_research_part, selection
from tests.test_ai_research_cohort_contract import BASIS
from tests.test_ai_research_cohort_execution import runtime_case as runtime_case  # noqa: F401
from tests.test_ai_research_cohort_storage import artifact_foreign_keys as artifact_foreign_keys  # noqa: F401
from tests.test_ai_research_cohort_storage import capture_sql, task_body_selects
from tests.test_ai_research_cohort_storage import configured as configured  # noqa: F401
from tests.test_ai_research_cohort_storage import research_case as research_case  # noqa: F401
from tests.test_ai_research_cohort_storage import storage_rows as storage_rows  # noqa: F401


@pytest.mark.parametrize(
    "value",
    [
        {},
        {"research_cohort_case_id": "not-a-uuid"},
        {"research_cohort_case_id": None},
        {"research_cohort_case_id": "00000000-0000-0000-0000-000000000001", "patient_id": 1},
        {"research_cohort_case_id": "00000000-0000-0000-0000-000000000001", "encounter_ref": "foreign"},
        {"research_cohort_case_id": "00000000-0000-0000-0000-000000000001", "cohort_case_id": "foreign"},
        {"research_cohort_case_id": "00000000-0000-0000-0000-000000000001", "question": "x" * 2001},
        {"research_cohort_case_id": "00000000-0000-0000-0000-000000000001", "question": "\ud800"},
    ],
)
def test_selection_rejects_missing_noncanonical_foreign_refs_and_whole_scalar_overflow(value):
    with pytest.raises(HTTPException) as error:
        selection(value)
    assert error.value.status_code == 422


@pytest.mark.parametrize("change", ["disabled", "roles", "credentials", "quota"])
def test_create_current_preflight_failure_never_stages_a_run_or_artifact_audit(runtime_case, change):
    case, db = runtime_case, runtime_case["db"]
    config = db.get(AIFeatureConfig, "research_cohort")
    if change == "disabled":
        config.enabled = 0
    elif change == "roles":
        config.allowed_roles_json = "malformed"
    elif change == "credentials":
        db.get(AIProvider, config.provider_id).api_key_env = "SYNTHETIC_RESEARCH_TEST_MISSING_SECRET_1A9E"
    else:
        used = db.query(func.count(AIRun.run_id)).filter_by(feature_key="research_cohort", requested_by=case["actor_id"]).scalar()
        assert used >= 1
        config.daily_limit = used
    db.commit()
    before = db.query(AIRun).count(), db.query(AIAuditEvent).count(), db.query(AIResearchCohortRunArtifact).count()
    with pytest.raises(HTTPException):
        create_research_run(db, case["actor"], {"research_cohort_case_id": case["case_id"]})
    assert (db.query(AIRun).count(), db.query(AIAuditEvent).count(), db.query(AIResearchCohortRunArtifact).count()) == before


def test_super_technical_role_does_not_supply_project_permission_and_ordinary_cannot_preview(runtime_case):
    case, db = runtime_case, runtime_case["db"]
    before = db.query(AIRun).count()
    with pytest.raises(HTTPException):
        create_research_run(db, case["identities"]["super_admin_user"], {"research_cohort_case_id": case["case_id"]}, preview=True)
    with pytest.raises(HTTPException):
        create_research_run(db, case["actor"], {"research_cohort_case_id": case["case_id"]}, preview=True)
    assert db.query(AIRun).count() == before


def test_created_short_metadata_split_source_scope_task_keep_question_and_patient_body_out_of_metadata(runtime_case):
    case, db = runtime_case, runtime_case["db"]
    question = "仅院内本次问题，含不应进入技术目录的直接标识字面。"
    run_id = create_research_run(db, case["actor"], {"research_cohort_case_id": case["case_id"], "question": question})
    short = describe_research_run(db, case["actor"], run_id)
    assert short["split_artifacts"] and short["clinical_parts_available"] and short["usage"]["model_call_attempted"] is False
    assert question not in canonical_json(short) and "否认胸痛" not in canonical_json(short)
    assert read_research_part(db, case["actor"], run_id, "source") == case["source"]
    scope = read_research_part(db, case["actor"], run_id, "scope")
    assert scope["case_id"] == case["case_id"]
    raw = read_research_part(db, case["actor"], run_id, "task")
    assert question in raw["input_json"] and "outcomes" not in raw["input_json"]
    assert all(len(raw[key].encode("utf-8")) <= 65535 for key in ("input_json", "evidence_json", "context_metadata_json"))


@pytest.mark.parametrize("who", ["ordinary", "super"])
def test_withdrawal_allows_only_opaque_technical_metadata_and_never_reads_task_text(runtime_case, who):
    case, db = runtime_case, runtime_case["db"]
    full = case_current(db, case["actor"], case["case_id"])
    authorization = full["snapshot"]["capture"]["patient_authorizations"][0]["identity"]["source_record_id"]
    run_id = create_research_run(db, case["actor"], {"research_cohort_case_id": case["case_id"], "question": "私有问题原文"})
    review_registry_original(db, case["identities"]["super_admin_user"], "authorization", authorization, {"expected_revision": 2, "basis_note": BASIS}, revoke=True)
    actor = SimpleNamespace(user_id=case["actor_id"] if who == "ordinary" else case["identities"]["super_admin_user"].user_id)
    statements, close = capture_sql(db)
    try:
        short = describe_research_run(db, actor, run_id, audit_only=who == "super")
        assert not short["clinical_parts_available"] and short["binding"] is None and short["protected_hashes_are_opaque"]
        assert "私有问题原文" not in canonical_json(short) and "否认胸痛" not in canonical_json(short)
        for part in ("source", "scope", "task", "result"):
            with pytest.raises(HTTPException):
                read_research_part(db, actor, run_id, part, audit_only=who == "super")
    finally:
        close()
    assert not task_body_selects(statements)


def test_real_postwrite_quota_phantom_trigger_rolls_back_new_run_artifact_and_specific_audit(runtime_case):
    case, db = runtime_case, runtime_case["db"]
    before = db.query(AIRun).count(), db.query(AIResearchCohortRunArtifact).count(), db.query(AIAuditEvent).count()
    db.execute(
        text(
            "CREATE TRIGGER research_quota_fault AFTER INSERT ON hoimsystem_ai_research_cohort_run_artifact BEGIN INSERT INTO hoimsystem_ai_run(run_id,feature_key,provider_id,provider_revision,prompt_version,prompt_hash,context_digest,requested_by,status,preview,input_json,result_json,evidence_json,context_metadata_json,input_tokens,output_tokens,create_time) SELECT lower(hex(randomblob(16))),'research_cohort',provider_id,provider_revision,prompt_version,prompt_hash,context_digest,requested_by,'queued',0,'{}','{}','[]','{}',0,0,create_time FROM hoimsystem_ai_run WHERE run_id=NEW.run_id; END"
        )
    )
    db.commit()
    try:
        with pytest.raises(HTTPException):
            create_research_run(db, case["actor"], {"research_cohort_case_id": case["case_id"]})
        assert (db.query(AIRun).count(), db.query(AIResearchCohortRunArtifact).count(), db.query(AIAuditEvent).count()) == before
    finally:
        db.rollback()
        db.execute(text("DROP TRIGGER research_quota_fault"))
        db.commit()
