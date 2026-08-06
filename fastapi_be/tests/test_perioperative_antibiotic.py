import datetime

import pytest

from app.models import Pharmaceutical, SurgeryApplication


@pytest.mark.asyncio
class TestPerioperativeAntibiotic:
    async def test_create_and_execute_prophylaxis(self, async_client, seed_data, auth_headers, db_session):
        drug = db_session.query(Pharmaceutical).filter(Pharmaceutical.pharmaceutical_id == seed_data["pharmaceutical"].pharmaceutical_id).one()
        drug.antibiotic_level = 1
        application = SurgeryApplication(
            patient_id=seed_data["patient"].patient_id,
            doctor_id=seed_data["doctor"].doctor_id,
            surgery_name="腹腔镜手术",
            status=1,
            create_time=datetime.datetime.now(),
        )
        db_session.add(application)
        db_session.commit()

        headers = auth_headers(seed_data["doctor_user"].username)
        created = await async_client.post(
            "/api/surgery/perioperative/create",
            headers=headers,
            json={"application_id": application.application_id, "pharmaceutical_id": drug.pharmaceutical_id, "dose": "1g", "timing_minutes": 30},
        )
        assert created.json()["code"] == 200
        record_id = created.json()["data"]["perioperative_id"]
        completed = await async_client.post(
            "/api/surgery/perioperative/status", headers=headers, json={"perioperative_id": record_id, "status": 1}
        )
        assert completed.json()["data"]["status_text"] == "已执行"

    async def test_non_antibiotic_is_rejected(self, async_client, seed_data, auth_headers, db_session):
        application = SurgeryApplication(
            patient_id=seed_data["patient"].patient_id,
            doctor_id=seed_data["doctor"].doctor_id,
            surgery_name="普通手术",
            status=1,
            create_time=datetime.datetime.now(),
        )
        db_session.add(application)
        db_session.commit()
        response = await async_client.post(
            "/api/surgery/perioperative/create",
            headers=auth_headers(seed_data["doctor_user"].username),
            json={"application_id": application.application_id, "pharmaceutical_id": seed_data["pharmaceutical"].pharmaceutical_id, "dose": "1g"},
        )
        assert response.json()["code"] == 400
