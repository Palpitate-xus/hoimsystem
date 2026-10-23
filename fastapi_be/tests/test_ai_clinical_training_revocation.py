"""Actual bodyless withdrawal and concrete immutable Source revocation receipts."""

import pytest
from fastapi import HTTPException
from sqlalchemy import event, text

from app.ai import clinical_training_registry as r
from app.ai import clinical_training_reviews as reviews
from app.ai.models import AIAuditEvent
from tests.test_ai_clinical_training_reference_sql import reference_case as reference_case
from tests.test_ai_clinical_training_registry import assert_zero_bodies, observe_bodies
from tests.test_ai_clinical_training_reviews import publish
from tests.test_ai_clinical_training_reviews import reviewed_case as reviewed_case


@pytest.mark.parametrize("target", ["lesson", "review"])
def test_actual_withdrawal_specific_pk_after_reference_loss_is_bodyless_and_current_source_remains_denied(reviewed_case, target):
    (db, actor, reviewer, documents), lesson = reviewed_case
    published = publish(reviewed_case, model_processing_allowed=True)
    db.commit()
    documents[0].status = "retired"
    db.flush()
    columns, observer = observe_bodies(db)
    try:
        result = r.revoke_lesson(db, actor, lesson["lesson_id"], dict(revision=1, reason="完整课程来源撤回")) if target == "lesson" else reviews.revoke_review(db, actor, published["review_id"], dict(revision=1, reason="明确复核版本撤回"))
        assert result["status"] == "revoked" and result["revision"] == 2 and result["revocation_event_id"] > 0
        assert result["revocation_event_id"] not in {lesson["creation_event_id"], published["creation_event_id"]}
        with pytest.raises(HTTPException) as error:
            reviews.get_review(db, actor, published["review_id"], include_body=True)
        assert error.value.status_code == 403
    finally:
        event.remove(db.get_bind(), "after_cursor_execute", observer)
    assert_zero_bodies(columns)
    assert not any(name == "review_json" or name.endswith("_review_json") for name in columns)
    assert reviews.get_review(db, actor, published["review_id"])["review_decision"] == "published"


def test_current_super_can_withdraw_stale_author_lesson_without_restoring_private_authority(reviewed_case):
    (db, actor, reviewer, documents), lesson = reviewed_case
    published = publish(reviewed_case)
    db.commit()
    actor_id = actor.user_id
    db.execute(text("UPDATE hoimsystem_users SET user_role='admin' WHERE user_id=:key"), {"key": actor_id})
    columns, observer = observe_bodies(db)
    try:
        result = r.revoke_lesson(db, reviewer, lesson["lesson_id"], dict(revision=1, reason="作者失权后的治理撤回"))
        assert result["status"] == "revoked" and result["revoked_by"] == reviewer.user_id
        assert reviews.get_review(db, reviewer, published["review_id"])["status"] == "published"
        with pytest.raises(HTTPException) as error:
            reviews.get_review(db, reviewer, published["review_id"], include_body=True)
        assert error.value.status_code == 403
    finally:
        event.remove(db.get_bind(), "after_cursor_execute", observer)
    assert_zero_bodies(columns)


@pytest.mark.parametrize("target", ["lesson", "review"])
def test_duplicate_withdrawal_is_cas_conflict_without_a_second_audit(reviewed_case, target):
    (db, actor, reviewer, documents), lesson = reviewed_case
    published = publish(reviewed_case)
    db.commit()
    operation = (lambda: r.revoke_lesson(db, actor, lesson["lesson_id"], dict(revision=1, reason="明确撤回"))) if target == "lesson" else (lambda: reviews.revoke_review(db, actor, published["review_id"], dict(revision=1, reason="明确撤回")))
    operation()
    db.commit()
    before = db.query(AIAuditEvent).count()
    with pytest.raises(HTTPException) as error:
        operation()
    assert error.value.status_code == 409 and db.query(AIAuditEvent).count() == before


def test_bad_specific_revocation_event_does_not_restore_a_revoked_lesson(reviewed_case):
    (db, actor, reviewer, documents), lesson = reviewed_case
    published = publish(reviewed_case)
    r.revoke_lesson(db, actor, lesson["lesson_id"], dict(revision=1, reason="明确撤回"))
    db.execute(text("UPDATE hoimsystem_ai_training_lesson SET revocation_event_id=:event WHERE lesson_id=:key"), {"key": lesson["lesson_id"], "event": published["creation_event_id"]})
    columns, observer = observe_bodies(db)
    try:
        with pytest.raises(HTTPException) as error:
            r.get_lesson(db, actor, lesson["lesson_id"])
        assert error.value.status_code == 409
    finally:
        event.remove(db.get_bind(), "after_cursor_execute", observer)
    assert_zero_bodies(columns)
