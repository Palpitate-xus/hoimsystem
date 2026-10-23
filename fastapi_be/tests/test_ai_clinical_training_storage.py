"""Actual staged Task SQL, exact receipts, source-first reads and rollback."""

import datetime as dt
import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import event, func, text

from app.ai import clinical_training_contract as c
from app.ai import clinical_training_practice as practice
from app.ai import clinical_training_reviews as reviews
from app.ai import clinical_training_storage as s
from app.ai.clinical_training_run_models import AITrainingRunArtifact, AITrainingRunResult
from app.ai.models import AIAuditEvent, AIFeatureConfig, AIPromptVersion, AIRun
from tests.test_ai_clinical_training_configuration import configured as configured
from tests.test_ai_clinical_training_configuration import selected
from tests.test_ai_clinical_training_contract import submission
from tests.test_ai_clinical_training_practice import practice_case as practice_case
from tests.test_ai_clinical_training_reference_sql import reference_case as reference_case
from tests.test_ai_clinical_training_registry import observe_bodies
from tests.test_ai_clinical_training_reviews import reviewed_case as reviewed_case


@pytest.fixture
def stored(configured):
    case, db = configured, configured["db"]
    case["provider"].api_key_env = ""
    db.commit()
    key = s.stage_run(db, case["actor"], selected(case))
    db.commit()
    try:
        yield case, key
    finally:
        db.rollback()
        db.query(AIFeatureConfig).filter_by(feature_key="clinical_training").delete()
        db.commit()


def counts(db):
    return {model.__tablename__: db.query(model).count() for model in (AIRun, AITrainingRunArtifact, AITrainingRunResult, AIAuditEvent)}


def assert_zero_bodies(columns):
    keys = ("private_json", "public_json", "references_json", "review_json", "content", "submission_json", "feedback_json", *s.ARTIFACT_TEXT, *s.RUN_TEXT)
    assert not any(name == key or name.endswith("_" + key) for name in columns for key in keys)


def test_actual_committed_queue_whole_source_raw_three_and_specific_create_receipt_readback(stored):
    case, key = stored
    db = case["db"]
    run, artifact, source, prompt, execution, choice = s.load_artifact(db, case["actor"], key, execution=True)
    assert run.status == "queued" and run.input_tokens == run.output_tokens == 0 and run.result_json == "{}"
    assert artifact.claim_event_id is artifact.claimed_at is artifact.lease_token is artifact.dispatch_event_id is artifact.usage_event_id is None
    assert source.source_id == choice.clinical_training_submission_id == case["submission"]["submission_id"]
    assert c.whole(source).encode() == artifact.source_json.encode() and source.feedback.matching_count == source.feedback.question_count == 2
    assert prompt["task_prompt"] and execution["feature_validation"]["current_validator"]["user_role"] == "super_admin"
    receipt = db.get(AIAuditEvent, artifact.created_audit_event_id)
    header = s.artifact_header(db, key)
    original = s._verify_created(db, header, s.run_header(db, key))
    assert receipt.action == s.CREATION_ACTION and receipt.target == key and receipt.actor_id == case["actor"].user_id
    assert receipt.detail_json == c.canonical_json(original)
    assert len({artifact.created_audit_event_id, artifact.lesson_creation_event_id, artifact.review_creation_event_id, artifact.submission_creation_event_id}) == 4
    for field, digest in zip(s.RAW_FIELDS, (artifact.input_hash, artifact.evidence_hash, artifact.metadata_hash), strict=True):
        assert len(getattr(run, field).encode()) <= 65535 and s.registry.raw_sha(getattr(run, field)) == digest
    assert "PRIVATE_REVIEWED_RATIONALE_SENTINEL" not in receipt.detail_json and "PRIVATE_REVIEWED_RATIONALE_SENTINEL" not in run.input_json


