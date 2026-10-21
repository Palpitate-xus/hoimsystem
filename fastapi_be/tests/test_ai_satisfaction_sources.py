"""Actual isolated review/excerpt/parent SQL; safe source does not contain raw comments."""

import copy
import datetime
import json
import uuid

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import text

from app.ai.models import AIAuditEvent
from app.ai.review_curation import create_excerpt, load_review_source, review_excerpt
from app.ai.satisfaction_contract import CaptureRequest, CaseCreate, SourceReview, SourceRevoke
from app.ai.satisfaction_models import AISatisfactionCase
from app.ai.satisfaction_sources import (
    authorize_case,
    binding_for,
    canonical_json,
    case_current,
    create_case,
    frozen_case_proof,
    hash_content,
    preview_input,
    project_snapshot,
    review_case,
    revoke_case,
    verify_capture,
    verify_snapshot,
)
from app.ai.schemas import ReviewExcerptReview, ReviewExcerptWrite
from app.models import Doctor, MedicalRecord, Review

BASIS = "隔离合成评价工程审查依据，人工隐私及原意核查仅为测试声明，不代表事实核实或医院真实验证。"


@pytest.fixture
def satisfaction_case(db_session, seed_data):
    db = db_session
    # Independent actual identities; no dependence on another test's review root.
    visit = MedicalRecord(patient_id=seed_data["patient"].patient_id, doctor_id=seed_data["doctor"].doctor_id, registration_uuid=None)
    db.add(visit)
    db.flush()
    review = Review(
        patient_id=visit.patient_id,
        doctor_id=visit.doctor_id,
        visit_id=visit.medical_record_id,
        score=2,
        comment="张三：合成原评论候诊较久，电话13800138000",
        review_time=datetime.datetime(2026, 10, 20, 10, 0, 0),
    )
    db.add(review)
    db.commit()
    source = load_review_source(db, review.review_id)
    excerpt = create_excerpt(
        db,
        seed_data["super_admin_user"],
        ReviewExcerptWrite(
            review_id=review.review_id, expected_source_hash=source.fingerprint, redacted_text="合成就诊者认为候诊较久，希望说明顺序。", change_note="隔离合成人工检查直接标识并保留原意。"
        ),
    )
    db.commit()
    excerpt = review_excerpt(
        db,
        seed_data["super_admin_user"],
        excerpt.excerpt_id,
        ReviewExcerptReview(expected_revision=1, status="published", privacy_checked=True, faithfulness_checked=True, review_note="隔离合成人工隐私和原意核查声明。"),
    )
    db.commit()
    return {**seed_data, "review": review, "excerpt": excerpt, "visit": visit}


def period(case, hospital=False):
    return {
        "scope_kind": "hospital_reviews" if hospital else "explicit_doctor_cohort",
        "doctor_ids": [] if hospital else [case["doctor"].doctor_id],
        "date_from": "2026-10-20",
        "date_to": "2026-10-20",
    }


def request(db, case, *, selected=True, hospital=False, actor=None):
    preview = preview_input(db, actor or case["super_admin_user"], period(case, hospital))
    chosen = next(o for o in preview["excerpt_options"] if o["excerpt_id"] == case["excerpt"].excerpt_id)
    return {
        "request": period(case, hospital),
        "expected_collection_digest": preview["collection_digest"],
        "selected_excerpts": [{k: chosen[k] for k in ("excerpt_id", "review_token", "content_hash", "governance_hash")}] if selected else [],
        "basis_note": BASIS,
    }


def published(db, case, *, actor=None, selected=True):
    made = create_case(db, actor or case["super_admin_user"], request(db, case, selected=selected, actor=actor))
    return review_case(db, case["super_admin_user"], made["case_id"], {"expected_revision": 1, "decision": "publish", "basis_note": BASIS})


def test_actual_complete_capture_and_public_safe_projection_never_return_raw_patient_visit_comment(db_session, satisfaction_case):
    db, case = db_session, satisfaction_case
    made = published(db, case)
    ordinary = case_current(db, case["admin_user"], made["case_id"])
    source = ordinary["public_source"]
    assert ordinary["eligible"] and ordinary["snapshot"] is None
    assert ordinary["review_basis_note"] is ordinary["revoke_reason"] is None
    serialized = canonical_json(ordinary)
    for private in (case["review"].comment, case["patient"].identity, case["patient"].phone, case["patient"].name, case["visit"].medical_record_id):
        assert private not in serialized
    assert '"review_id"' not in serialized and '"patient_id"' not in serialized and '"visit_id"' not in serialized
    assert source["safe_snapshot"]["selected_excerpts"][0]["text"] == case["excerpt"].redacted_text
    assert hash_content(source["safe_snapshot"]) == source["safe_projection_hash"]
    row, snapshot, native = authorize_case(db, case["admin_user"], made["case_id"])
    assert native == source and snapshot == made["snapshot"]
    assert authorize_case(db, case["admin_user"], made["case_id"], binding=binding_for(row, source))[2] == source
    frozen = frozen_case_proof(db, made["case_id"])
    assert frozen["snapshot"] is None and frozen["frozen_task_view"]
    assert case["review"].comment not in canonical_json(frozen)


