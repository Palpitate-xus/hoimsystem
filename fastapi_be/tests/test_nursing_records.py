import datetime

import pytest

from app.models import Admission


@pytest.mark.asyncio
class TestNursingRecordIntegrity:
    async def test_nursing_records_match_patient_and_are_immutable(self, async_client, seed_data, auth_headers, db_session):
        admission = Admission(
            admission_id="nursing-integrity-admission",
            admission_no="ZYNURS001",
            patient_id=seed_data["patient"].patient_id,
            doctor_id=seed_data["doctor"].doctor_id,
            admission_diagnosis="肺炎",
            status=1,
            admission_time=datetime.datetime.now(),
            create_time=datetime.datetime.now(),
        )
        db_session.add(admission)
        db_session.commit()
        headers = auth_headers(seed_data["nurse_user"].username)
        mismatch = await async_client.post(
            "/api/nursingRecord/create",
            headers=headers,
            json={"admission_id": admission.admission_id, "patient_id": seed_data["patient2"].patient_id, "record_time": "2026-08-07 08:00:00"},
        )
        assert mismatch.json() == {"code": 500, "msg": "入院记录不存在或患者不匹配"}
        created = await async_client.post(
            "/api/nursingRecord/create",
            headers=headers,
            json={"admission_id": admission.admission_id, "patient_id": seed_data["patient"].patient_id, "record_time": "2026-08-07 08:00:00", "temperature": 36.5},
        )
        assert created.json()["code"] == 200
        deleted = await async_client.post("/api/nursingRecord/delete", headers=headers, json={"record_id": 1})
        assert deleted.json() == {"code": 403, "msg": "护理文书不可删除，请通过更正记录补录"}

    async def test_temperature_records_match_patient_and_are_immutable(self, async_client, seed_data, auth_headers, db_session):
        admission = Admission(
            admission_id="temperature-integrity-admission",
            admission_no="ZYNURS002",
            patient_id=seed_data["patient"].patient_id,
            doctor_id=seed_data["doctor"].doctor_id,
            admission_diagnosis="肺炎",
            status=1,
            admission_time=datetime.datetime.now(),
            create_time=datetime.datetime.now(),
        )
        db_session.add(admission)
        db_session.commit()
        headers = auth_headers(seed_data["nurse_user"].username)
        mismatch = await async_client.post(
            "/api/temperatureRecord/create",
            headers=headers,
            json={"admission_id": admission.admission_id, "patient_id": seed_data["patient2"].patient_id, "record_date": "2026-08-07", "time_point": "08:00"},
        )
        assert mismatch.json() == {"code": 500, "msg": "入院记录不存在或患者不匹配"}
        created = await async_client.post(
            "/api/temperatureRecord/create",
            headers=headers,
            json={"admission_id": admission.admission_id, "patient_id": seed_data["patient"].patient_id, "record_date": "2026-08-07", "time_point": "08:00", "temperature": 36.5},
        )
        assert created.json()["code"] == 200
        deleted = await async_client.post("/api/temperatureRecord/delete", headers=headers, json={"temp_id": 1})
        assert deleted.json() == {"code": 403, "msg": "体温单记录不可删除，请通过更正记录补录"}
