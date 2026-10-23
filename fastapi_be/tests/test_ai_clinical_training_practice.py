"""Actual persisted local practice, deterministic recomputation and source loss."""

import copy
import datetime as dt
import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import event, text

from app.ai import clinical_training_contract as c
from app.ai import clinical_training_practice as practice
from app.ai import clinical_training_registry as r
from app.ai import clinical_training_reviews as reviews
from app.ai.clinical_training_practice_models import AITrainingSubmission
from app.ai.models import AIAuditEvent
from tests.test_ai_clinical_training_contract import submission
from tests.test_ai_clinical_training_reference_sql import reference_case as reference_case
from tests.test_ai_clinical_training_registry import observe_bodies
from tests.test_ai_clinical_training_reviews import publish
from tests.test_ai_clinical_training_reviews import reviewed_case as reviewed_case


@pytest.fixture
def practice_case(reviewed_case, seed_data):
    (db, author, reviewer, documents), lesson = reviewed_case
    published = publish(reviewed_case)
    private = r.get_lesson(db, author, lesson["lesson_id"], include_body=True)["private"]
    db.commit()
    return db, author, reviewer, documents, lesson, published, private, seed_data["doctor_user"]


def request(case):
    return dict(review_id=case[5]["review_id"], submission=submission(case[6]))


def assert_no_key_reference_or_practice_body(columns):
    assert not any(name == key or name.endswith("_" + key) for name in columns for key in ("private_json", "references_json", "review_json", "content", "submission_json", "feedback_json"))


def test_actual_submit_ack_has_no_answer_then_committed_current_owner_feedback_recomputes_exact_key(practice_case):
    db, author, reviewer, documents, lesson, published, private, actor = practice_case
    value = request(practice_case)
    ack = practice.submit_practice(db, actor, value)
    wire = c.whole(ack)
    assert ack["model_attempted"] is False and ack["record_kind"] == "server_recorded_deterministic_practice"
    assert all(key not in wire for key in ("correct_option_ids", "reviewed_rationale", "feedback", lesson["private_hash"], published["review_hash"]))
    db.commit()
    result = practice.get_practice(db, actor, ack["submission_id"], include_feedback=True)
    assert result["submission"] == value["submission"]
    assert result["feedback"]["matching_count"] == result["feedback"]["question_count"] == 2
    assert result["feedback"]["differing_count"] == result["feedback"]["unanswered_count"] == 0
    assert result["feedback"]["assessment_claim"] == "practice_record_only_not_clinical_competence_or_credential"
    receipt = db.get(AIAuditEvent, ack["creation_event_id"])
    header = practice.submission_header(db, actor, ack["submission_id"])
    assert receipt.action == "training_practice_submit" and receipt.target == ack["submission_id"]
    assert receipt.detail_json == c.canonical_json(r.detail(header, practice.ORIGIN_COLUMNS))
    assert ack["creation_event_id"] not in {lesson["creation_event_id"], published["creation_event_id"]}


def test_explicit_unanswered_and_partial_multi_selection_are_distinct_exact_matching_outcomes(practice_case):
    db, author, reviewer, documents, lesson, published, private, actor = practice_case
    value = request(practice_case)
    value["submission"]["answers"][0]["selected_option_ids"] = []
    value["submission"]["answers"][1]["selected_option_ids"] = [private["questions"][1]["correct_option_ids"][0]]
    ack = practice.submit_practice(db, actor, value)
    feedback = practice.get_practice(db, actor, ack["submission_id"], include_feedback=True)["feedback"]
    assert (feedback["matching_count"], feedback["differing_count"], feedback["unanswered_count"]) == (0, 1, 1)
    assert [item["outcome"] for item in feedback["questions"]] == ["explicitly_unanswered", "differs_from_reviewed_key"]


@pytest.mark.parametrize("fault", ["missing_question", "foreign_question", "foreign_option", "duplicate_option", "single_multiple", "public_sha", "lesson_id", "fake_answer_key"])
def test_incomplete_or_foreign_submission_is_rejected_before_hidden_key_or_any_practice_body(practice_case, fault):
    db, author, reviewer, documents, lesson, published, private, actor = practice_case
    value = request(practice_case)
    submitted = value["submission"]
    if fault == "missing_question":
        submitted["answers"].pop()
    elif fault == "foreign_question":
        submitted["answers"][0]["question_id"] = str(uuid.uuid4())
    elif fault == "foreign_option":
        submitted["answers"][0]["selected_option_ids"] = [str(uuid.uuid4())]
    elif fault == "duplicate_option":
        submitted["answers"][0]["selected_option_ids"] *= 2
    elif fault == "single_multiple":
        submitted["answers"][0]["selected_option_ids"] = [option["option_id"] for option in private["questions"][0]["options"][:2]]
    elif fault == "public_sha":
        submitted["public_source_sha256"] = "0" * 64
    elif fault == "lesson_id":
        submitted["lesson_id"] = str(uuid.uuid4())
    else:
        submitted["correct_option_ids"] = ["not-accepted"]
    before = {model.__tablename__: db.query(model).count() for model in (AITrainingSubmission, AIAuditEvent)}
    columns, observer = observe_bodies(db)
    try:
        with pytest.raises(HTTPException) as error:
            practice.submit_practice(db, actor, value)
        assert error.value.status_code in {409, 422}
    finally:
        event.remove(db.get_bind(), "after_cursor_execute", observer)
    assert_no_key_reference_or_practice_body(columns)
    assert {model.__tablename__: db.query(model).count() for model in (AITrainingSubmission, AIAuditEvent)} == before


