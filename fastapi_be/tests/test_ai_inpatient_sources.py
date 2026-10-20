"""Source connectors preserve admission and medication workflow boundaries."""

import datetime

import pytest

from app.ai.catalog import FEATURE_BY_KEY
from app.ai.context import patient_snapshot
from app.ai.governance import encode_json
from app.models import Admission, DischargeSummary, InpatientOrder, InpatientOrderItem, MedicationAdministration, NursingAssessment, NursingRecord, OrderExecution, ProgressNote


@pytest.fixture
def admissions(seed_data, db_session):
    now = datetime.datetime.now()
    rows = [
        Admission(patient_id=seed_data["patient"].patient_id, doctor_id=seed_data["doctor"].doctor_id, department_id=seed_data["department"].department_id, status=1, admission_time=now)
        for _ in range(2)
    ]
    db_session.add_all(rows)
    db_session.commit()
    return rows


def test_selected_admission_filters_notes_and_preserves_stopped_orders(seed_data, db_session, admissions):
    current, other = admissions
    now = datetime.datetime.now()
    db_session.add_all(
        [
            ProgressNote(admission_id=current.admission_id, patient_id=current.patient_id, doctor_id=current.doctor_id, content="本次住院记录", record_time=now, create_time=now),
            ProgressNote(admission_id=other.admission_id, patient_id=other.patient_id, doctor_id=other.doctor_id, content="他次住院不应出现", record_time=now, create_time=now),
        ]
    )
    order = InpatientOrder(patient_id=current.patient_id, admission_id=current.admission_id, doctor_id=current.doctor_id, category="drug", status=3, start_time=now, stop_time=now, create_time=now)
    order.items.append(InpatientOrderItem(item_name="测试药品", item_type="drug", dose="原始用法文本", unit="盒", frequency="未知频次"))
    db_session.add(order)
    db_session.commit()
    bundle = patient_snapshot(db_session, seed_data["doctor_user"], FEATURE_BY_KEY["progress_note"], current.patient_id, current.admission_id)
    serialized = encode_json({"data": bundle.data, "evidence": bundle.evidence})
    assert "本次住院记录" in serialized
    assert "他次住院不应出现" not in serialized
    assert bundle.data["inpatient_orders"][0]["status_meaning"] == "已停止"
    assert bundle.data["inpatient_orders"][0]["items"][0]["dose"] == "原始用法文本"


def test_verification_does_not_become_administration_and_barcodes_are_not_exported(seed_data, db_session, admissions):
    current = admissions[0]
    now = datetime.datetime.now()
    order = InpatientOrder(patient_id=current.patient_id, admission_id=current.admission_id, doctor_id=current.doctor_id, category="drug", status=2, start_time=now, create_time=now)
    db_session.add(order)
    db_session.flush()
    execution = OrderExecution(order_id=order.order_id, nurse_id=seed_data["nurse_user"].user_id, planned_time=now, status=0)
    db_session.add(execution)
    db_session.flush()
    administration = MedicationAdministration(
        execution_id=execution.execution_id,
        order_id=order.order_id,
        patient_id=current.patient_id,
        nurse_id=seed_data["nurse_user"].user_id,
        patient_barcode="sensitive-patient-barcode-test",
        medication_barcodes_json='["sensitive-drug-barcode-test"]',
        status=1,
        verified_at=now,
    )
    db_session.add(administration)
    db_session.commit()
    bundle = patient_snapshot(db_session, seed_data["doctor_user"], FEATURE_BY_KEY["medication_reconciliation"], current.patient_id, current.admission_id)
    assert bundle.data["medication_administrations"][0]["recorded_as_administered"] is False
    assert bundle.data["order_executions"][0]["status_meaning"] == "待执行"
    assert "sensitive-patient-barcode-test" not in encode_json(bundle.data)
    assert "sensitive-drug-barcode-test" not in encode_json(bundle.evidence)
    administration.status = 2
    administration.administration_time = now
    db_session.commit()
    after = patient_snapshot(db_session, seed_data["doctor_user"], FEATURE_BY_KEY["medication_reconciliation"], current.patient_id, current.admission_id)
    assert after.data["medication_administrations"][0]["recorded_as_administered"] is True


def test_nursing_drafts_are_excluded_and_patients_cannot_use_ai_to_read_staff_working_notes(seed_data, db_session, admissions):
    current = admissions[0]
    now = datetime.datetime.now()
    db_session.add(
        NursingRecord(patient_id=current.patient_id, admission_id=current.admission_id, nurse_id=seed_data["nurse_user"].user_id, record_time=now, note="仅医护工作记录内容", create_time=now)
    )
    db_session.add(
        NursingAssessment(
            patient_id=current.patient_id,
            admission_id=current.admission_id,
            nurse_id=seed_data["nurse_user"].user_id,
            adl_score=20,
            status=0,
            note="护理评估草稿内容",
            create_time=now,
            update_time=now,
        )
    )
    db_session.commit()
    clinical = patient_snapshot(db_session, seed_data["doctor_user"], FEATURE_BY_KEY["nursing_risk_assessment"], current.patient_id, current.admission_id)
    assert clinical.data["nursing_records"][0]["note"] == "仅医护工作记录内容"
    assert clinical.data["completed_nursing_assessments"] == []
    patient = patient_snapshot(db_session, seed_data["patient_user"], FEATURE_BY_KEY["rehabilitation_care"], current.patient_id, current.admission_id)
    assert "仅医护工作记录内容" not in encode_json(patient.data)
    assert "护理评估草稿内容" not in encode_json(patient.evidence)


def test_discharge_instructions_reach_patient_only_for_a_discharged_admission(seed_data, db_session, admissions):
    current = admissions[0]
    db_session.add(
        DischargeSummary(
            admission_id=current.admission_id, patient_id=current.patient_id, doctor_id=current.doctor_id, discharge_instruction="已记录的出院指导原文", create_time=datetime.datetime.now()
        )
    )
    db_session.commit()
    spec = FEATURE_BY_KEY["rehabilitation_care"]
    before = patient_snapshot(db_session, seed_data["patient_user"], spec, current.patient_id, current.admission_id)
    assert "discharge_summaries" not in before.data
    current.status = 2
    db_session.commit()
    after = patient_snapshot(db_session, seed_data["patient_user"], spec, current.patient_id, current.admission_id)
    assert after.data["discharge_summaries"][0]["discharge_instruction"] == "已记录的出院指导原文"
