"""Feedback text has immutable versions, explicit review and source-bound publication."""

import datetime
from pathlib import Path

import pytest
from alembic.config import Config
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import create_engine, inspect, text

from alembic import command
from app.ai.governance import encode_json
from app.ai.models import AIAuditEvent, AIReviewExcerpt
from app.ai.review_curation import create_excerpt, describe_excerpt, load_review_source, review_excerpt, source_state
from app.ai.schemas import ReviewExcerptReview, ReviewExcerptWrite
from app.models import Department, MedicalRecord, Registration, Review


@pytest.fixture
def source_case(seed_data, db_session):
    db_session.query(AIReviewExcerpt).delete()
    db_session.query(Review).delete()
    now = datetime.datetime.now()
    registration = Registration(patient_id=seed_data["patient"].patient_id, doctor_id=seed_data["doctor"].doctor_id, department_id=seed_data["department"].department_id, time=now)
    db_session.add(registration)
    db_session.flush()
    visit = MedicalRecord(patient_id=registration.patient_id, doctor_id=registration.doctor_id, registration_uuid=registration.registration_uuid)
    db_session.add(visit)
    db_session.flush()
    review = Review(
        patient_id=visit.patient_id,
        doctor_id=visit.doctor_id,
        visit_id=visit.medical_record_id,
        score=2,
        comment=seed_data["patient"].name + "评价" + seed_data["doctor"].name + "：候诊较久，电话13800138000",
        review_time=now,
    )
    db_session.add(review)
    db_session.commit()
    return review, registration, visit


def draft(db_session, seed_data, review, **changes):
    source = load_review_source(db_session, review.review_id)
    request = {"review_id": review.review_id, "expected_source_hash": source.fingerprint, "redacted_text": "候诊较久，希望了解顺序。", "change_note": "删除直接标识，保留原意", **changes}
    item = create_excerpt(db_session, seed_data["super_admin_user"], ReviewExcerptWrite(**request))
    db_session.commit()
    return item


def decide(db_session, seed_data, item, **changes):
    request = {"expected_revision": item.revision, "status": "published", "privacy_checked": True, "faithfulness_checked": True, "review_note": "已检查脱敏和原意", **changes}
    result = review_excerpt(db_session, seed_data["super_admin_user"], item.excerpt_id, ReviewExcerptReview(**request))
    db_session.commit()
    return result


def test_drafts_are_immutable_new_versions_and_audit_contains_no_comment_text(seed_data, db_session, source_case):
    review, _, _ = source_case
    first = draft(db_session, seed_data, review)
    second = draft(db_session, seed_data, review, redacted_text="候诊时间较长，希望了解流程。")
    assert (first.version, second.version) == (1, 2)
    assert first.status == second.status == "draft"
    assert first.redacted_text == "候诊较久，希望了解顺序。"
    assert "redacted_text" not in describe_excerpt(first)
    audit_text = encode_json([event.detail_json for event in db_session.query(AIAuditEvent).filter(AIAuditEvent.action.like("review_excerpt.%")).all()])
    assert review.comment not in audit_text and second.redacted_text not in audit_text and "13800138000" not in audit_text


def test_known_patient_staff_identifiers_are_removed_in_suggestion_and_rejected_in_draft(seed_data, db_session, source_case):
    review, _, _ = source_case
    source = load_review_source(db_session, review.review_id)
    suggestion = source.redact(review.comment)
    for identifier in (seed_data["patient"].name, seed_data["doctor"].name, "13800138000"):
        assert identifier not in suggestion
    with pytest.raises(HTTPException) as error:
        draft(db_session, seed_data, review, redacted_text=review.comment)
    assert error.value.status_code == 422
    review.comment = " "
    db_session.commit()
    with pytest.raises(HTTPException) as error:
        draft(db_session, seed_data, review)
    assert error.value.status_code == 409


def test_publication_requires_both_explicit_checks_and_matching_source(seed_data, db_session, source_case):
    review, _, _ = source_case
    item = draft(db_session, seed_data, review)
    for flags in ({"privacy_checked": False}, {"faithfulness_checked": False}):
        with pytest.raises(HTTPException) as error:
            decide(db_session, seed_data, item, **flags)
        assert error.value.status_code == 422
    review.comment += "原评论已修改"
    db_session.commit()
    assert source_state(db_session, item) == "stale"
    with pytest.raises(HTTPException) as error:
        decide(db_session, seed_data, item)
    assert error.value.status_code == 409
    assert item.status == "draft"


