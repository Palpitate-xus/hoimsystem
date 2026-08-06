import datetime

import pytest

from app.models import Admission


@pytest.mark.asyncio
class TestInpatientOrderSafety:
    async def test_order_list_requires_role(self, async_client):
        response = await async_client.get("/api/inpatientOrder/getList")
        assert response.status_code == 401

    async def test_order_create_validates_admission_patient_and_stock(self, async_client, seed_data, auth_headers, db_session):
        admission = Admission(
            patient_id=seed_data["patient"].patient_id,
            doctor_id=seed_data["doctor"].doctor_id,
            department_id=seed_data["department"].department_id,
            status=1,
            admission_time=datetime.datetime.now(),
            create_time=datetime.datetime.now(),
        )
        db_session.add(admission)
        db_session.commit()
        headers = auth_headers(seed_data["doctor_user"].username)
        base = {
            "admission_id": admission.admission_id,
            "patient_id": seed_data["patient2"].patient_id,
            "doctor_id": seed_data["doctor"].doctor_id,
            "order_type": 0,
            "category": "drug",
            "items": [{"item_name": "阿司匹林", "item_type": "drug", "item_id_ref": seed_data["pharmaceutical"].pharmaceutical_id, "quantity": 1, "days": 1, "unit_price": 15.5}],
        }
        mismatch = await async_client.post("/api/inpatientOrder/create", headers=headers, json=base)
        assert mismatch.json()["code"] == 500

        base["patient_id"] = seed_data["patient"].patient_id
        base["items"][0]["quantity"] = 1000
        insufficient = await async_client.post("/api/inpatientOrder/create", headers=headers, json=base)
        assert insufficient.json()["code"] == 500

    async def test_execution_rejects_invalid_result_state(self, async_client, seed_data, auth_headers, db_session):
        admission = Admission(
            patient_id=seed_data["patient"].patient_id,
            doctor_id=seed_data["doctor"].doctor_id,
            department_id=seed_data["department"].department_id,
            status=1,
            admission_time=datetime.datetime.now(),
            create_time=datetime.datetime.now(),
        )
        db_session.add(admission)
        db_session.commit()
        admin_headers = auth_headers(seed_data["admin_user"].username)
        created = await async_client.post("/api/inpatientOrder/create", headers=admin_headers, json={
            "admission_id": admission.admission_id,
            "patient_id": seed_data["patient"].patient_id,
            "doctor_id": seed_data["doctor"].doctor_id,
            "order_type": 1,
            "category": "treatment",
            "items": [{"item_name": "换药", "item_type": "service", "quantity": 1, "days": 1, "unit_price": 0}],
        })
        assert created.json()["code"] == 200
        order_id = created.json()["data"]["order_id"]
        nurse_headers = auth_headers(seed_data["nurse_user"].username)
        invalid = await async_client.post("/api/inpatientOrder/execute", headers=nurse_headers, json={"order_id": order_id, "status": 0})
        assert invalid.json()["code"] == 500
        await async_client.post("/api/inpatientOrder/audit", headers=admin_headers, json={"order_id": order_id})
        valid = await async_client.post("/api/inpatientOrder/execute", headers=nurse_headers, json={"order_id": order_id, "status": 1})
        assert valid.json()["code"] == 200
