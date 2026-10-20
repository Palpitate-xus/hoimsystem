"""A responsible physician must explicitly verify diagnoses used by treatment assistance."""

import datetime
from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from alembic import command
from app.ai.catalog import FEATURE_BY_KEY
from app.ai.context import patient_snapshot
from app.models import Admission, ClinicalDiagnosisReview, Registration, StructuredMedicalRecord


def signed_record(seed_data, db_session):
    record = seed_data["medical_record"]
    encounter = Registration(patient_id=record.patient_id, doctor_id=record.doctor_id, department_id=seed_data["department"].department_id, time=datetime.datetime.now(), status=1)
    db_session.add(encounter)
    db_session.flush()
    record.registration_uuid = encounter.registration_uuid
    record.status = 1
    record.sign_time = datetime.datetime.now()
    db_session.commit()
    return record, encounter


@pytest.mark.asyncio
async def test_signed_text_is_not_confirmed_until_explicit_review_and_can_be_withdrawn(async_client, seed_data, auth_headers, db_session):
    record, encounter = signed_record(seed_data, db_session)
    original = (record.result, record.status, record.sign_time)
    params = {"source_kind": "outpatient", "source_id": record.medical_record_id}
    headers = auth_headers(seed_data["doctor_user"].username)
    first = await async_client.get("/api/clinicalDiagnosis/review", headers=headers, params=params)
    assert first.status_code == 200, first.text
    source = first.json()["data"]
    assert source["certainty"] == "unknown"
    assert source["revision"] == 0
    body = {**params, "source_hash": source["source_hash"], "expected_revision": 0, "certainty": "confirmed", "reason": "测试责任医生已逐项确认原记录诊断"}
    confirmed = await async_client.post("/api/clinicalDiagnosis/review", headers=headers, json=body)
    assert confirmed.status_code == 200, confirmed.text
    bundle = patient_snapshot(db_session, seed_data["doctor_user"], FEATURE_BY_KEY["treatment_pathway"], record.patient_id, encounter.registration_uuid)
    assert bundle.data["current_confirmed_diagnoses"] == [record.result]
    assert bundle.data["diagnosis_reviews"][0]["certainty"] == "confirmed"
    stale_write = await async_client.post("/api/clinicalDiagnosis/review", headers=headers, json=body)
    assert stale_write.status_code == 409
    withdrawn = await async_client.post("/api/clinicalDiagnosis/review", headers=headers, json={**body, "expected_revision": 1, "certainty": "suspected", "reason": "测试新增信息后改为尚待确认的诊断"})
    assert withdrawn.status_code == 200
    bundle = patient_snapshot(db_session, seed_data["doctor_user"], FEATURE_BY_KEY["treatment_pathway"], record.patient_id, encounter.registration_uuid)
    assert bundle.data["current_confirmed_diagnoses"] == []
    assert db_session.query(ClinicalDiagnosisReview).filter_by(source_id=record.medical_record_id).count() == 2
    db_session.refresh(record)
    assert (record.result, record.status, record.sign_time) == original


@pytest.mark.asyncio
async def test_changed_source_invalidates_prior_assertion_and_stale_submission(async_client, seed_data, auth_headers, db_session):
    record, encounter = signed_record(seed_data, db_session)
    headers = auth_headers(seed_data["doctor_user"].username)
    params = {"source_kind": "outpatient", "source_id": record.medical_record_id}
    source = (await async_client.get("/api/clinicalDiagnosis/review", headers=headers, params=params)).json()["data"]
    body = {**params, "source_hash": source["source_hash"], "expected_revision": 0, "certainty": "confirmed", "reason": "测试原始版本责任医生确认记录"}
    assert (await async_client.post("/api/clinicalDiagnosis/review", headers=headers, json=body)).status_code == 200
    # Simulate an external data correction; signed narrative is never edited by the review API.
    record.result = "经外部订正后的诊断原文"
    db_session.commit()
    bundle = patient_snapshot(db_session, seed_data["doctor_user"], FEATURE_BY_KEY["treatment_pathway"], record.patient_id, encounter.registration_uuid)
    assert bundle.data["current_confirmed_diagnoses"] == []
    assert bundle.data["diagnosis_reviews"][0]["certainty"] == "stale"
    rejected = await async_client.post("/api/clinicalDiagnosis/review", headers=headers, json={**body, "expected_revision": 1})
    assert rejected.status_code == 409