@pytest.mark.parametrize("field,value", [("doctor_ids", [True]), ("date_from", "2026-02-30"), ("date_to", "2027-11-01"), ("scope_kind", "registration_department")])
def test_strict_actual_scope_dates_and_scalar_types(satisfaction_case, field, value):
    value = {**period(satisfaction_case), field: value}
    with pytest.raises(ValidationError):
        CaptureRequest.model_validate(value)


def test_hospital_create_super_only_safe_read_admin_and_director_exact_current_doctor_scope(db_session, satisfaction_case):
    db, case = db_session, satisfaction_case
    for key in ("admin_user", "director_user", "doctor_user", "patient_user"):
        with pytest.raises(HTTPException) as error:
            preview_input(db, case[key], period(case, hospital=True))
        assert error.value.status_code == 403
    preview_input(db, case["director_user"], period(case))
    foreign = Doctor(name="合成范围外医生", department_id=None)
    db.add(foreign)
    db.commit()
    with pytest.raises(HTTPException) as error:
        preview_input(db, case["director_user"], {**period(case), "doctor_ids": sorted([case["doctor"].doctor_id, foreign.doctor_id])})
    assert error.value.status_code == 403


def test_null_invalid_ratings_null_bad_clocks_and_unresolved_parents_are_full_members_not_zero_or_nps(db_session, satisfaction_case):
    db, case = db_session, satisfaction_case
    for score, clock in ((5, None), (None, datetime.datetime(2026, 10, 20)), (-4, datetime.datetime(2026, 10, 20)), (9, datetime.datetime(2026, 10, 20))):
        db.add(Review(doctor_id=case["doctor"].doctor_id, patient_id=None, visit_id=None, score=score, comment="未选原评论不外发", review_time=clock))
    db.flush()
    last = Review(doctor_id=case["doctor"].doctor_id, score=3, review_time=None)
    db.add(last)
    db.flush()
    db.execute(text("UPDATE hoimsystem_review SET review_time='2026-02-30 00:00:00' WHERE review_id=:id"), {"id": last.review_id})
    db.commit()
    preview = preview_input(db, case["super_admin_user"], period(case))
    safe = preview["safe_snapshot"]
    assert safe["unknown_date_member_count"] >= 2 and safe["unresolved_parent_count"] >= 5
    stats = safe["all_member_statistics"]
    assert stats["null_score_count"] >= 1 and stats["invalid_score_count"] >= 2
    assert stats["valid_score_count"] + stats["null_score_count"] + stats["invalid_score_count"] == stats["record_count"]
    assert stats["mean_valid_score"] == {"numerator": 10, "denominator": 3}
    assert safe["known_period_statistics"]["mean_valid_score"] == {"numerator": 2, "denominator": 1}
    assert "nps" not in stats and "response_rate" not in stats


@pytest.mark.parametrize("change", ["new_review", "new_draft_version", "comment", "reviewer_role", "patient_identifier", "visit_binding", "doctor_department"])
def test_any_related_new_nonwinner_or_parent_changes_invalidate_source_and_ordinary_redacts(db_session, satisfaction_case, change):
    db, case = db_session, satisfaction_case
    made = published(db, case)
    if change == "new_review":
        db.add(Review(doctor_id=case["doctor"].doctor_id, score=1, review_time=datetime.datetime(2026, 10, 20)))
    elif change == "new_draft_version":
        source = load_review_source(db, case["review"].review_id)
        create_excerpt(
            db,
            case["super_admin_user"],
            ReviewExcerptWrite(review_id=case["review"].review_id, expected_source_hash=source.fingerprint, redacted_text="新未选中合成草稿", change_note="新增版本也纳入完整集合"),
        )
    elif change == "comment":
        case["review"].comment += "原评论改变"
    elif change == "reviewer_role":
        case["super_admin_user"].user_role = "admin"
    elif change == "patient_identifier":
        case["patient"].phone = "13911112222"
    elif change == "visit_binding":
        case["visit"].patient_id = case["patient2"].patient_id
    else:
        case["doctor"].department_id = None
    db.commit()
    ordinary = case_current(db, case["admin_user"], made["case_id"])
    assert not ordinary["eligible"] and not ordinary["parent_current"]
    assert ordinary["snapshot"] is ordinary["safe_snapshot"] is ordinary["public_source"] is None
    with pytest.raises(HTTPException) as error:
        authorize_case(db, case["admin_user"], made["case_id"])
    assert error.value.status_code == 409