def test_publish_new_version_retires_prior_and_rejects_lost_review_updates(seed_data, db_session, source_case):
    review, _, _ = source_case
    first = decide(db_session, seed_data, draft(db_session, seed_data, review))
    old_revision = first.revision
    second = decide(db_session, seed_data, draft(db_session, seed_data, review, redacted_text="希望了解候诊顺序，等待较久。"))
    db_session.refresh(first)
    assert first.status == "retired" and first.revision == old_revision + 1
    assert second.status == "published" and second.privacy_checked and second.faithfulness_checked
    assert first.reviewed_at is not None and first.retired_at is not None
    with pytest.raises(HTTPException) as error:
        decide(db_session, seed_data, first, status="retired", expected_revision=old_revision)
    assert error.value.status_code == 409
    with pytest.raises(HTTPException) as error:
        decide(db_session, seed_data, first)
    assert error.value.status_code == 409


def test_broken_source_can_be_retired_but_cannot_be_published(seed_data, db_session, source_case):
    review, registration, _ = source_case
    first = decide(db_session, seed_data, draft(db_session, seed_data, review))
    second = draft(db_session, seed_data, review)
    registration.patient_id = seed_data["patient2"].patient_id
    db_session.commit()
    assert source_state(db_session, first) == "unavailable"
    with pytest.raises(HTTPException) as error:
        decide(db_session, seed_data, second)
    assert error.value.status_code == 409
    first = decide(db_session, seed_data, first, status="retired")
    assert first.status == "retired"


def test_effective_original_department_and_known_identity_changes_control_source_hash(seed_data, db_session, source_case):
    review, registration, visit = source_case
    item = draft(db_session, seed_data, review)
    new_department = Department(name="新评价归属")
    db_session.add(new_department)
    db_session.flush()
    seed_data["doctor"].department_id = new_department.department_id
    db_session.commit()
    # An unchanged original registration keeps its real department despite later physician rotation.
    assert source_state(db_session, item) == "current"
    visit.registration_uuid = None
    db_session.commit()
    assert source_state(db_session, item) == "stale"
    new_item = draft(db_session, seed_data, review)
    assert new_item.department_id == new_department.department_id
    seed_data["patient"].phone = "13912345678"
    db_session.commit()
    assert source_state(db_session, new_item) == "stale"


def test_invalid_source_revision_and_request_types_fail_before_draft_write(seed_data, db_session, source_case):
    review, _, _ = source_case
    with pytest.raises(HTTPException) as error:
        draft(db_session, seed_data, review, expected_source_hash="0" * 64)
    assert error.value.status_code == 409
    for review_id in (True, "1", 0):
        with pytest.raises(ValidationError):
            ReviewExcerptWrite(review_id=review_id, expected_source_hash="0" * 64, redacted_text="候诊原文", change_note="脱敏说明")
    assert db_session.query(AIReviewExcerpt).count() == 0


def test_excerpt_migration_upgrade_rollback_preserves_source_review(tmp_path):
    path = tmp_path / "review-excerpt.db"
    engine = create_engine(f"sqlite:///{path}")
    with engine.begin() as conn:
        for table, key in (("users", "user_id"), ("department", "department_id"), ("review", "review_id")):
            conn.exec_driver_sql(f"CREATE TABLE hoimsystem_{table} ({key} INTEGER PRIMARY KEY)")
        conn.exec_driver_sql("INSERT INTO hoimsystem_review VALUES (7)")
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{path}")
    command.stamp(config, "20261020_dose_rule_units")
    command.upgrade(config, "head")
    assert "hoimsystem_ai_review_excerpt" in inspect(engine).get_table_names()
    command.downgrade(config, "20261020_dose_rule_units")
    assert "hoimsystem_ai_review_excerpt" not in inspect(engine).get_table_names()
    with engine.connect() as conn:
        assert conn.scalar(text("SELECT review_id FROM hoimsystem_review")) == 7
    engine.dispose()
