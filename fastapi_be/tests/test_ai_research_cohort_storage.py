"""Actual split-artifact SQL/authority/read order, not queue or worker tests."""

import copy
import json

import pytest
from fastapi import HTTPException
from sqlalchemy import event, text

from app.ai.models import AIAuditEvent, AIFeatureConfig, AIPromptVersion, AIProvider, AIRun
from app.ai.research_cohort_artifact_models import AIResearchCohortRunArtifact
from app.ai.research_cohort_cases import case_current
from app.ai.research_cohort_contract import canonical_json
from app.ai.research_cohort_registry import review_registry_original
from app.ai.research_cohort_sources import utcnow
from app.ai.research_cohort_storage import freeze_artifact, load_artifact
from app.models import User
from tests.test_ai_research_cohort_artifact_models import artifact_foreign_keys as artifact_foreign_keys  # noqa: F401
from tests.test_ai_research_cohort_artifact_models import storage_rows as storage_rows  # noqa: F401
from tests.test_ai_research_cohort_contract import BASIS
from tests.test_ai_research_cohort_sources import research_case as research_case  # noqa: F401


@pytest.fixture
def configured(storage_rows, research_case):
    db, run_id, source, values = storage_rows
    actor = db.get(User, values["requested_by"])
    provider = db.get(AIProvider, values["provider_id"])
    provider.enabled = provider.allows_patient_data = 1
    run = db.get(AIRun, run_id)
    run.status, run.lease_token = "queued", None
    config = db.get(AIFeatureConfig, "research_cohort")
    if config is None:
        config = AIFeatureConfig(feature_key="research_cohort", updated_by=actor.user_id)
        db.add(config)
    config.enabled, config.provider_id, config.active_prompt_id = 1, provider.provider_id, values["prompt_id"]
    config.allowed_roles_json, config.validation_status = '["admin","doctor"]', "validated"
    config.validation_note = BASIS
    config.validated_by, config.validated_at = research_case["super_admin_user"].user_id, utcnow()
    config.daily_limit, config.revision = 100, 1
    db.commit()
    return db, actor, run_id, source, values, research_case


def task_body_selects(statements):
    names = (
        "hoimsystem_ai_run.input_json",
        "hoimsystem_ai_run.evidence_json",
        "hoimsystem_ai_run.context_metadata_json",
        "hoimsystem_ai_research_cohort_run_artifact.source_json",
        "hoimsystem_ai_research_cohort_run_artifact.prompt_snapshot_json",
    )
    return [sql for sql in statements if sql.lstrip().lower().startswith("select") and any(name in sql.lower() for name in names)]


def capture_sql(db):
    statements = []

    def seen(conn, cursor, statement, params, context, many):
        statements.append(statement)

    event.listen(db.bind, "before_cursor_execute", seen)
    return statements, lambda: event.remove(db.bind, "before_cursor_execute", seen)


def test_actual_freeze_full_source_prompt_versions_short_raw3_specific_audit_and_no_commit(configured):
    db, actor, run_id, source, values, _ = configured
    prompt = db.get(AIPromptVersion, values["prompt_id"])
    prompt.task_prompt = "独立保存的完整自定义研究Task版本\ufeff\r\n🧪，不是默认Task字符串。"
    db.commit()
    before = db.query(AIAuditEvent).count()
    artifact = freeze_artifact(db, actor, run_id, values["case_id"], question="原问题\ufeff\r\n🧪")
    run, checked, case, same_source = load_artifact(db, actor, run_id, execution=True)
    assert checked.run_id == artifact.run_id and same_source == source and case["case_id"] == values["case_id"]
    assert artifact.source_json == canonical_json(source)
    assert "完整自定义研究Task版本" in artifact.prompt_snapshot_json
    assert "outcomes" not in run.input_json and "task_prompt" not in run.input_json
    assert all(len(getattr(run, key).encode()) <= 65535 for key in ("input_json", "evidence_json", "context_metadata_json"))
    assert artifact.usage_event_id is None
    assert db.query(AIAuditEvent).filter_by(event_id=artifact.created_audit_event_id).one().action == "research.task.artifact.create"
    # The helper has staged, never committed, the exact creation audit/artifact.
    db.rollback()
    assert db.query(AIResearchCohortRunArtifact).filter_by(run_id=run_id).count() == 0
    assert db.query(AIAuditEvent).count() == before


