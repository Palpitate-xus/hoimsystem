import datetime

import pytest

from app.models import Admission


@pytest.mark.asyncio
class TestMedicalRecordArchive:
    async def test_archive_actions_require_reason_and_location(self, async_client, seed_data, auth_headers, db_session):
        admission = Admission(admission_id="archive-validation", admission_no="ZYARCH002", patient_id=seed_data["patient"].patient_id, doctor_id=seed_data["doctor"].doctor_id, admission_diagnosis="肺炎", status=2, admission_time=datetime.datetime.now(), create_time=datetime.datetime.now())
        db_session.add(admission)
        db_session.commit()
        doctor_headers = auth_headers(seed_data["doctor_user"].username)
        home = await async_client.post("/api/medicalRecordHome/create", headers=doctor_headers, json={"admission_id": admission.admission_id, "admission_diagnosis": "肺炎", "discharge_diagnosis": "肺炎好转"})
        home_id = home.json()["data"]["home_id"]
        await async_client.post("/api/medicalRecordHome/submit", headers=doctor_headers, json={"home_id": home_id})
        missing_location = await async_client.post("/api/medicalRecordArchive/create", headers=doctor_headers, json={"home_id": home_id, "location": "   "})
        assert missing_location.json() == {"code": 500, "msg": "归档位置不能为空"}
        created = await async_client.post("/api/medicalRecordArchive/create", headers=doctor_headers, json={"home_id": home_id, "location": "B-01-01"})
        archive_id = created.json()["data"]["archive_id"]
        director_headers = auth_headers(seed_data["director_user"].username)
        await async_client.post("/api/medicalRecordArchive/archive", headers=director_headers, json={"archive_id": archive_id})
        missing_borrow_reason = await async_client.post("/api/medicalRecordArchive/borrow", headers=doctor_headers, json={"archive_id": archive_id, "reason": " "})
        assert missing_borrow_reason.json() == {"code": 500, "msg": "借阅事由不能为空"}
        await async_client.post("/api/medicalRecordArchive/borrow", headers=doctor_headers, json={"archive_id": archive_id, "reason": "病案质控"})
        missing_seal_reason = await async_client.post("/api/medicalRecordArchive/seal", headers=director_headers, json={"archive_id": archive_id, "reason": " "})
        assert missing_seal_reason.json() == {"code": 500, "msg": "封存原因不能为空"}

    async def test_archive_borrow_return_and_seal(self, async_client, seed_data, auth_headers, db_session):
        admission = Admission(admission_id="archive-admission", admission_no="ZYARCH001", patient_id=seed_data["patient"].patient_id, doctor_id=seed_data["doctor"].doctor_id, admission_diagnosis="肺炎", status=2, admission_time=datetime.datetime.now(), create_time=datetime.datetime.now())
        db_session.add(admission)
        db_session.commit()
        doctor_headers = auth_headers(seed_data["doctor_user"].username)
        director_headers = auth_headers(seed_data["director_user"].username)
        home = await async_client.post("/api/medicalRecordHome/create", headers=doctor_headers, json={"admission_id": admission.admission_id, "admission_diagnosis": "肺炎", "discharge_diagnosis": "肺炎好转"})
        home_id = home.json()["data"]["home_id"]
        await async_client.post("/api/medicalRecordHome/submit", headers=doctor_headers, json={"home_id": home_id})
        created = await async_client.post("/api/medicalRecordArchive/create", headers=doctor_headers, json={"home_id": home_id, "location": "A-01-01"})
        assert created.json()["code"] == 200
        archive_id = created.json()["data"]["archive_id"]
        archived = await async_client.post("/api/medicalRecordArchive/archive", headers=director_headers, json={"archive_id": archive_id})
        assert archived.json()["data"]["status_text"] == "已归档"
        borrowed = await async_client.post("/api/medicalRecordArchive/borrow", headers=doctor_headers, json={"archive_id": archive_id, "reason": "病案质控"})
        assert borrowed.json()["data"]["status_text"] == "借阅中"
        returned = await async_client.post("/api/medicalRecordArchive/return", headers=doctor_headers, json={"archive_id": archive_id})
        assert returned.json()["data"]["status_text"] == "已归档"
        sealed = await async_client.post("/api/medicalRecordArchive/seal", headers=director_headers, json={"archive_id": archive_id, "reason": "年度封存"})
        assert sealed.json()["data"]["status_text"] == "已封存"
