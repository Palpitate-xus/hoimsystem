"""Outpatient billing uses verified ownership and source facts, never payment tokens or price guesses."""

import datetime
import json
import uuid
from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.ai.billing_sources import billing_reconciliation
from app.ai.catalog import FEATURE_BY_KEY
from app.ai.context import patient_snapshot
from app.ai.governance import encode_json
from app.ai.models import AIPatientGrant, AIRun, utcnow
from app.ai.runtime import authorize_run
from app.models import Admission, Charge, Department, Invoice, Patient, Payment, Prescription, Registration


@pytest.fixture
def outpatient_bills(seed_data, db_session):
    now = datetime.datetime.now()
    patient_id = seed_data["patient"].patient_id
    registration = Registration(patient_id=patient_id, doctor_id=seed_data["doctor"].doctor_id, department_id=seed_data["department"].department_id, status=0, time=now)
    other = Registration(patient_id=patient_id, doctor_id=seed_data["doctor"].doctor_id, department_id=seed_data["department"].department_id, status=0, time=now)
    db_session.add_all([registration, other])
    db_session.flush()
    charges = [
        Charge(registration_uuid=registration.registration_uuid, charge_type="registration", amount=Decimal(amount), status=status, charge_time=now)
        for amount, status in (("10.00", 1), ("20.00", 0), ("30.00", 2))
    ]
    other_charge = Charge(registration_uuid=other.registration_uuid, charge_type="registration", amount=Decimal("40.00"), status=1, charge_time=now)
    db_session.add_all([*charges, other_charge])
    db_session.flush()
    for charge in charges[1:]:
        db_session.add(
            Payment(
                payment_no="AI-TEST-" + uuid.uuid4().hex[:20],
                charge_id=charge.charge_id,
                amount=charge.amount,
                status=1,
                channel="cash",
                paid_time=now,
                create_time=now,
                qr_code_data="sensitive-qr-test",
                external_payment_id="sensitive-external-test",
            )
        )
    invoice = Invoice(charge_id=charges[2].charge_id, invoice_no="sensitive-invoice-no", amount=charges[2].amount, status=0, invoice_time=now)
    db_session.add(invoice)
    db_session.commit()
    return registration, other, charges, other_charge, invoice


def snapshot(db_session, seed_data, registration, **references):
    return patient_snapshot(db_session, seed_data["super_admin_user"], FEATURE_BY_KEY["charge_reconciliation"], registration.patient_id, registration.registration_uuid, references)


def test_current_visit_excludes_other_visit_and_retains_original_payment_invoice_conflicts(seed_data, db_session, outpatient_bills):
    registration, _, charges, other_charge, invoice = outpatient_bills
    bundle = snapshot(db_session, seed_data, registration)
    serialized = encode_json({"data": bundle.data, "evidence": bundle.evidence})
    assert {row["charge_id"] for row in bundle.data["outpatient_charges"]} == {row.charge_id for row in charges}
    assert other_charge.charge_id not in serialized
    for value in ("sensitive-qr-test", "sensitive-external-test", "sensitive-invoice-no"):
        assert value not in serialized
    results = billing_reconciliation(bundle.data)
    checks = {row["charge_id"]: row for row in results["outpatient_checks"]}
    assert any("不能判为未支付" in value for value in checks[charges[0].charge_id]["findings"])
    assert any("存在成功支付流水" in value for value in checks[charges[1].charge_id]["findings"])
    assert any("未作废票据" in value for value in checks[charges[2].charge_id]["findings"])
    assert checks[charges[2].charge_id]["payment_status_totals"][0]["amount_sum"] == "30.00"
    assert results["changes_written"] == []
    db_session.refresh(invoice)
    assert invoice.status == 0
    assert [db_session.get(Charge, row.charge_id).status for row in charges] == [1, 0, 2]


def test_registration_only_charge_is_supported_but_cannot_bind_to_another_visit(seed_data, db_session, outpatient_bills):
    registration, other, charges, _, _ = outpatient_bills
    selected = snapshot(db_session, seed_data, registration, outpatient_charge_id=charges[0].charge_id)
    assert len(selected.data["outpatient_charges"]) == 1
    with pytest.raises(HTTPException) as mismatch:
        snapshot(db_session, seed_data, other, outpatient_charge_id=charges[0].charge_id)
    assert mismatch.value.status_code == 422


def test_legacy_prescription_charge_without_saved_visit_is_not_assigned_by_date(seed_data, db_session, outpatient_bills):
    registration, _, _, _, _ = outpatient_bills
    charge = seed_data["charge"]
    with pytest.raises(HTTPException) as mismatch:
        snapshot(db_session, seed_data, registration, outpatient_charge_id=charge.charge_id)
    assert mismatch.value.status_code == 422
    selected = patient_snapshot(db_session, seed_data["super_admin_user"], FEATURE_BY_KEY["charge_reconciliation"], registration.patient_id, None, {"outpatient_charge_id": charge.charge_id})
    assert selected.data["billing_scope"]["registration_uuid"] is None
    assert [row["charge_id"] for row in selected.data["outpatient_charges"]] == [charge.charge_id]


