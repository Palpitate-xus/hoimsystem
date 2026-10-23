"""Actual answer-free learner reads; local practice and model grants stay separate."""

import datetime as dt

import pytest
from fastapi import HTTPException
from sqlalchemy import event, text

from app.ai import clinical_training_contract as c
from app.ai import clinical_training_learner as learner
from app.ai import clinical_training_registry as r
from app.ai.models import AIFeatureConfig
from tests.test_ai_clinical_training_reference_sql import reference_case as reference_case
from tests.test_ai_clinical_training_registry import assert_zero_bodies, observe_bodies
from tests.test_ai_clinical_training_reviews import publish
from tests.test_ai_clinical_training_reviews import reviewed_case as reviewed_case


def assert_no_private_or_reference(columns):
    assert not any(name == key or name.endswith("_" + key) for name in columns for key in ("private_json", "references_json", "review_json", "content"))


def test_actual_learner_public_quiz_uses_no_private_reference_or_review_body_and_no_answer_fingerprint(reviewed_case, seed_data):
    (db, actor, reviewer, documents), lesson = reviewed_case
    published = publish(reviewed_case)
    columns, observer = observe_bodies(db)
    try:
        value = learner.get_public_lesson(db, seed_data["doctor_user"], published["review_id"])
    finally:
        event.remove(db.get_bind(), "after_cursor_execute", observer)
    assert_no_private_or_reference(columns)
    wire = c.whole(value)
    assert value["public_source_sha256"] == lesson["public_hash"] and value["model_processing_allowed"] is False
    assert all(key not in wire for key in ("correct_option_ids", "reviewed_rationale", "reference_ids", "private_hash", "private_sha256", "references_hash", "review_hash", lesson["private_hash"], published["review_hash"]))


@pytest.mark.parametrize("fault", ["requester_role", "requester_epoch", "feature_roles", "super_outside_roles", "source_revoked", "reviewer_epoch", "reference_epoch", "reference_metadata"])
def test_current_learner_source_roles_and_epochs_precede_any_public_or_private_body(reviewed_case, seed_data, fault):
    (db, actor, reviewer, documents), lesson = reviewed_case
    published = publish(reviewed_case)
    requester = seed_data["doctor_user"]
    if fault == "requester_role":
        db.execute(text("UPDATE hoimsystem_users SET user_role='patient' WHERE user_id=:key"), {"key": requester.user_id})
    elif fault == "requester_epoch":
        db.execute(text("UPDATE hoimsystem_users SET token_invalid_before=:clock WHERE user_id=:key"), {"key": requester.user_id, "clock": dt.datetime.now(dt.UTC).replace(tzinfo=None)})
    elif fault in {"feature_roles", "super_outside_roles"}:
        config = AIFeatureConfig(feature_key="clinical_training", allowed_roles_json='["admin"]', revision=1, updated_by=actor.user_id)
        db.add(config)
        db.flush()
        if fault == "super_outside_roles":
            requester = actor
    elif fault == "source_revoked":
        r.revoke_lesson(db, actor, lesson["lesson_id"], dict(revision=1, reason="明确撤回课程"))
    elif fault in {"reviewer_epoch", "reference_epoch"}:
        # Both are actual review/reference governance actors in this fixture.
        db.execute(text("UPDATE hoimsystem_users SET token_invalid_before=:clock WHERE user_id=:key"), {"key": reviewer.user_id, "clock": dt.datetime.now(dt.UTC).replace(tzinfo=None)})
    else:
        documents[0].title += " changed"
        db.flush()
    columns, observer = observe_bodies(db)
    try:
        with pytest.raises(HTTPException) as error:
            learner.get_public_lesson(db, requester, published["review_id"])
        assert error.value.status_code in {403, 409}
    finally:
        event.remove(db.get_bind(), "after_cursor_execute", observer)
    assert_zero_bodies(columns)
    assert_no_private_or_reference(columns)


def test_disabled_ai_model_does_not_turn_current_local_practice_into_model_execution(reviewed_case, seed_data):
    (db, actor, reviewer, documents), lesson = reviewed_case
    published = publish(reviewed_case)
    db.add(AIFeatureConfig(feature_key="clinical_training", enabled=0, provider_id=None, allowed_roles_json='["doctor"]', revision=1, updated_by=actor.user_id))
    db.flush()
    result = learner.get_public_lesson(db, seed_data["doctor_user"], published["review_id"])
    assert result["lesson"]["intended_use"] == "education_only_not_patient_treatment_or_credentialing"
    assert result["model_processing_allowed"] is False
