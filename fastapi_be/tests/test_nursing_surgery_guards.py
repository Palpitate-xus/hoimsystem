"""出院后护理文书拦截 + 手术排台冲突检测回归测试。"""
import datetime

import pytest

from app.models import Admission, SurgeryApplication, SurgerySchedule


def _make_admission(db, patient_id, doctor_id, department_id, status=1):
    admission = Admission(
        admission_no=f"ZY-NG-{datetime.datetime.now().strftime('%H%M%S%f')}",
        patient_id=patient_id,
        doctor_id=doctor_id,
        department_id=department_id,
        admission_time=datetime.datetime.now(),
        status=status,
        create_time=datetime.datetime.now(),
    )
    db.add(admission)
    db.commit()
    return admission


@pytest.mark.asyncio
class TestDischargedNursingGuard:
    async def test_nursing_record_rejected_after_discharge(self, async_client, seed_data, auth_headers, db_session):
        """出院（status=2）后书写护理记录必须被拒。"""
        admission = _make_admission(
            db_session, seed_data["patient"].patient_id,
            seed_data["doctor"].doctor_id, seed_data["department"].department_id, status=2,
        )
        headers = auth_headers(seed_data["nurse_user"].username)
        r = await async_client.post(
            "/api/nursingRecord/create",
            headers=headers,
            json={
                "admission_id": admission.admission_id,
                "patient_id": seed_data["patient"].patient_id,
                "content": "补写记录",
                "record_time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            },
        )
        assert r.json()["code"] == 500
        assert "出院" in r.json()["msg"]

    async def test_nursing_assessment_rejected_after_discharge(self, async_client, seed_data, auth_headers, db_session):
        admission = _make_admission(
            db_session, seed_data["patient"].patient_id,
            seed_data["doctor"].doctor_id, seed_data["department"].department_id, status=2,
        )
        headers = auth_headers(seed_data["nurse_user"].username)
        r = await async_client.post(
            "/api/nursingAssessment/create",
            headers=headers,
            json={"admission_id": admission.admission_id, "patient_id": seed_data["patient"].patient_id, "adl_score": 90},
        )
        assert r.json()["code"] == 500
        assert "出院" in r.json()["msg"]


@pytest.mark.asyncio
class TestSurgeryScheduleConflict:
    def _mk_application(self, db, patient_id, name="排台测试"):
        app_obj = SurgeryApplication(
            patient_id=patient_id,
            surgery_name=name,
            status=1,
            create_time=datetime.datetime.now(),
        )
        db.add(app_obj)
        db.commit()
        return app_obj

    async def test_same_room_same_date_rejected(self, async_client, seed_data, auth_headers, db_session):
        """同手术室同日已有未取消排台时拒绝。"""
        app1 = self._mk_application(db_session, seed_data["patient"].patient_id)
        db_session.add(SurgerySchedule(
            application_id=app1.application_id,
            patient_id=seed_data["patient"].patient_id,
            operating_room="OR-CONF",
            surgery_date=datetime.date.today(),
            status=0,
            create_time=datetime.datetime.now(),
        ))
        db_session.commit()

        app2 = self._mk_application(db_session, seed_data["patient2"].patient_id, name="冲突申请")
        headers = auth_headers("doc01")
        r = await async_client.post(
            "/api/surgerySchedule/create",
            headers=headers,
            json={
                "application_id": app2.application_id,
                "operating_room": "OR-CONF",
                "surgery_date": datetime.date.today().isoformat(),
            },
        )
        assert r.json()["code"] == 500
        assert "已 有排台" in r.json()["msg"] or "已有排台" in r.json()["msg"]

    async def test_cancelled_schedule_does_not_block(self, async_client, seed_data, auth_headers, db_session):
        """已取消（3）的排台不占用手术室。"""
        app1 = self._mk_application(db_session, seed_data["patient"].patient_id)
        db_session.add(SurgerySchedule(
            application_id=app1.application_id,
            patient_id=seed_data["patient"].patient_id,
            operating_room="OR-FREE",
            surgery_date=datetime.date.today(),
            status=3,
            create_time=datetime.datetime.now(),
        ))
        db_session.commit()
        app2 = self._mk_application(db_session, seed_data["patient2"].patient_id, name="新排台")
        headers = auth_headers("doc01")
        r = await async_client.post(
            "/api/surgerySchedule/create",
            headers=headers,
            json={
                "application_id": app2.application_id,
                "operating_room": "OR-FREE",
                "surgery_date": datetime.date.today().isoformat(),
            },
        )
        assert r.json()["code"] == 200, r.json()
