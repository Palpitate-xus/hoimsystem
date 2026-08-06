import datetime

import pytest

from app.models import Admission


@pytest.mark.asyncio
class TestMedicalRecordHomeQuality:
    async def test_quality_check_and_summary(self, async_client, seed_data, auth_headers, db_session):
        admission = Admission(admission_id="quality-home-admission", admission_no="ZYQUAL001", patient_id=seed_data["patient"].patient_id, doctor_id=seed_data["doctor"].doctor_id, admission_diagnosis="肺炎", status=2, admission_time=datetime.datetime.now(), create_time=datetime.datetime.now())
        db_session.add(admission)
        db_session.commit()
        headers = auth_headers(seed_data["doctor_user"].username)
        home = await async_client.post("/api/medicalRecordHome/create", headers=headers, json={"admission_id": admission.admission_id, "admission_diagnosis": "肺炎"})
        home_id = home.json()["data"]["home_id"]
        checked = await async_client.post("/api/medicalRecordHomeQuality/check", headers=headers, json={"home_id": home_id, "check_item": "出院诊断", "check_result": 2, "issue": "未填写出院诊断", "score": 60})
        assert checked.json()["data"]["check_result_text"] == "错误"
        listing = await async_client.get("/api/medicalRecordHomeQuality/list", headers=headers, params={"home_id": home_id})
        assert len(listing.json()["data"]) == 1
        summary = await async_client.get("/api/medicalRecordHomeQuality/summary", headers=headers)
        assert summary.json()["data"]["error_count"] == 1
