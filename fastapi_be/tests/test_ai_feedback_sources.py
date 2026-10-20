"""Ratings are scoped through verified visit links, without comment disclosure or false denominators."""

import datetime
import uuid

import pytest
from fastapi import HTTPException

from app.ai.catalog import FEATURE_BY_KEY
from app.ai.governance import encode_json
from app.ai.operational_sources import operational_context
from app.models import Department, Doctor, MedicalRecord, Registration, Review


@pytest.fixture
def rating_case(seed_data, db_session):
    db_session.query(Review).delete()
    foreign = Department(name="评价范围外" + uuid.uuid4().hex[:6])
    db_session.add(foreign)
    db_session.flush()
    doctor = Doctor(name="评价原医生", department_id=foreign.department_id)
    db_session.add(doctor)
    db_session.flush()
    now = datetime.datetime.now()
    visits = []
    for index, score in enumerate((1, 5, None, 99, 4)):
        registration = Registration(
            patient_id=seed_data["patient"].patient_id, doctor_id=doctor.doctor_id, department_id=seed_data["department"].department_id if index < 4 else foreign.department_id, time=now
        )
        db_session.add(registration)
        db_session.flush()
        visit = MedicalRecord(patient_id=registration.patient_id, doctor_id=doctor.doctor_id, registration_uuid=registration.registration_uuid)
        db_session.add(visit)
        db_session.flush()
        db_session.add(
            Review(patient_id=visit.patient_id, doctor_id=doctor.doctor_id, visit_id=visit.medical_record_id, score=score, comment="患者姓名、电话13800138000和地址不进入模型", review_time=now)
        )
        visits.append(visit)
    # Patient and physician mismatches, orphan visit, and invalid registration links must be excluded.
    db_session.add_all(
        [
            Review(patient_id=seed_data["patient2"].patient_id, doctor_id=doctor.doctor_id, visit_id=visits[0].medical_record_id, score=5, review_time=now),
            Review(patient_id=seed_data["patient"].patient_id, doctor_id=seed_data["doctor"].doctor_id, visit_id=visits[0].medical_record_id, score=5, review_time=now),
            Review(patient_id=seed_data["patient"].patient_id, doctor_id=doctor.doctor_id, visit_id="nonexistent", score=5, review_time=now),
        ]
    )
    broken = MedicalRecord(patient_id=seed_data["patient2"].patient_id, doctor_id=doctor.doctor_id, registration_uuid=visits[0].registration_uuid)
    db_session.add(broken)
    db_session.flush()
    db_session.add(Review(patient_id=broken.patient_id, doctor_id=doctor.doctor_id, visit_id=broken.medical_record_id, score=5, review_time=now))
    db_session.commit()
    return now, visits, doctor


def snapshot(db_session, seed_data, user=None, **values):
    return operational_context(db_session, user or seed_data["director_user"], FEATURE_BY_KEY["feedback_analysis"], {"department_id": seed_data["department"].department_id, **values})


def test_original_registration_department_controls_scope_and_no_text_or_individual_ids_leave_source(seed_data, db_session, rating_case):
    bundle = snapshot(db_session, seed_data)
    summary = bundle.data["feedback_rating_summary"]
    assert summary["record_count"] == 4
    assert summary["distinct_recorded_visit_count"] == 4
    assert summary["valid_score_record_count"] == 2
    assert summary["mean_recorded_score"] == 3
    assert summary["out_of_range_score_record_count"] == 1
    assert summary["withheld_comment_record_count"] == 4
    serialized = encode_json({"context": bundle.data, "evidence": bundle.evidence})
    for forbidden in ("13800138000", "患者姓名、电话", "评价原医生", "patient_id", "doctor_id", "review_id", "visit_id", seed_data["patient"].identity):
        assert forbidden not in serialized
    assert any("不能生成投诉主题" in text for text in bundle.data["missing_data"])


def test_missing_out_of_range_and_unobserved_days_are_not_zero_filled(seed_data, db_session, rating_case):
    now, _, _ = rating_case
    bundle = snapshot(db_session, seed_data, date_from=str(now.date() - datetime.timedelta(days=2)))
    series = bundle.data["feedback_rating_series"]
    rows = [dict(zip(series["columns"], row)) for row in series["rows"]]
    assert len(rows) == 3 and {row["date"] for row in rows} == {str(now.date())}
    unknown = next(row for row in rows if row["recorded_score"] is None)
    assert unknown["record_count"] == 2 and unknown["out_of_range_score_record_count"] == 1
    for review in db_session.query(Review).all():
        review.review_time = now - datetime.timedelta(days=90)
    db_session.commit()
    empty = snapshot(db_session, seed_data).data["feedback_rating_summary"]
    assert empty["record_count"] == 0 and empty["mean_recorded_score"] is None


def test_hospital_summary_includes_verified_other_department_but_dept_role_cannot_request_it(seed_data, db_session, rating_case):
    bundle = snapshot(db_session, seed_data, user=seed_data["super_admin_user"], department_id=None)
    assert bundle.data["feedback_rating_summary"]["record_count"] == 5
    with pytest.raises(HTTPException) as error:
        snapshot(db_session, seed_data, department_id=rating_case[2].department_id)
    assert error.value.status_code == 403


def test_current_doctor_department_only_applies_when_no_registration_was_recorded(seed_data, db_session, rating_case):
    now, visits, doctor = rating_case
    visits[0].registration_uuid = None
    db_session.commit()
    assert snapshot(db_session, seed_data).data["feedback_rating_summary"]["record_count"] == 3
    doctor.department_id = seed_data["department"].department_id
    db_session.commit()
    assert snapshot(db_session, seed_data).data["feedback_rating_summary"]["record_count"] == 4
