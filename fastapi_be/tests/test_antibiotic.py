import datetime

import pytest

from app.models import AntibioticApproval, Pharmaceutical


@pytest.mark.asyncio
class TestAntibiotic:
    async def test_grade_and_escalation_approval(self, async_client, seed_data, auth_headers, db_session):
        seed_data["pharmaceutical"].antibiotic_level = 2
        db_session.commit()
        doctor_headers = auth_headers(seed_data["doctor_user"].username)
        grade = await async_client.get("/api/antibiotic/grade/list", headers=doctor_headers)
        assert grade.json()["data"][0]["level"] == 2
        created = await async_client.post(
            "/api/antibiotic/approval/create",
            headers=doctor_headers,
            json={"pharmaceutical_id": seed_data["pharmaceutical"].pharmaceutical_id, "patient_id": seed_data["patient"].patient_id, "reason": "重症感染需限制级用药"},
        )
        assert created.json()["code"] == 200
        reviewed = await async_client.post(
            "/api/antibiotic/approval/review",
            headers=auth_headers(seed_data["director_user"].username),
            json={"approval_id": created.json()["data"]["approval_id"], "status": 1, "note": "同意"},
        )
        assert reviewed.json()["code"] == 200

    async def test_patient_cannot_review_antibiotic(self, async_client, seed_data, auth_headers):
        response = await async_client.get("/api/antibiotic/approval/list", headers=auth_headers(seed_data["patient_user"].username))
        assert response.status_code == 403

    async def test_approved_antibiotic_is_required_and_consumed_by_prescription(self, async_client, seed_data, auth_headers, db_session):
        drug = seed_data["pharmaceutical"]
        drug.antibiotic_level = 3
        db_session.commit()
        doctor_headers = auth_headers(seed_data["doctor_user"].username)
        patient_id = seed_data["patient2"].patient_id
        payload = {"patient": patient_id, "phas": [{"id": drug.pharmaceutical_id, "number": 1}]}

        blocked = await async_client.post("/api/prescriptionManagement/create", headers=doctor_headers, json=payload)
        assert blocked.json()["code"] == 500
        assert "审批" in blocked.json()["msg"]

        approval = await async_client.post("/api/antibiotic/approval/create", headers=doctor_headers, json={
            "pharmaceutical_id": drug.pharmaceutical_id,
            "patient_id": patient_id,
            "reason": "重症感染需特殊使用级抗菌药",
        })
        approval_id = approval.json()["data"]["approval_id"]
        duplicate = await async_client.post("/api/antibiotic/approval/create", headers=doctor_headers, json={
            "pharmaceutical_id": drug.pharmaceutical_id,
            "patient_id": patient_id,
            "reason": "重复提交",
        })
        assert duplicate.json()["data"]["idempotent"] is True
        reviewed = await async_client.post("/api/antibiotic/approval/review", headers=auth_headers(seed_data["director_user"].username), json={
            "approval_id": approval_id, "status": 1, "note": "同意",
        })
        assert reviewed.json()["code"] == 200
        repeated_review = await async_client.post("/api/antibiotic/approval/review", headers=auth_headers(seed_data["director_user"].username), json={
            "approval_id": approval_id, "status": 1, "note": "重复确认",
        })
        assert repeated_review.json()["data"]["idempotent"] is True

        created = await async_client.post("/api/prescriptionManagement/create", headers=doctor_headers, json={
            **payload, "antibiotic_approval_ids": [approval_id],
        })
        assert created.json()["code"] == 200
        approval_row = db_session.get(AntibioticApproval, approval_id)
        assert approval_row.prescription_id == created.json()["data"]["uuid"]
        reused = await async_client.post("/api/prescriptionManagement/create", headers=doctor_headers, json={
            **payload, "antibiotic_approval_ids": [approval_id],
        })
        assert reused.json()["code"] == 500
