import datetime

import pytest

from app.models import Admission, MedicationAdministration, PatientCard


@pytest.mark.asyncio
async def test_emar_requires_matching_patient_and_drug_barcodes(async_client, seed_data, auth_headers, db_session):
    card = PatientCard(
        card_no="WRIST-0001",
        patient_id=seed_data["patient"].patient_id,
        status=0,
        issue_time=datetime.datetime.now(),
        issuer_id=seed_data["admin_user"].user_id,
    )
    seed_data["pharmaceutical"].barcode = "MED-ASPIRIN-001"
    admission = Admission(
        patient_id=seed_data["patient"].patient_id,
        doctor_id=seed_data["doctor"].doctor_id,
        department_id=seed_data["department"].department_id,
        status=1,
        admission_time=datetime.datetime.now(),
        create_time=datetime.datetime.now(),
    )
    db_session.add_all([card, admission])
    db_session.commit()
    admin_headers = auth_headers(seed_data["admin_user"].username)
    created = await async_client.post(
        "/api/inpatientOrder/create",
        headers=admin_headers,
        json={
            "admission_id": admission.admission_id,
            "patient_id": seed_data["patient"].patient_id,
            "doctor_id": seed_data["doctor"].doctor_id,
            "order_type": 1,
            "category": "drug",
            "items": [{
                "item_name": "阿司匹林",
                "item_type": "drug",
                "item_id_ref": seed_data["pharmaceutical"].pharmaceutical_id,
                "quantity": 1,
                "days": 1,
                "unit_price": 15.5,
            }],
        },
    )
    order_id = created.json()["data"]["order_id"]
    await async_client.post("/api/inpatientOrder/audit", headers=admin_headers, json={"order_id": order_id})
    execution = await async_client.get(
        "/api/inpatientOrder/getExecutionList",
        headers=admin_headers,
        params={"order_id": order_id},
    )
    execution_id = execution.json()["data"][0]["execution_id"]
    nurse_headers = auth_headers(seed_data["nurse_user"].username)

    bypass = await async_client.post(
        "/api/inpatientOrder/execute",
        headers=nurse_headers,
        json={"order_id": order_id, "status": 1},
    )
    assert bypass.status_code == 409

    mismatch = await async_client.post(
        "/api/emar/verify",
        headers=nurse_headers,
        json={
            "execution_id": execution_id,
            "patient_barcode": "WRIST-0001",
            "medication_barcodes": ["WRONG-DRUG"],
        },
    )
    assert mismatch.status_code == 400

    verified = await async_client.post(
        "/api/emar/verify",
        headers=nurse_headers,
        json={
            "execution_id": execution_id,
            "patient_barcode": "WRIST-0001",
            "medication_barcodes": ["MED-ASPIRIN-001"],
        },
    )
    assert verified.status_code == 200
    administration_id = verified.json()["data"]["administration_id"]

    administered = await async_client.post(
        "/api/emar/administer",
        headers=nurse_headers,
        json={"administration_id": administration_id, "note": "口服"},
    )
    assert administered.status_code == 200
    assert db_session.get(MedicationAdministration, administration_id).status == 2