@pytest.mark.parametrize("fault", ["other_owner", "owner_role", "owner_epoch", "configured_role", "review_revoked", "lesson_revoked", "reference_retired", "reference_metadata", "reviewer_epoch", "wrong_specific_audit", "self_rehash_artifact", "immutable_run", "disabled_for_execution", "provider_revision", "config_revision", "validator_role"])
def test_actual_current_source_authority_and_original_technical_receipt_precede_all_bodies(stored, fault):
    case, key = stored
    db, actor = case["db"], case["actor"]
    execution = fault in {"disabled_for_execution", "provider_revision", "config_revision", "validator_role"}
    if fault == "other_owner":
        actor = case["author"]
    elif fault == "owner_role":
        db.execute(text("UPDATE hoimsystem_users SET user_role='admin' WHERE user_id=:key"), dict(key=actor.user_id))
    elif fault in {"owner_epoch", "reviewer_epoch"}:
        target = actor.user_id if fault == "owner_epoch" else case["reviewer"].user_id
        db.execute(text("UPDATE hoimsystem_users SET token_invalid_before=:clock WHERE user_id=:key"), dict(key=target, clock=dt.datetime.now(dt.UTC).replace(tzinfo=None)))
    elif fault == "configured_role":
        case["config"].allowed_roles_json = '["super_admin"]'
    elif fault == "review_revoked":
        reviews.revoke_review(db, case["author"], case["review"]["review_id"], dict(revision=1, reason="实际培训模型范围撤回"))
    elif fault == "lesson_revoked":
        s.registry.revoke_lesson(db, case["author"], case["lesson"]["lesson_id"], dict(revision=1, reason="实际培训来源撤回"))
    elif fault == "reference_retired":
        case["documents"][0].status = "retired"
    elif fault == "reference_metadata":
        case["documents"][0].title += " changed"
    elif fault == "wrong_specific_audit":
        unrelated = AIAuditEvent(actor_id=actor.user_id, action="synthetic.unrelated.actual.audit", target=key, detail_json="{}")
        db.add(unrelated)
        db.flush()
        db.execute(text("UPDATE hoimsystem_ai_training_run_artifact SET created_audit_event_id=:event WHERE run_id=:key"), dict(key=key, event=unrelated.event_id))
    elif fault == "self_rehash_artifact":
        # Actual header digest is changed without changing its original receipt;
        # refusal must occur before reading the altered full Source.
        db.execute(text("UPDATE hoimsystem_ai_training_run_artifact SET source_projection_hash=:digest WHERE run_id=:key"), dict(key=key, digest="0" * 64))
    elif fault == "immutable_run":
        db.execute(text("UPDATE hoimsystem_ai_run SET preview=1 WHERE run_id=:key"), dict(key=key))
    elif fault == "disabled_for_execution":
        case["config"].enabled = 0
    elif fault == "provider_revision":
        case["provider"].revision += 1
    elif fault == "config_revision":
        case["config"].revision += 1
    else:
        case["validator"].user_role = "admin"
    db.flush()
    columns, observer = observe_bodies(db)
    try:
        with pytest.raises(HTTPException) as error:
            s.load_artifact(db, actor, key, execution=execution)
        assert error.value.status_code in {403, 409}
    finally:
        event.remove(db.get_bind(), "after_cursor_execute", observer)
    assert_zero_bodies(columns)


def test_expired_artifact_primary_key_refresh_never_loads_any_body_before_revoked_source(stored):
    case, key = stored
    db = case["db"]
    artifact = db.get(AITrainingRunArtifact, key)
    db.expire(artifact)
    reviews.revoke_review(db, case["author"], case["review"]["review_id"], dict(revision=1, reason="明确当前课程处理撤回"))
    columns, observer = observe_bodies(db)
    try:
        with pytest.raises(HTTPException) as error:
            s.load_artifact(db, case["actor"], key)
        assert error.value.status_code == 403 and error.value.detail == "课程复核版本已经撤回"
    finally:
        event.remove(db.get_bind(), "after_cursor_execute", observer)
    assert_zero_bodies(columns)


