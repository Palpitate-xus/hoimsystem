"""A clicked business row must remain in the bounded, authorized AI snapshot."""

import datetime

import pytest
from fastapi import HTTPException

from app.ai.catalog import FEATURE_BY_KEY
from app.ai.context import patient_snapshot
from app.models import LabOrder, LabResult, MedicalRecord


def test_explicit_old_record_survives_recent_history_limit(seed_data, db_session):
    old = MedicalRecord(
        patient_id=seed_data["patient"].patient_id,
        doctor_id=seed_data["doctor"].doctor_id,
        consultation_time=datetime.datetime(2000, 1, 1),
        symptom="所选旧记录",
        result="历史诊断",
        status=1,
    )
    db_session.add(old)
    db_session.add_all(
        MedicalRecord(patient_id=old.patient_id, doctor_id=old.doctor_id, consultation_time=datetime.datetime(2020, 1, 1) + datetime.timedelta(days=i), symptom="近期记录", result="既往记录", status=1)
        for i in range(20)
    )
    db_session.commit()
    bundle = patient_snapshot(db_session, seed_data["doctor_user"], FEATURE_BY_KEY["record_quality"], old.patient_id, source_refs={"record_id": old.medical_record_id})
    assert bundle.data["outpatient_records"][0]["source_id"] == "outpatient:" + old.medical_record_id
    assert bundle.data["current_confirmed_diagnoses"] == []
    assert any(item["source"] == "门诊病历" for item in bundle.data["truncated_sources"])
    assert len(bundle.data["outpatient_records"]) == 15


def test_foreign_row_or_unreviewed_lab_selection_is_rejected(seed_data, db_session):
    with pytest.raises(HTTPException) as foreign:
        patient_snapshot(
            db_session, seed_data["super_admin_user"], FEATURE_BY_KEY["record_quality"], seed_data["patient2"].patient_id, source_refs={"record_id": seed_data["medical_record"].medical_record_id}
        )
    assert foreign.value.status_code == 404
    order = LabOrder(patient_id=seed_data["patient"].patient_id, doctor_id=seed_data["doctor"].doctor_id, check_type="待审核测试", create_time=datetime.datetime.now())
    db_session.add(order)
    db_session.flush()
    report = LabResult(lab_order_id=order.lab_order_id, result="未审核检验原文", audit_status=0, report_time=datetime.datetime.now())
    db_session.add(report)
    db_session.commit()
    with pytest.raises(HTTPException) as pending:
        patient_snapshot(db_session, seed_data["doctor_user"], FEATURE_BY_KEY["lab_interpretation"], order.patient_id, source_refs={"lab_result_id": report.lab_result_id})
    assert pending.value.status_code == 409


def test_patient_snapshot_omits_unsigned_record_even_without_explicit_selection(seed_data, db_session):
    record = seed_data["medical_record"]
    record.status = 0
    db_session.commit()
    spec = FEATURE_BY_KEY["patient_report_explanation"]
    bundle = patient_snapshot(db_session, seed_data["patient_user"], spec, record.patient_id)
    assert "outpatient:" + record.medical_record_id not in {item["source_id"] for item in bundle.evidence}
    with pytest.raises(HTTPException) as unsigned:
        patient_snapshot(db_session, seed_data["patient_user"], spec, record.patient_id, source_refs={"record_id": record.medical_record_id})
    assert unsigned.value.status_code == 403


@pytest.mark.asyncio
async def test_context_preview_uses_the_same_explicit_row_selection(async_client, seed_data, auth_headers):
    record = seed_data["medical_record"]
    response = await async_client.get(
        "/api/ai/context",
        headers=auth_headers(seed_data["doctor_user"].username),
        params={"feature_key": "record_quality", "patient_id": record.patient_id, "record_id": record.medical_record_id},
    )
    assert response.status_code == 200, response.text
    assert response.json()["data"]["context"]["selected_sources"] == {"record_id": record.medical_record_id}
