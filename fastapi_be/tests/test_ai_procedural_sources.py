"""Perioperative AI uses exact surgery references and real team care, without inferring execution."""

import datetime
import uuid

import pytest
from fastapi import HTTPException

from app.ai.catalog import FEATURE_BY_KEY
from app.ai.clinical_tools import perioperative_timing
from app.ai.context import accessible_patients, authorize_patient, patient_snapshot
from app.models import Admission, AnesthesiaRecord, Doctor, PerioperativeAntibiotic, SurgeryApplication, SurgerySchedule, User


@pytest.fixture
def operative_case(seed_data, db_session):
    start = datetime.datetime(2026, 10, 20, 10)
    surgeon_user = User(username="surg-" + uuid.uuid4().hex[:12], password="test", user_role="doctor")
    db_session.add(surgeon_user)
    db_session.flush()
    surgeon = Doctor(name="测试主刀", user_id=surgeon_user.user_id, department_id=seed_data["department"].department_id)
    admission = Admission(patient_id=seed_data["patient"].patient_id, doctor_id=seed_data["doctor"].doctor_id, department_id=seed_data["department"].department_id, admission_time=start, status=1)
    db_session.add_all([surgeon, admission])
    db_session.flush()
    application = SurgeryApplication(
        patient_id=admission.patient_id,
        admission_id=admission.admission_id,
        doctor_id=seed_data["doctor"].doctor_id,
        surgery_name="隔离测试手术",
        preop_diagnosis="原始术前诊断",
        status=2,
        create_time=start,
    )
    db_session.add(application)
    db_session.flush()
    schedule = SurgerySchedule(
        patient_id=admission.patient_id,
        application_id=application.application_id,
        surgeon_id=surgeon.doctor_id,
        scrub_nurse_id=seed_data["nurse_user"].user_id,
        start_time=start,
        status=2,
        create_time=start,
    )
    medication = PerioperativeAntibiotic(
        patient_id=admission.patient_id,
        application_id=application.application_id,
        pharmaceutical_id=seed_data["pharmaceutical"].pharmaceutical_id,
        prescriber_id=seed_data["doctor_user"].user_id,
        dose="原始用法文本",
        indication=seed_data["patient"].name + "的测试指征",
        status=1,
        administered_time=start - datetime.timedelta(minutes=60),
        create_time=start,
    )
    db_session.add_all([schedule, medication])
    db_session.commit()
    return admission, application, schedule, medication, surgeon_user


def snapshot(db_session, seed_data, case, **refs):
    admission, application, _, _, _ = case
    return patient_snapshot(
        db_session, seed_data["doctor_user"], FEATURE_BY_KEY["perioperative_antibiotics"], admission.patient_id, admission.admission_id, {"surgery_application_id": application.application_id, **refs}
    )


def test_procedure_sources_preserve_raw_dose_and_statistical_reference_without_confirming_diagnosis(seed_data, db_session, operative_case):
    bundle = snapshot(db_session, seed_data, operative_case)
    assert bundle.data["current_confirmed_diagnoses"] == []
    assert bundle.data["surgery_applications"][0]["preop_diagnosis"] == "原始术前诊断"
    assert bundle.data["perioperative_antibiotics"][0]["dose_text"] == "原始用法文本"
    assert seed_data["patient"].name not in bundle.data["perioperative_antibiotics"][0]["indication"]
    assessment = perioperative_timing(bundle.data)
    assert assessment["results"][0]["minutes_before_start"] == 60
    assert assessment["results"][0]["within_existing_window"] is True
    assert assessment["results"][0]["clinical_appropriateness"] is None
    assert assessment["actions_executed"] == []