@pytest.mark.parametrize("who", ["ordinary", "super_audit"])
def test_withdrawn_patient_research_permission_denies_before_task_text_even_super(configured, who):
    db, actor, run_id, _, values, case = configured
    full = case_current(db, actor, values["case_id"])
    authorization_id = full["snapshot"]["capture"]["patient_authorizations"][0]["identity"]["source_record_id"]
    freeze_artifact(db, actor, run_id, values["case_id"])
    db.commit()
    review_registry_original(db, case["super_admin_user"], "authorization", authorization_id, {"expected_revision": 2, "basis_note": BASIS}, revoke=True)
    statements, close = capture_sql(db)
    try:
        with pytest.raises(HTTPException):
            load_artifact(db, actor if who == "ordinary" else case["super_admin_user"], run_id, audit_only=who == "super_audit")
    finally:
        close()
    assert not task_body_selects(statements)


def test_super_technical_identity_without_own_project_grant_cannot_read_artifact_text(configured):
    db, actor, run_id, _, values, case = configured
    freeze_artifact(db, actor, run_id, values["case_id"])
    db.commit()
    statements, close = capture_sql(db)
    try:
        with pytest.raises(HTTPException):
            load_artifact(db, case["super_admin_user"], run_id, audit_only=True)
    finally:
        close()
    assert not task_body_selects(statements)


@pytest.mark.parametrize("change", ["role", "token_epoch"])
def test_actual_stale_request_epoch_is_rejected_before_any_task_text(configured, change):
    db, actor, run_id, _, values, _ = configured
    freeze_artifact(db, actor, run_id, values["case_id"])
    db.commit()
    # Snapshot fields are already loaded before the real SQL change; the guard
    # must preserve that incoming request epoch before populate_existing.
    _ = actor.user_role, actor.token_invalid_before
    db.execute(text("UPDATE hoimsystem_users SET " + ("user_role='doctor'" if change == "role" else "token_invalid_before='2030-01-01 00:00:00'") + " WHERE user_id=:id"), {"id": actor.user_id})
    statements, close = capture_sql(db)
    try:
        with pytest.raises(HTTPException) as error:
            load_artifact(db, actor, run_id)
        assert error.value.status_code == 403
    finally:
        close()
        db.rollback()
    assert not task_body_selects(statements)


@pytest.mark.parametrize("fault", ["audit_action", "audit_detail", "source_body", "provider", "actor"])
def test_real_sql_postwrite_faults_rollback_exact_artifact_audit_and_run_without_new_business_writes(configured, fault):
    db, actor, run_id, _, values, _ = configured
    before = db.query(AIAuditEvent).count()
    initial = {key: getattr(db.get(AIRun, run_id), key) for key in ("input_json", "evidence_json", "context_metadata_json", "context_digest", "prompt_hash")}
    if fault == "audit_action":
        command = "UPDATE hoimsystem_ai_audit_event SET action='wrong_action' WHERE event_id=NEW.event_id;"
    elif fault == "audit_detail":
        command = "UPDATE hoimsystem_ai_audit_event SET detail_json='{}' WHERE event_id=NEW.event_id;"
    elif fault == "source_body":
        command = "UPDATE hoimsystem_medical_record SET symptom='已知原来源在具体回执后变化' WHERE patient_id=" + str(configured[5]["patient"].patient_id) + ";"
    elif fault == "provider":
        command = "UPDATE hoimsystem_ai_provider SET enabled=0 WHERE provider_id=" + str(values["provider_id"]) + ";"
    else:
        command = "UPDATE hoimsystem_users SET user_role='patient' WHERE user_id=NEW.actor_id;"
    db.execute(text("CREATE TRIGGER research_artifact_fault AFTER INSERT ON hoimsystem_ai_audit_event WHEN NEW.action='research.task.artifact.create' BEGIN " + command + " END"))
    db.commit()
    try:
        with pytest.raises(HTTPException):
            freeze_artifact(db, actor, run_id, values["case_id"])
        db.rollback()
        assert db.query(AIResearchCohortRunArtifact).filter_by(run_id=run_id).count() == 0
        assert db.query(AIAuditEvent).count() == before
        assert {key: getattr(db.get(AIRun, run_id), key) for key in initial} == initial
        assert db.get(User, values["requested_by"]).user_role == "admin"
        assert db.get(AIProvider, values["provider_id"]).enabled == 1
    finally:
        db.rollback()
        db.execute(text("DROP TRIGGER research_artifact_fault"))
        db.commit()