def test_no_favourable_version_no_foreign_selection_and_exact_capture_anchor(db_session, satisfaction_case):
    db, case = db_session, satisfaction_case
    req = request(db, case)
    wrong = copy.deepcopy(req)
    wrong["selected_excerpts"][0]["excerpt_id"] = str(uuid.uuid4())
    with pytest.raises(HTTPException) as error:
        create_case(db, case["super_admin_user"], wrong)
    assert error.value.status_code == 409
    db.add(Review(doctor_id=case["doctor"].doctor_id, score=1, review_time=datetime.datetime(2026, 10, 20)))
    db.commit()
    with pytest.raises(HTTPException) as error:
        create_case(db, case["super_admin_user"], req)
    assert error.value.status_code == 409
    assert db.query(AISatisfactionCase).filter_by(content_hash="0" * 64).count() == 0


def test_cas_reject_terminal_revoke_preserves_publication_and_super_frozen(db_session, satisfaction_case):
    db, case = db_session, satisfaction_case
    made = published(db, case)
    before_hash = made["content_hash"]
    with pytest.raises(HTTPException) as error:
        revoke_case(db, case["super_admin_user"], made["case_id"], {"expected_revision": 1, "basis_note": BASIS})
    assert error.value.status_code == 409
    revoked = revoke_case(db, case["super_admin_user"], made["case_id"], {"expected_revision": 2, "basis_note": BASIS})
    assert revoked["content_hash"] == before_hash and revoked["revision"] == 3 and revoked["public_source"] == made["public_source"]
    ordinary = case_current(db, case["admin_user"], made["case_id"])
    assert ordinary["safe_snapshot"] is ordinary["public_source"] is None
    rejected = create_case(db, case["super_admin_user"], request(db, case))
    review_case(db, case["super_admin_user"], rejected["case_id"], {"expected_revision": 1, "decision": "reject", "basis_note": BASIS})
    with pytest.raises(HTTPException):
        review_case(db, case["super_admin_user"], rejected["case_id"], {"expected_revision": 2, "decision": "publish", "basis_note": BASIS})


def test_actual_audit_sql_failure_rolls_back_case_and_whole_governance(db_session, satisfaction_case):
    db, case = db_session, satisfaction_case
    made = create_case(db, case["super_admin_user"], request(db, case))
    count = db.query(AIAuditEvent).count()
    db.execute(
        text("CREATE TRIGGER reject_satisfaction_audit BEFORE INSERT ON hoimsystem_ai_audit_event WHEN NEW.action='satisfaction_case.review' BEGIN SELECT RAISE(ABORT,'synthetic audit failure'); END")
    )
    db.commit()
    try:
        with pytest.raises(Exception, match="synthetic audit failure"):
            review_case(db, case["super_admin_user"], made["case_id"], {"expected_revision": 1, "decision": "publish", "basis_note": BASIS})
        row = db.query(AISatisfactionCase).filter_by(case_id=made["case_id"]).one()
        assert row.status == "draft" and row.revision == 1 and row.projection_json is None
        assert db.query(AIAuditEvent).count() == count
    finally:
        db.execute(text("DROP TRIGGER reject_satisfaction_audit"))
        db.commit()


def test_own_tamper_even_super_and_rehashed_invalid_scope_date_are_rejected(db_session, satisfaction_case):
    db, case = db_session, satisfaction_case
    made = published(db, case)
    row = db.query(AISatisfactionCase).filter_by(case_id=made["case_id"]).one()
    row.snapshot_json += " "  # Lexical whitespace is canonicalized, not an original semantic change.
    db.commit()
    assert case_current(db, case["super_admin_user"], row.case_id, audit_only=True)["content_hash"] == made["content_hash"]
    snap = json.loads(row.snapshot_json)
    snap["collection"]["reviews"][0]["comment"] += "被篡改"
    row.snapshot_json = canonical_json(snap)
    db.commit()
    with pytest.raises(HTTPException) as error:
        case_current(db, case["super_admin_user"], row.case_id, audit_only=True)
    assert error.value.status_code == 409
    fake = copy.deepcopy(made["snapshot"]["collection"])
    fake["request"]["date_from"] = "2026-02-30"
    with pytest.raises(HTTPException):
        verify_capture(fake)
    assert verify_snapshot(made["snapshot"])["case_id"] == made["case_id"]
    assert project_snapshot(made["snapshot"], made)["safe_snapshot"] == made["safe_snapshot"]


def test_notes_unicode_bytes_and_revoke_codepoint_limits_are_exact():
    SourceRevoke(expected_revision=2, basis_note="🧪" * 1000)
    with pytest.raises(ValidationError):
        SourceRevoke(expected_revision=2, basis_note="x" * 1001)
    with pytest.raises(ValidationError):
        SourceReview(expected_revision=1, decision="publish", basis_note="🧪" * 1001)
    with pytest.raises(ValidationError):
        CaseCreate.model_validate({})