def test_planned_cancelled_or_unstarted_records_are_not_invented_as_administered(seed_data, db_session, operative_case):
    _, _, schedule, medication, _ = operative_case
    for status in (0, 2):
        medication.status = status
        db_session.commit()
        assert perioperative_timing(snapshot(db_session, seed_data, operative_case).data)["results"][0]["status"] == "not_evaluated"
    medication.status = 1
    schedule.status = 0
    db_session.commit()
    result = perioperative_timing(snapshot(db_session, seed_data, operative_case, surgery_schedule_id=schedule.schedule_id).data)["results"][0]
    assert result["status"] == "not_evaluated"
    assert result["within_existing_window"] is None


def test_multiple_schedules_require_explicit_pairing(seed_data, db_session, operative_case):
    admission, application, selected, _, _ = operative_case
    db_session.add(
        SurgerySchedule(
            patient_id=admission.patient_id, application_id=application.application_id, start_time=selected.start_time + datetime.timedelta(hours=4), status=2, create_time=selected.create_time
        )
    )
    db_session.commit()
    ambiguous = perioperative_timing(snapshot(db_session, seed_data, operative_case).data)["results"][0]
    assert ambiguous["status"] == "not_evaluated"
    chosen = perioperative_timing(snapshot(db_session, seed_data, operative_case, surgery_schedule_id=selected.schedule_id).data)["results"][0]
    assert chosen["within_existing_window"] is True
    assert "surgery-schedule:" + selected.schedule_id in chosen["source_ids"]


def test_team_care_is_limited_to_the_assigned_admission_and_revoked_when_cancelled(seed_data, db_session, operative_case):
    admission, application, schedule, _, surgeon_user = operative_case
    spec = FEATURE_BY_KEY["perioperative_assessment"]
    assert admission.patient_id in {row.patient_id for row in accessible_patients(db_session, surgeon_user, spec)}
    assert authorize_patient(db_session, surgeon_user, admission.patient_id, "inpatient", admission.admission_id)
    assert authorize_patient(db_session, seed_data["nurse_user"], admission.patient_id, "inpatient", admission.admission_id)
    other = Admission(patient_id=admission.patient_id, doctor_id=admission.doctor_id, department_id=admission.department_id, status=1, admission_time=admission.admission_time)
    db_session.add(other)
    db_session.commit()
    for actor in (surgeon_user, seed_data["nurse_user"]):
        with pytest.raises(HTTPException) as foreign:
            authorize_patient(db_session, actor, admission.patient_id, "inpatient", other.admission_id)
        assert foreign.value.status_code == 403
    schedule.status = 3
    db_session.commit()
    with pytest.raises(HTTPException):
        authorize_patient(db_session, surgeon_user, admission.patient_id, "inpatient", admission.admission_id)
    assert application.doctor_id != db_session.query(Doctor).filter_by(user_id=surgeon_user.user_id).one().doctor_id


def test_selected_surgery_cannot_be_combined_with_another_admission(seed_data, db_session, operative_case):
    admission, application, _, _, _ = operative_case
    other = Admission(patient_id=admission.patient_id, doctor_id=admission.doctor_id, department_id=admission.department_id, status=1, admission_time=admission.admission_time)
    db_session.add(other)
    db_session.commit()
    with pytest.raises(HTTPException) as mismatch:
        patient_snapshot(
            db_session, seed_data["doctor_user"], FEATURE_BY_KEY["perioperative_antibiotics"], admission.patient_id, other.admission_id, {"surgery_application_id": application.application_id}
        )
    assert mismatch.value.status_code == 422


def test_legacy_anesthesia_defaults_are_explicitly_ambiguous(seed_data, db_session, operative_case):
    admission, _, schedule, _, _ = operative_case
    db_session.add(AnesthesiaRecord(patient_id=admission.patient_id, schedule_id=schedule.schedule_id, create_time=schedule.create_time))
    db_session.commit()
    data = snapshot(db_session, seed_data, operative_case).data["anesthesia_records"][0]
    assert data["blood_loss"] == 0
    assert set(data["legacy_zero_ambiguous_fields"]) == {"blood_loss", "urine_output", "fluid_input"}