@pytest.mark.asyncio
async def test_charge_list_exposes_real_patient_and_visit_binding_for_registration_only_charge(async_client, seed_data, auth_headers, outpatient_bills):
    registration, _, charges, _, _ = outpatient_bills
    response = await async_client.get("/api/chargeManagement/getList", headers=auth_headers(seed_data["admin_user"].username))
    assert response.status_code == 200, response.text
    row = next(item for item in response.json()["data"] if item["id"] == charges[0].charge_id)
    assert row["patient_id"] == registration.patient_id
    assert row["registration_uuid"] == registration.registration_uuid


def test_inconsistent_patient_joins_are_excluded_and_cannot_be_selected(seed_data, db_session, outpatient_bills):
    registration, _, _, _, _ = outpatient_bills
    foreign = Patient(name="其他收费患者", identity="AI-BILL-" + uuid.uuid4().hex)
    db_session.add(foreign)
    db_session.flush()
    prescription = Prescription(patient_id=foreign.patient_id, doctor_id=seed_data["doctor"].doctor_id, status=0, create_time=datetime.datetime.now())
    db_session.add(prescription)
    db_session.flush()
    charge = Charge(registration_uuid=registration.registration_uuid, prescription_id=prescription.prescription_id, amount=999, status=0, charge_time=datetime.datetime.now())
    db_session.add(charge)
    db_session.commit()
    bundle = snapshot(db_session, seed_data, registration)
    assert charge.charge_id not in encode_json(bundle.data)
    assert any("患者归属" in item for item in bundle.data["missing_data"])
    with pytest.raises(HTTPException) as denied:
        snapshot(db_session, seed_data, registration, outpatient_charge_id=charge.charge_id)
    assert denied.value.status_code == 404


def test_missing_payment_amount_is_not_treated_as_zero_or_successful_full_reconciliation(seed_data, db_session, outpatient_bills):
    registration, _, charges, _, _ = outpatient_bills
    charge = charges[0]
    db_session.add(Payment(payment_no="AI-NULL-" + uuid.uuid4().hex[:20], charge_id=charge.charge_id, amount=None, status=1, create_time=datetime.datetime.now()))
    db_session.commit()
    bundle = snapshot(db_session, seed_data, registration, outpatient_charge_id=charge.charge_id)
    check = billing_reconciliation(bundle.data)["outpatient_checks"][0]
    assert check["payment_status_totals"][0]["amount_sum"] is None
    assert any("缺失金额" in value for value in check["findings"])


def test_result_access_rechecks_actual_billing_encounter_even_when_caller_omitted_header(seed_data, db_session):
    now = datetime.datetime.now()
    director = seed_data["director_user"]
    patient_id = seed_data["patient"].patient_id
    # One historical encounter remains accessible; the frozen source was moved out of this scope.
    own = Admission(patient_id=patient_id, doctor_id=seed_data["director_doctor"].doctor_id, department_id=seed_data["department"].department_id, status=1, admission_time=now)
    foreign_department = Department(name="AI异科测试" + uuid.uuid4().hex[:8])
    db_session.add_all([own, foreign_department])
    db_session.flush()
    source = Admission(patient_id=patient_id, doctor_id=seed_data["doctor"].doctor_id, department_id=foreign_department.department_id, status=1, admission_time=now)
    db_session.add(source)
    db_session.commit()
    run = AIRun(
        feature_key="charge_reconciliation",
        patient_id=patient_id,
        requested_by=director.user_id,
        encounter_ref=None,
        input_json=json.dumps({"payload": {"context": {"billing_scope": {"admission_id": source.admission_id}}}}),
    )
    with pytest.raises(HTTPException) as denied:
        authorize_run(db_session, director, run)
    assert denied.value.status_code == 403


@pytest.mark.asyncio
async def test_cashier_uses_only_billing_capability_and_explicit_revocable_patient_grants(async_client, seed_data, db_session, auth_headers, outpatient_bills):
    registration, _, charges, _, _ = outpatient_bills
    user = seed_data["cashier_user"]
    headers = auth_headers(user.username)
    features = await async_client.get("/api/ai/features", headers=headers)
    assert {row["key"] for row in features.json()["data"]} == {"charge_reconciliation"}
    request = {
        "feature_key": "charge_reconciliation",
        "patient_id": registration.patient_id,
        "encounter_ref": registration.registration_uuid,
        "source_refs": {"outpatient_charge_id": charges[0].charge_id},
    }
    denied = await async_client.post("/api/ai/context", headers=headers, json=request)
    assert denied.status_code == 403
    grant = AIPatientGrant(
        user_id=user.user_id,
        patient_id=registration.patient_id,
        category="operations",
        reason="测试限定收费核对用途",
        expires_at=utcnow() + datetime.timedelta(hours=1),
        created_by=seed_data["super_admin_user"].user_id,
    )
    db_session.add(grant)
    db_session.commit()
    allowed = await async_client.post("/api/ai/context", headers=headers, json=request)
    assert allowed.status_code == 200, allowed.text
    context = allowed.json()["data"]["context"]
    assert context["outpatient_charges"][0]["charge_id"] == charges[0].charge_id
    assert "outpatient_records" not in context
    assert "reviewed_lab_results" not in context
    grant.revoked = 1
    db_session.commit()
    revoked = await async_client.post("/api/ai/context", headers=headers, json=request)
    assert revoked.status_code == 403
