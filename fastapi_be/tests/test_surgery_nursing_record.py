import datetime

import pytest

from app.models import Admission, SurgeryApplication, SurgerySchedule


@pytest.mark.asyncio
class TestSurgeryNursingRecord:
    async def test_surgery_nursing_phases(self, async_client, seed_data, auth_headers, db_session):
        admission = Admission(admission_id="surgery-nursing-admission", admission_no="ZYSURG001", patient_id=seed_data["patient"].patient_id, status=1, admission_time=datetime.datetime.now(), create_time=datetime.datetime.now())
        application = SurgeryApplication(application_id="surgery-nursing-application", admission_id=admission.admission_id, patient_id=admission.patient_id, surgery_name="腹腔镜手术", status=2, create_time=datetime.datetime.now())
        schedule = SurgerySchedule(schedule_id="surgery-nursing-schedule", application_id=application.application_id, patient_id=admission.patient_id, surgery_date=datetime.date.today(), status=0, create_time=datetime.datetime.now())
        db_session.add_all([admission, application, schedule])
        db_session.commit()
        response = await async_client.post("/api/surgeryNursingRecord/create", headers=auth_headers(seed_data["nurse_user"].username), json={"schedule_id": schedule.schedule_id, "patient_id": admission.patient_id, "phase": 1, "checklist": "器械、纱布、标本核对完成", "instrument_count": "器械 20 件", "specimen": "阑尾标本"})
        assert response.json()["code"] == 200
        assert response.json()["data"]["phase_text"] == "术中"
