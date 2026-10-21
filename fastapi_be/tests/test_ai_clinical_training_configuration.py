"""Actual current model permission/config/UUID Prompt before protected bodies."""

import datetime as dt
import uuid
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import event, text

from app.ai import clinical_training_configuration as cfg
from app.ai import clinical_training_contract as c
from app.ai import clinical_training_practice as practice
from app.ai import clinical_training_reviews as reviews
from app.ai.models import AIFeatureConfig, AIPromptVersion, AIProvider, AIRun
from app.config import settings
from app.models import User
from tests.test_ai_clinical_training_contract import submission
from tests.test_ai_clinical_training_practice import practice_case as practice_case
from tests.test_ai_clinical_training_reference_sql import reference_case as reference_case
from tests.test_ai_clinical_training_registry import observe_bodies
from tests.test_ai_clinical_training_reviews import proposal
from tests.test_ai_clinical_training_reviews import reviewed_case as reviewed_case


@pytest.fixture
def configured(practice_case, monkeypatch):
    db, author, reviewer, documents, lesson, old_review, private, actor = practice_case
    review = reviews.review_lesson(db, reviewer, lesson["lesson_id"], proposal(lesson, model_processing_allowed=True))
    ack = practice.submit_practice(db, actor, dict(review_id=review["review_id"], submission=submission(private)))
    validator = User(username="training-model-validator-" + uuid.uuid4().hex, password="synthetic-only", user_role="super_admin")
    db.add(validator)
    db.flush()
    provider = AIProvider(name="training-model-" + uuid.uuid4().hex, kind="chat", api_base="http://127.0.0.1:1/v1", model="synthetic-text-model", api_key_env="PRIVATE_CREDENTIAL_REFERENCE_SENTINEL", enabled=1, allows_patient_data=0, temperature=Decimal("0.125"), created_by=author.user_id)
    db.add(provider)
    db.flush()
    config = AIFeatureConfig(feature_key="clinical_training", enabled=1, provider_id=provider.provider_id, allowed_roles_json='["doctor","super_admin"]', validation_status="validated", validation_note="明确合成教学反馈范围声明，未代表真实医学或资质验证", validated_by=validator.user_id, validated_at=dt.datetime.now(dt.UTC).replace(tzinfo=None, microsecond=0), daily_limit=100, revision=1, updated_by=author.user_id)
    db.add(config)
    # The base fixture commits the reviewed local course. Keep this case's
    # additional model grant, submission and unique feature configuration in
    # its own transaction; reference_case rolls them back after every test.
    db.flush()
    monkeypatch.setattr(settings, "AI_PROVIDER_ALLOWED_HOSTS", "127.0.0.1")
    return dict(base=practice_case, db=db, actor=actor, author=author, reviewer=reviewer, validator=validator, documents=documents, lesson=lesson, review=review, submission=ack, provider=provider, config=config, private=private)


def selected(case):
    return dict(clinical_training_submission_id=case["submission"]["submission_id"], objective="explain_practice_feedback")


def assert_zero_bodies(columns):
    assert not any(name == key or name.endswith("_" + key) for name in columns for key in ("private_json", "public_json", "references_json", "review_json", "content", "submission_json", "feedback_json", "source_json"))


@pytest.mark.parametrize("protocol", ["chat", "responses"])
def test_actual_current_source_permission_fixed_feedback_config_and_precise_decimal_context(configured, protocol):
    case = configured
    case["provider"].kind = protocol
    case["db"].flush()
    context = cfg.prepare_context(case["db"], case["actor"], selected(case))
    assert context.source.source_id == case["submission"]["submission_id"]
    assert context.source.feedback.matching_count == context.source.feedback.question_count == 2
    assert context.execution["provider_snapshot"]["kind"] == protocol and context.execution["provider_snapshot"]["temperature_decimal"] == "0.125"
    assert context.prompt["prompt_id"] is None and context.prompt["prompt_version"] == 0 and context.prompt["origin"] == "packaged_task"
    assert context.binding()["submission_creation_event_id"] == case["submission"]["creation_event_id"]
    assert context.binding()["review_creation_event_id"] == case["review"]["creation_event_id"]
    assert context.binding()["lesson_creation_event_id"] == case["lesson"]["creation_event_id"]
    assert context.binding()["feedback_hash"] == c.content_hash(context.source.feedback)
    assert all(key not in c.canonical_json([context.prompt, context.execution, context.source.model_dump()]) for key in ("PRIVATE_CREDENTIAL_REFERENCE_SENTINEL", "api_key_env", "api_key_encrypted"))


