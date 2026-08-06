import datetime

import pytest

from app.models import Admission


@pytest.mark.asyncio
class TestCriticalCareRecord:
    async def test_critical_record_vitals(self, async_client, seed_data, auth_headers, db_session):
        admission = Admission(admission_id="critical-admission", admission_no="ZYCRITICAL1", patient_id=seed_data["patient"].patient_id, status=1, admission_time=datetime.datetime.now(), create_time=datetime.datetime.now())
        db_session.add(admission)
        db_session.commit()
        response = await async_client.post("/api/criticalCareRecord/create", headers=auth_headers(seed_data["nurse_user"].username), json={"admission_id": admission.admission_id, "patient_id": admission.patient_id, "consciousness": 2, "gcs_score": 8, "oxygen_support": "无创呼吸机", "blood_pressure": "90/60", "pulse": 110, "spo2": 88, "urine_output": "20ml/h"})
        assert response.json()["code"] == 200
        listed = await async_client.get("/api/criticalCareRecord/list", headers=auth_headers(seed_data["nurse_user"].username), params={"admission_id": admission.admission_id})
        assert listed.json()["data"][0]["gcs_score"] == 8
