import datetime

import pytest

from app.models import Pharmaceutical


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