@pytest.mark.parametrize("fault", ["other_owner", "disabled", "unvalidated", "validator_role", "validator_epoch", "provider_disabled", "provider_kind", "provider_url", "roles", "bad_roles", "wrong_prompt_feature", "prompt_too_large", "withdrawn_review", "reference_changed", "owner_epoch", "model_permission"])
def test_current_source_role_model_permission_and_configuration_loss_precedes_all_protected_bodies(configured, fault):
    case, db = configured, configured["db"]
    actor, choice = case["actor"], selected(case)
    if fault == "other_owner":
        actor = case["author"]
    elif fault == "disabled":
        case["config"].enabled = 0
    elif fault == "unvalidated":
        case["config"].validation_status = "unreviewed"
    elif fault == "validator_role":
        case["validator"].user_role = "admin"
    elif fault == "validator_epoch":
        case["validator"].token_invalid_before = dt.datetime.now(dt.UTC).replace(tzinfo=None) + dt.timedelta(seconds=1)
    elif fault == "provider_disabled":
        case["provider"].enabled = 0
    elif fault == "provider_kind":
        case["provider"].kind = "vision"
    elif fault == "provider_url":
        case["provider"].api_base = "https://not-permitted.invalid/v1"
    elif fault == "roles":
        case["config"].allowed_roles_json = '["super_admin"]'
    elif fault == "bad_roles":
        case["config"].allowed_roles_json = '["doctor","doctor"]'
    elif fault in {"wrong_prompt_feature", "prompt_too_large"}:
        prompt = AIPromptVersion(feature_key="patient_summary" if fault == "wrong_prompt_feature" else "clinical_training", version=1, task_prompt="x" * 65536 if fault == "prompt_too_large" else "synthetic", change_note="synthetic-only", created_by=case["author"].user_id)
        db.add(prompt)
        db.flush()
        case["config"].active_prompt_id = prompt.prompt_id
    elif fault == "withdrawn_review":
        reviews.revoke_review(db, case["author"], case["review"]["review_id"], dict(revision=1, reason="明确受审课程模型范围撤回"))
    elif fault == "reference_changed":
        case["documents"][0].title += " changed"
    elif fault == "owner_epoch":
        db.execute(text("UPDATE hoimsystem_users SET token_invalid_before=:clock WHERE user_id=:id"), dict(clock=dt.datetime.now(dt.UTC).replace(tzinfo=None), id=actor.user_id))
    else:
        # A separate actual submitted review with model permission false;
        # never mutate approval flags to manufacture the negative case.
        ack = practice.submit_practice(db, actor, dict(review_id=case["base"][5]["review_id"], submission=submission(case["private"])))
        choice["clinical_training_submission_id"] = ack["submission_id"]
    db.flush()
    columns, observer = observe_bodies(db)
    try:
        with pytest.raises(HTTPException) as error:
            cfg.prepare_context(db, actor, choice)
        assert error.value.status_code in {403, 409}
    finally:
        event.remove(db.get_bind(), "after_cursor_execute", observer)
    assert_zero_bodies(columns)


def test_actual_uuid_prompt_preview_does_not_activate_then_independent_recorded_revalidation(configured):
    case, db = configured, configured["db"]
    teacher_ack = practice.submit_practice(db, case["author"], dict(review_id=case["review"]["review_id"], submission=submission(case["private"])))
    text_prompt = "\ufeff只解释当前实际练习😀\r\n\x00  尾部  "
    prompt = AIPromptVersion(feature_key="clinical_training", version=1, task_prompt=text_prompt, change_note="实际UUID版本的合成范围", created_by=case["author"].user_id)
    db.add(prompt)
    db.flush()
    case["config"].active_prompt_id, case["config"].revision = prompt.prompt_id, 2
    case["config"].enabled, case["config"].validation_status = 0, "unreviewed"
    db.flush()
    before_runs = db.query(AIRun).count()
    teacher_choice = {**selected(case), "clinical_training_submission_id": teacher_ack["submission_id"]}
    preview = cfg.prepare_context(db, case["author"], teacher_choice, preview=True)
    assert preview.prompt["prompt_id"] == prompt.prompt_id and len(prompt.prompt_id) == 36 and preview.prompt["prompt_version"] == 1
    assert preview.prompt["task_prompt"].encode() == text_prompt.encode()
    assert preview.execution["preview"] is True and case["config"].enabled == 0 and case["config"].validation_status == "unreviewed"
    with pytest.raises(HTTPException) as error:
        cfg.prepare_context(db, case["actor"], selected(case))
    assert error.value.status_code == 409
    case["config"].enabled, case["config"].validation_status, case["config"].revision = 1, "validated", 3
    case["config"].validated_at = dt.datetime.now(dt.UTC).replace(tzinfo=None, microsecond=0)
    db.flush()
    accepted = cfg.prepare_context(db, case["actor"], selected(case))
    assert accepted.prompt["prompt_id"] == prompt.prompt_id and accepted.prompt["task_prompt"] == text_prompt
    assert accepted.execution["preview"] is False and db.query(AIRun).count() == before_runs


def test_preview_requires_current_super_and_cannot_restore_other_learners_submission(configured):
    case, db = configured, configured["db"]
    for actor in (case["actor"], case["author"]):
        columns, observer = observe_bodies(db)
        try:
            with pytest.raises(HTTPException) as error:
                cfg.prepare_context(db, actor, selected(case), preview=True)
            assert error.value.status_code == 403
        finally:
            event.remove(db.get_bind(), "after_cursor_execute", observer)
        assert_zero_bodies(columns)
