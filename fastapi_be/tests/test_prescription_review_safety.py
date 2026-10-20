"""Recheck saved dose and current patient conditions at both pharmacy state transitions."""

import datetime
import json
from decimal import Decimal

import pytest

from app.models import Charge, PatientAllergy, PatientClinicalProfile, Pharmaceutical, PrescriptionReviewRule


@pytest.fixture(autouse=True)
def isolate_review_rules(db_session):
    db_session.query(PrescriptionReviewRule).delete()
    db_session.query(PatientClinicalProfile).delete()
    db_session.query(PatientAllergy).delete()
    db_session.commit()


def rule(seed_data, **kwargs):
    values = {"drug_a": seed_data["pharmaceutical"].name, "severity": 3, "status": 1, "source": "隔离测试规则", "version": "test-v1", "create_time": datetime.datetime.now()}
    values.update(kwargs)
    return PrescriptionReviewRule(**values)


async def assert_both_transitions_block(async_client, seed_data, auth_headers, db_session, message):
    pre = seed_data["prescription"]
    headers = auth_headers(seed_data["pharmacist_user"].username)
    pre.status = 0
    db_session.commit()
    response = await async_client.post("/api/pharmacy/audit", headers=headers, json={"prescription_id": pre.prescription_id})
    assert response.status_code == 400, response.text
    assert message in response.json()["msg"]
    db_session.refresh(pre)
    assert pre.status == 0
    # Simulate a prior completed audit, followed by a clinical/rule change before dispensing.
    pre.status = 1
    db_session.query(Charge).filter_by(prescription_id=pre.prescription_id).update({"status": 1})
    db_session.commit()
    stock = db_session.get(Pharmaceutical, seed_data["pharmaceutical"].pharmaceutical_id).stock
    response = await async_client.post("/api/pharmacy/dispense", headers=headers, json={"prescription_id": pre.prescription_id})
    assert response.status_code == 400, response.text
    assert message in response.json()["msg"]
    db_session.refresh(pre)
    assert pre.status == 1
    assert db_session.get(Pharmaceutical, seed_data["pharmaceutical"].pharmaceutical_id).stock == stock


@pytest.mark.asyncio
async def test_saved_dose_and_frequency_are_rechecked(async_client, seed_data, auth_headers, db_session):
    line = seed_data["prescription"].pre_phas[0]
    line.dosage = Decimal("10")
    line.dose_unit = "mg"
    line.frequency = "bid"
    db_session.add(rule(seed_data, rule_type="dose", dose_unit="mg", max_daily_dose=15, message="测试每日剂量限制"))
    db_session.commit()
    await assert_both_transitions_block(async_client, seed_data, auth_headers, db_session, "测试每日剂量限制")


@pytest.mark.asyncio
async def test_current_patient_profile_is_rechecked(async_client, seed_data, auth_headers, db_session):
    db_session.add(
        PatientClinicalProfile(
            patient_id=seed_data["patient"].patient_id, egfr=Decimal("25"), diagnoses_json="[]", labs_json="{}", updated_by=seed_data["doctor_user"].user_id, update_time=datetime.datetime.now()
        )
    )
    db_session.add(rule(seed_data, rule_type="context", condition_json=json.dumps({"max_egfr": 30}), message="测试患者条件变化"))
    db_session.commit()
    await assert_both_transitions_block(async_client, seed_data, auth_headers, db_session, "测试患者条件变化")


@pytest.mark.asyncio
async def test_structured_allergy_is_part_of_the_same_review(async_client, seed_data, auth_headers, db_session):
    seed_data["patient"].allergy_history = ""
    db_session.add(
        PatientAllergy(
            patient_id=seed_data["patient"].patient_id,
            allergen=seed_data["pharmaceutical"].name,
            reaction="测试反应",
            severity=3,
            reporter_id=seed_data["doctor_user"].user_id,
            create_time=datetime.datetime.now(),
            update_time=datetime.datetime.now(),
        )
    )
    db_session.add(rule(seed_data, rule_type="allergy_key", message="测试结构化过敏拦截"))
    db_session.commit()
    await assert_both_transitions_block(async_client, seed_data, auth_headers, db_session, "测试结构化过敏拦截")


@pytest.mark.asyncio
async def test_review_engine_failure_cannot_advance_pharmacy_state(async_client, seed_data, auth_headers, db_session, monkeypatch):
    import app.rx_review_engine as engine

    def unavailable(*args, **kwargs):
        raise RuntimeError("sensitive-test-details")

    monkeypatch.setattr(engine, "check_prescription", unavailable)
    await assert_both_transitions_block(async_client, seed_data, auth_headers, db_session, "安全检查暂不可用")
