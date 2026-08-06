import datetime

import pytest

from app.models import Admission


@pytest.mark.asyncio
class TestNursingAssessment:
    async def test_assessment_lifecycle(self, async_client, seed_data, auth_headers, db_session):
        admission = Admission(admission_id="assessment-admission", admission_no="ZYASSESS001", patient_id=seed_data["patient"].patient_id, status=1, admission_time=datetime.datetime.now(), create_time=datetime.datetime.now())
        db_session.add(admission)
        db_session.commit()
        nurse_headers = auth_headers(seed_data["nurse_user"].username)
        created = await async_client.post("/api/nursingAssessment/create", headers=nurse_headers, json={"admission_id": admission.admission_id, "patient_id": seed_data["patient"].patient_id, "adl_score": 45, "pressure_ulcer_risk": 2, "fall_risk": 1, "consciousness": 0, "nutrition_risk": 1, "note": "需要协助下床"})
        assert created.json()["code"] == 200
        assessment_id = created.json()["data"]["assessment_id"]
        duplicate = await async_client.post("/api/nursingAssessment/create", headers=nurse_headers, json={"admission_id": admission.admission_id, "patient_id": seed_data["patient"].patient_id, "adl_score": 50})
        assert duplicate.json()["code"] == 500
        updated = await async_client.put("/api/nursingAssessment/update", headers=nurse_headers, json={"assessment_id": assessment_id, "fall_risk": 2})
        assert updated.json()["data"]["fall_risk"] == 2
        completed = await async_client.post("/api/nursingAssessment/complete", headers=nurse_headers, json={"assessment_id": assessment_id})
        assert completed.json()["data"]["status_text"] == "已完成"
        blocked = await async_client.put("/api/nursingAssessment/update", headers=nurse_headers, json={"assessment_id": assessment_id, "note": "修改"})
        assert blocked.json()["code"] == 403