def test_ordinary_read_keeps_authorized_frozen_history_when_model_disabled_but_execution_refuses(stored):
    case, key = stored
    db = case["db"]
    case["config"].enabled = 0
    db.flush()
    assert s.load_artifact(db, case["actor"], key)[0].status == "queued"
    with pytest.raises(HTTPException) as error:
        s.load_artifact(db, case["actor"], key, execution=True)
    assert error.value.status_code == 409


def test_actual_current_quota_counts_existing_rows_and_stages_no_partial_task_or_audit(stored):
    case, key = stored
    db = case["db"]
    used = db.query(func.count(AIRun.run_id)).filter_by(feature_key="clinical_training", requested_by=case["actor"].user_id).scalar()
    assert used > 0
    case["config"].daily_limit = used
    db.commit()
    before = counts(db)
    with pytest.raises(HTTPException) as error:
        s.stage_run(db, case["actor"], selected(case))
    assert error.value.status_code == 429 and counts(db) == before


@pytest.mark.parametrize("fault", ["reference", "owner", "config"])
def test_actual_post_artifact_insert_mutation_rolls_back_task_specific_audit_and_mutation(stored, fault):
    case, key = stored
    db = case["db"]
    before = counts(db)
    if fault == "reference":
        change = "UPDATE hoimsystem_ai_knowledge_document SET status='retired' WHERE document_id='" + case["documents"][0].document_id + "';"
    elif fault == "owner":
        change = "UPDATE hoimsystem_users SET user_role='admin' WHERE user_id=" + str(case["actor"].user_id) + ";"
    else:
        change = "UPDATE hoimsystem_ai_feature_config SET enabled=0 WHERE feature_key='clinical_training';"
    trigger = "training_after_task_insert_" + fault
    db.execute(text("CREATE TEMP TRIGGER " + trigger + " AFTER INSERT ON hoimsystem_ai_training_run_artifact BEGIN " + change + " END"))
    db.commit()
    try:
        with pytest.raises(HTTPException) as error:
            s.stage_run(db, case["actor"], selected(case))
        assert error.value.status_code in {403, 409} and counts(db) == before
        assert db.execute(text("SELECT enabled FROM hoimsystem_ai_feature_config WHERE feature_key='clinical_training'")).scalar_one() == 1
        assert db.execute(text("SELECT user_role FROM hoimsystem_users WHERE user_id=:key"), dict(key=case["actor"].user_id)).scalar_one() == "doctor"
        assert db.execute(text("SELECT status FROM hoimsystem_ai_knowledge_document WHERE document_id=:key"), dict(key=case["documents"][0].document_id)).scalar_one() == "published"
    finally:
        db.execute(text("DROP TRIGGER IF EXISTS " + trigger))
        db.commit()


def test_actual_uuid_prompt_and_own_super_preview_freeze_without_enabling_feature(stored):
    case, original_key = stored
    db = case["db"]
    ack = practice.submit_practice(db, case["author"], dict(review_id=case["review"]["review_id"], submission=submission(case["private"])))
    raw = "\ufeff明确自己的实际练习😀\r\n\x00  尾部  "
    prompt = AIPromptVersion(feature_key="clinical_training", version=1, task_prompt=raw, change_note="独立实际UUID版本", created_by=case["author"].user_id)
    db.add(prompt)
    db.flush()
    case["config"].active_prompt_id, case["config"].revision = prompt.prompt_id, 2
    case["config"].enabled, case["config"].validation_status = 0, "unreviewed"
    db.commit()
    key = s.stage_run(db, case["author"], dict(clinical_training_submission_id=ack["submission_id"], objective="review_supplied_material"), preview=True)
    db.commit()
    actual = s.load_artifact(db, case["author"], key, execution=True)
    assert key != original_key and actual[0].preview == 1 and actual[3]["prompt_id"] == prompt.prompt_id
    assert actual[3]["task_prompt"].encode() == raw.encode() and actual[4]["preview"] is True
    assert db.query(AIFeatureConfig.enabled).filter_by(feature_key="clinical_training").scalar() == 0
    assert len(uuid.UUID(prompt.prompt_id).bytes) == 16