@pytest.mark.asyncio
async def test_only_responsible_physician_can_review_and_unsigned_records_cannot_be_confirmed(async_client, seed_data, auth_headers, db_session):
    record = seed_data["medical_record"]
    record.status = 0
    db_session.commit()
    params = {"source_kind": "outpatient", "source_id": record.medical_record_id}
    for role in ("admin_user", "super_admin_user", "director_user", "patient_user", "nurse_user"):
        denied = await async_client.get("/api/clinicalDiagnosis/review", headers=auth_headers(seed_data[role].username), params=params)
        assert denied.status_code == 403
    headers = auth_headers(seed_data["doctor_user"].username)
    source = (await async_client.get("/api/clinicalDiagnosis/review", headers=headers, params=params)).json()["data"]
    response = await async_client.post(
        "/api/clinicalDiagnosis/review", headers=headers, json={**params, "source_hash": source["source_hash"], "expected_revision": 0, "certainty": "confirmed", "reason": "测试草稿不能作为确认依据"}
    )
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_structured_review_is_bound_to_its_actual_admission(async_client, seed_data, auth_headers, db_session):
    admission = Admission(
        patient_id=seed_data["patient"].patient_id, doctor_id=seed_data["doctor"].doctor_id, department_id=seed_data["department"].department_id, status=1, admission_time=datetime.datetime.now()
    )
    db_session.add(admission)
    db_session.flush()
    record = StructuredMedicalRecord(
        patient_id=admission.patient_id,
        doctor_id=admission.doctor_id,
        admission_id=admission.admission_id,
        diagnosis="测试住院诊断",
        status=1,
        sign_time=datetime.datetime.now(),
        create_time=datetime.datetime.now(),
    )
    db_session.add(record)
    db_session.commit()
    params = {"source_kind": "structured", "source_id": record.record_id}
    headers = auth_headers(seed_data["doctor_user"].username)
    source = (await async_client.get("/api/clinicalDiagnosis/review", headers=headers, params=params)).json()["data"]
    response = await async_client.post(
        "/api/clinicalDiagnosis/review",
        headers=headers,
        json={**params, "source_hash": source["source_hash"], "expected_revision": 0, "certainty": "confirmed", "reason": "测试主管医生确认本次住院诊断"},
    )
    assert response.status_code == 200, response.text
    current = patient_snapshot(db_session, seed_data["doctor_user"], FEATURE_BY_KEY["treatment_pathway"], admission.patient_id, admission.admission_id)
    assert record.diagnosis in current.data["current_confirmed_diagnoses"]
    historical = patient_snapshot(db_session, seed_data["doctor_user"], FEATURE_BY_KEY["patient_summary"], admission.patient_id)
    assert historical.data["current_confirmed_diagnoses"] == []


def test_diagnosis_review_migration_does_not_assume_legacy_certainty(tmp_path):
    url = f"sqlite:///{tmp_path / 'diagnosis-reviews.db'}"
    engine = create_engine(url)
    with engine.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE hoimsystem_patient (patient_id INTEGER PRIMARY KEY)")
        conn.exec_driver_sql("CREATE TABLE hoimsystem_users (user_id INTEGER PRIMARY KEY)")
        conn.exec_driver_sql("CREATE TABLE hoimsystem_medical_record (result TEXT)")
        conn.exec_driver_sql("INSERT INTO hoimsystem_medical_record VALUES ('疑似诊断原文')")
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", url)
    command.stamp(config, "20261020_lab_observations")
    command.upgrade(config, "20261020_diagnosis_review")
    with engine.connect() as conn:
        assert conn.scalar(text("SELECT count(*) FROM hoimsystem_clinical_diagnosis_review")) == 0
        assert conn.scalar(text("SELECT result FROM hoimsystem_medical_record")) == "疑似诊断原文"
    command.downgrade(config, "20261020_lab_observations")
    assert "hoimsystem_clinical_diagnosis_review" not in inspect(engine).get_table_names()
    engine.dispose()
