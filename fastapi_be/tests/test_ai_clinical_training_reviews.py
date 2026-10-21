"""Actual independent complete lesson publication and separately denied model use."""

import datetime as dt

import pytest
from fastapi import HTTPException
from sqlalchemy import event, text

from app.ai import clinical_training_contract as c
from app.ai import clinical_training_registry as r
from app.ai import clinical_training_reviews as reviews
from app.ai.clinical_training_models import AITrainingReview
from app.ai.models import AIAuditEvent
from tests.test_ai_clinical_training_reference_sql import reference_case as reference_case
from tests.test_ai_clinical_training_registry import assert_zero_bodies, observe_bodies, request


@pytest.fixture
def reviewed_case(reference_case):
    db, actor, reviewer, documents = reference_case
    metadata = r.register_lesson(db, actor, request(reference_case))
    db.commit()
    return reference_case, metadata


def proposal(metadata, **changes):
    value = dict(expected_lesson_revision=metadata["revision"], expected_private_sha256=metadata["private_hash"], expected_public_sha256=metadata["public_hash"], expected_references_sha256=metadata["references_hash"], decision="publish", synthetic_material_checked=True, answer_key_checked=True, reference_applicability_checked=True, model_processing_allowed=False, basis="合成资料的实际独立声明复核；不代表真实医学效力")
    return {**value, **changes}


def publish(case, **changes):
    (db, actor, reviewer, documents), lesson = case
    return reviews.review_lesson(db, reviewer, lesson["lesson_id"], proposal(lesson, **changes))


def test_actual_independent_review_binds_all_complete_source_hashes_and_concrete_pk(reviewed_case):
    (db, actor, reviewer, documents), lesson = reviewed_case
    result = publish(reviewed_case)
    assert result["reviewed_by"] == reviewer.user_id != actor.user_id
    assert result["status"] == result["review_decision"] == "published"
    assert result["model_processing_allowed"] == 0 and result["creation_event_id"] != lesson["creation_event_id"]
    assert result["lesson_private_hash"] == lesson["private_hash"] and result["lesson_public_hash"] == lesson["public_hash"] and result["lesson_references_hash"] == lesson["references_hash"]
    body = reviews.get_review(db, actor, result["review_id"], include_body=True)
    assert body["proposal"] == proposal(lesson)
    receipt = db.get(AIAuditEvent, result["creation_event_id"])
    header, _ = reviews.review_header(db, result["review_id"], require_published=True)
    assert receipt.action == "training_lesson_review" and receipt.target == result["review_id"] and receipt.detail_json == c.canonical_json(r.detail(header, reviews.ORIGIN_COLUMNS))
    assert "PRIVATE_REVIEWED_RATIONALE_SENTINEL" not in receipt.detail_json
    with pytest.raises(HTTPException) as error:
        reviews.review_header(db, result["review_id"], require_published=True, execution=True)
    assert error.value.status_code == 403


@pytest.mark.parametrize("flag", reviews.FLAGS[:3])
def test_each_explicit_publication_assertion_is_required_without_staged_audit(reviewed_case, flag):
    (db, actor, reviewer, documents), lesson = reviewed_case
    before = {model.__tablename__: db.query(model).count() for model in (AITrainingReview, AIAuditEvent)}
    with pytest.raises(HTTPException) as error:
        publish(reviewed_case, **{flag: False})
    assert error.value.status_code == 422
    assert {model.__tablename__: db.query(model).count() for model in (AITrainingReview, AIAuditEvent)} == before


@pytest.mark.parametrize("fault", ["same_author", "private_hash", "public_hash", "references_hash"])
def test_self_review_or_wrong_complete_version_refuses_before_any_source_body(reviewed_case, fault):
    (db, actor, reviewer, documents), lesson = reviewed_case
    value = proposal(lesson)
    if fault != "same_author":
        value["expected_" + fault.replace("_hash", "") + "_sha256"] = "0" * 64
    columns, observer = observe_bodies(db)
    try:
        with pytest.raises(HTTPException) as error:
            reviews.review_lesson(db, actor if fault == "same_author" else reviewer, lesson["lesson_id"], value)
        assert error.value.status_code == (403 if fault == "same_author" else 409)
    finally:
        event.remove(db.get_bind(), "after_cursor_execute", observer)
    assert_zero_bodies(columns)


def test_rejection_is_a_real_separate_review_without_publication_or_model_grant(reviewed_case):
    (db, actor, reviewer, documents), lesson = reviewed_case
    result = publish(reviewed_case, decision="reject", synthetic_material_checked=False)
    assert result["status"] == result["review_decision"] == "rejected" and result["model_processing_allowed"] == 0
    assert reviews.get_review(db, actor, result["review_id"], include_body=True)["proposal"]["decision"] == "reject"
    with pytest.raises(HTTPException) as error:
        reviews.review_header(db, result["review_id"], require_published=True)
    assert error.value.status_code == 403


@pytest.mark.parametrize("fault", ["role", "epoch", "wrong_specific_pk", "reference_metadata"])
def test_current_review_authority_or_specific_receipt_refuses_before_review_and_source_body(reviewed_case, fault):
    (db, actor, reviewer, documents), lesson = reviewed_case
    result = publish(reviewed_case, model_processing_allowed=True)
    if fault == "role":
        db.execute(text("UPDATE hoimsystem_users SET user_role='admin' WHERE user_id=:key"), {"key": reviewer.user_id})
    elif fault == "epoch":
        db.execute(text("UPDATE hoimsystem_users SET token_invalid_before=:clock WHERE user_id=:key"), {"key": reviewer.user_id, "clock": dt.datetime.now(dt.UTC).replace(tzinfo=None)})
    elif fault == "wrong_specific_pk":
        db.execute(text("UPDATE hoimsystem_ai_training_review SET creation_event_id=:event WHERE review_id=:key"), {"key": result["review_id"], "event": lesson["creation_event_id"]})
    else:
        documents[0].title += " changed"
        db.flush()
    columns, observer = observe_bodies(db)
    try:
        with pytest.raises(HTTPException) as error:
            reviews.get_review(db, actor, result["review_id"], include_body=True)
        assert error.value.status_code in {403, 409}
    finally:
        event.remove(db.get_bind(), "after_cursor_execute", observer)
    assert_zero_bodies(columns)
    assert not any(name == "review_json" or name.endswith("_review_json") for name in columns)


def test_after_actual_review_insert_reference_change_rolls_back_review_specific_audit_and_source_mutation(reviewed_case):
    (db, actor, reviewer, documents), lesson = reviewed_case
    before = {model.__tablename__: db.query(model).count() for model in (AITrainingReview, AIAuditEvent)}
    document_id = documents[0].document_id
    db.execute(text("CREATE TEMP TRIGGER training_after_review_insert AFTER INSERT ON hoimsystem_ai_training_review BEGIN UPDATE hoimsystem_ai_knowledge_document SET status='retired' WHERE document_id='" + document_id + "'; END"))
    try:
        with pytest.raises(HTTPException) as error:
            publish(reviewed_case)
        assert error.value.status_code in {403, 409}
        assert {model.__tablename__: db.query(model).count() for model in (AITrainingReview, AIAuditEvent)} == before
        assert db.execute(text("SELECT status FROM hoimsystem_ai_knowledge_document WHERE document_id=:key"), {"key": document_id}).scalar_one() == "published"
    finally:
        db.execute(text("DROP TRIGGER IF EXISTS training_after_review_insert"))
        db.commit()