def test_altered_source_or_stripped_feature_cannot_downgrade_durable_artifact(configured):
    db, actor, run_id, source, values, _ = configured
    freeze_artifact(db, actor, run_id, values["case_id"])
    db.commit()
    original = db.get(AIRun, run_id).feature_key
    db.execute(text("UPDATE hoimsystem_ai_run SET feature_key='nursing_support' WHERE run_id=:id"), {"id": run_id})
    with pytest.raises(HTTPException) as error:
        load_artifact(db, actor, run_id)
    assert error.value.status_code == 409
    db.rollback()
    assert db.get(AIRun, run_id).feature_key == original
    # A compatible-size altered stored Source with its own hashes still cannot
    # replace the separately current, authorized Case publication.
    wrong = copy.deepcopy(source)
    wrong["privacy_basis"] = "not_the_declared_privacy_basis"
    db.execute(
        text("UPDATE hoimsystem_ai_research_cohort_run_artifact SET source_json=:body,source_bytes=:size WHERE run_id=:id"),
        {"body": canonical_json(wrong), "size": len(canonical_json(wrong).encode()), "id": run_id},
    )
    with pytest.raises(HTTPException):
        load_artifact(db, actor, run_id)
    db.rollback()


def test_packaged_version_zero_has_no_fabricated_prompt_foreign_key_or_governance_write(configured):
    db, actor, run_id, _, values, _ = configured
    config = db.get(AIFeatureConfig, "research_cohort")
    config.active_prompt_id = None
    db.commit()
    before = db.query(AIPromptVersion).count()
    artifact = freeze_artifact(db, actor, run_id, values["case_id"])
    db.commit()
    run, actual, _, _ = load_artifact(db, actor, run_id, execution=True)
    prompt = json.loads(actual.prompt_snapshot_json)
    assert artifact.prompt_id is None and artifact.prompt_version == run.prompt_version == 0
    assert prompt["origin"] == "packaged_catalog" and prompt["prompt_id"] is None and prompt["prompt_version"] == 0
    assert prompt["native_task_version"] == "research_cohort_questions_task_v1" and prompt["catalog_version"]
    assert db.query(AIPromptVersion).count() == before


def test_database_version_origin_uses_actual_fk_and_cannot_turn_into_packaged_by_self_hash(configured):
    db, actor, run_id, _, values, _ = configured
    artifact = freeze_artifact(db, actor, run_id, values["case_id"])
    db.commit()
    original = json.loads(artifact.prompt_snapshot_json)
    assert original["origin"] == "database_version" and original["prompt_id"] == values["prompt_id"]
    assert original["prompt_version"] == values["prompt_version"] > 0
    wrong = {**original, "origin": "packaged_catalog"}
    from app.ai.research_cohort_draft import digest

    db.execute(
        text("UPDATE hoimsystem_ai_research_cohort_run_artifact SET prompt_snapshot_json=:body,prompt_snapshot_hash=:hash WHERE run_id=:id"),
        {"body": canonical_json(wrong), "hash": digest(wrong), "id": run_id},
    )
    with pytest.raises(HTTPException) as error:
        load_artifact(db, actor, run_id)
    assert error.value.status_code == 409
    db.rollback()