@pytest.mark.parametrize("fault", ["other_owner", "owner_epoch", "source_withdrawn", "review_withdrawn", "reference_metadata", "wrong_specific_pk"])
def test_current_owner_source_and_specific_receipt_failure_refuses_before_all_answer_feedback_and_source_bodies(practice_case, seed_data, fault):
    db, author, reviewer, documents, lesson, published, private, actor = practice_case
    ack = practice.submit_practice(db, actor, request(practice_case))
    requester = actor
    if fault == "other_owner":
        requester = author  # Super governance never restores another learner's key.
    elif fault == "owner_epoch":
        db.execute(text("UPDATE hoimsystem_users SET token_invalid_before=:clock WHERE user_id=:key"), {"key": actor.user_id, "clock": dt.datetime.now(dt.UTC).replace(tzinfo=None)})
    elif fault == "source_withdrawn":
        r.revoke_lesson(db, author, lesson["lesson_id"], dict(revision=1, reason="明确课程撤回"))
    elif fault == "review_withdrawn":
        reviews.revoke_review(db, author, published["review_id"], dict(revision=1, reason="明确复核撤回"))
    elif fault == "reference_metadata":
        documents[0].title += " changed"
        db.flush()
    else:
        db.execute(text("UPDATE hoimsystem_ai_training_submission SET creation_event_id=:event WHERE submission_id=:key"), {"key": ack["submission_id"], "event": published["creation_event_id"]})
    columns, observer = observe_bodies(db)
    try:
        with pytest.raises(HTTPException) as error:
            practice.get_practice(db, requester, ack["submission_id"], include_feedback=True)
        assert error.value.status_code in {403, 409}
    finally:
        event.remove(db.get_bind(), "after_cursor_execute", observer)
    assert_no_key_reference_or_practice_body(columns)


def test_after_actual_submission_insert_reference_mutation_rolls_back_submission_receipt_and_mutation(practice_case):
    db, author, reviewer, documents, lesson, published, private, actor = practice_case
    value, document_id = request(practice_case), documents[0].document_id
    before = {model.__tablename__: db.query(model).count() for model in (AITrainingSubmission, AIAuditEvent)}
    db.execute(text("CREATE TEMP TRIGGER training_after_submission_insert AFTER INSERT ON hoimsystem_ai_training_submission BEGIN UPDATE hoimsystem_ai_knowledge_document SET status='retired' WHERE document_id='" + document_id + "'; END"))
    try:
        with pytest.raises(HTTPException) as error:
            practice.submit_practice(db, actor, value)
        assert error.value.status_code in {403, 409}
        assert {model.__tablename__: db.query(model).count() for model in (AITrainingSubmission, AIAuditEvent)} == before
        assert db.execute(text("SELECT status FROM hoimsystem_ai_knowledge_document WHERE document_id=:key"), {"key": document_id}).scalar_one() == "published"
    finally:
        db.execute(text("DROP TRIGGER IF EXISTS training_after_submission_insert"))
        db.commit()


def test_self_rehashed_false_feedback_still_cannot_replace_original_specific_submit_receipt(practice_case):
    db, author, reviewer, documents, lesson, published, private, actor = practice_case
    ack = practice.submit_practice(db, actor, request(practice_case))
    row = db.get(AITrainingSubmission, ack["submission_id"])
    false = copy.deepcopy(c.parse_packet(row.feedback_json))
    false["questions"][0]["reviewed_rationale"] = "changed rationale"
    raw = c.whole(false)
    row.feedback_json, row.feedback_hash, row.feedback_bytes = raw, r.raw_sha(raw), len(raw.encode())
    db.flush()
    columns, observer = observe_bodies(db)
    try:
        with pytest.raises(HTTPException) as error:
            practice.get_practice(db, actor, ack["submission_id"], include_feedback=True)
        assert error.value.status_code == 409
    finally:
        event.remove(db.get_bind(), "after_cursor_execute", observer)
    assert_no_key_reference_or_practice_body(columns)
