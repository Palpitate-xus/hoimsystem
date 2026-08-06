import datetime

import pytest

from app.models import Admission


@pytest.mark.asyncio
class TestMedicalRecordHome:
    async def test_medical_record_home_submit_and_lock(self, async_client, seed_data, auth_headers, db_session):
        admission = Admission(admission_id="home-admission", admission_no="ZYHOME001", patient_id=seed_data["patient"].patient_id, doctor_id=seed_data["doctor"].doctor_id, admission_diagnosis="肺炎", status=2, admission_time=datetime.datetime.now(), create_time=datetime.datetime.now())
        db_session.add(admission)
        db_session.commit()
        headers = auth_headers(seed_data["doctor_user"].username)
        created = await async_client.post("/api/medicalRecordHome/create", headers=headers, json={"admission_id": admission.admission_id, "admission_diagnosis": "肺炎"})
        assert created.json()["code"] == 200
        home_id = created.json()["data"]["home_id"]
        missing = await async_client.post("/api/medicalRecordHome/submit", headers=headers, json={"home_id": home_id})
        assert missing.json()["code"] == 500
        updated = await async_client.put("/api/medicalRecordHome/update", headers=headers, json={"home_id": home_id, "discharge_diagnosis": "肺炎好转"})
        assert updated.json()["code"] == 200
        submitted = await async_client.post("/api/medicalRecordHome/submit", headers=headers, json={"home_id": home_id})
        assert submitted.json()["data"]["status_text"] == "已提交"
        blocked = await async_client.put("/api/medicalRecordHome/update", headers=headers, json={"home_id": home_id, "complication": "无"})
        assert blocked.json()["code"] == 403