def test_super_frozen_audit_requires_own_research_grants_but_not_malformed_live_feature_roles(configured):
    from app.ai.research_cohort_cases import create_case, preview_input, review_case
    from app.ai.research_cohort_registry import create_registry_original
    from tests.test_ai_research_cohort_registry import acl_request, publish

    db, actor, run_id, _, values, case = configured
    previous = case_current(db, actor, values["case_id"])
    proof = previous["snapshot"]["capture"]["scope_original"]
    scope = {**proof["identity"], "content_hash": proof["content_hash"], "governance_hash": proof["governance_hash"]}
    request = {**acl_request(case, scope), "user_id": case["super_admin_user"].user_id}
    publish(db, case, "acl", create_registry_original(db, case["super_admin_user"], "acl", request))
    # A new ACL is a new root: capture a genuinely fresh Case containing it.
    # Never forge can_read/current flags on the original stale Case.
    preview = preview_input(db, actor, previous["snapshot"]["request"])
    fresh = create_case(db, actor, {"request": preview["request"], "expected_collection_digest": preview["expected_collection_digest"], "basis_note": BASIS})
    review_case(db, case["super_admin_user"], fresh["case_id"], {"expected_revision": 1, "decision": "publish", "basis_note": BASIS})
    freeze_artifact(db, actor, run_id, fresh["case_id"])
    db.commit()
    review_case(db, case["super_admin_user"], fresh["case_id"], {"expected_revision": 2, "basis_note": BASIS}, revoke=True)
    db.get(AIFeatureConfig, "research_cohort").allowed_roles_json = "malformed"
    db.commit()
    assert load_artifact(db, case["super_admin_user"], run_id, audit_only=True)[3]["source_id"].startswith("research_cohort:")
    statements, close = capture_sql(db)
    try:
        with pytest.raises(HTTPException):
            load_artifact(db, actor, run_id)
    finally:
        close()
    assert not task_body_selects(statements)
    with pytest.raises(HTTPException):
        load_artifact(db, case["super_admin_user"], run_id, execution=True)


def test_packaged_downgrade_refuses_before_any_ddl_or_row_change(configured):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    from tests.test_ai_research_cohort_prompt_origin_migration import migration

    db, actor, run_id, _, values, _ = configured
    db.get(AIFeatureConfig, "research_cohort").active_prompt_id = None
    db.commit()
    freeze_artifact(db, actor, run_id, values["case_id"])
    db.commit()
    before = db.execute(text("SELECT sql FROM sqlite_master WHERE name='hoimsystem_ai_research_cohort_run_artifact'")).scalar_one()
    rows = db.execute(text("SELECT * FROM hoimsystem_ai_research_cohort_run_artifact WHERE run_id=:id"), {"id": run_id}).all()
    change = migration("20261021_research_prompt_origin.py")
    change.op = Operations(MigrationContext.configure(db.connection()))
    with pytest.raises(RuntimeError, match="cannot be represented"):
        change.downgrade()
    assert db.execute(text("SELECT sql FROM sqlite_master WHERE name='hoimsystem_ai_research_cohort_run_artifact'")).scalar_one() == before
    assert db.execute(text("SELECT * FROM hoimsystem_ai_research_cohort_run_artifact WHERE run_id=:id"), {"id": run_id}).all() == rows


def test_prompt_origin_sql_rejects_null_positive_and_nonnull_zero_versions(configured):
    from sqlalchemy.exc import IntegrityError

    db, actor, run_id, _, values, _ = configured
    freeze_artifact(db, actor, run_id, values["case_id"])
    db.commit()
    for command in ("prompt_id=NULL", "prompt_version=0"):
        with pytest.raises(IntegrityError):
            db.execute(text("UPDATE hoimsystem_ai_research_cohort_run_artifact SET " + command + " WHERE run_id=:id"), {"id": run_id})
        db.rollback()
    assert load_artifact(db, actor, run_id)[1].prompt_id == values["prompt_id"]


@pytest.mark.parametrize("change", ["role", "token_epoch"])
def test_worker_id_only_actor_cannot_execute_queued_artifact_after_creation_epoch_change(configured, change):
    from types import SimpleNamespace

    db, actor, run_id, _, values, _ = configured
    identifier = actor.user_id
    freeze_artifact(db, actor, run_id, values["case_id"])
    db.commit()
    db.execute(text("UPDATE hoimsystem_users SET " + ("user_role='doctor'" if change == "role" else "token_invalid_before='2030-01-01 00:00:00'") + " WHERE user_id=:id"), {"id": identifier})
    db.commit()
    # A worker resolves only the actual requester PK. It must compare against
    # the creation epoch stored in the artifact, not just today's allowed role.
    with pytest.raises(HTTPException) as error:
        load_artifact(db, SimpleNamespace(user_id=identifier), run_id, execution=True)
    assert error.value.status_code == 409
    # A separately authorized current session may still inspect its old task;
    # the frozen creation epoch blocks dispatch, not all historical reading.
    assert load_artifact(db, SimpleNamespace(user_id=identifier), run_id, execution=False)[0].run_id == run_id
