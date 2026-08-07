import datetime

import pytest

from app.models import Appointment, DoctorSchedule


@pytest.mark.asyncio
class TestWindowAppointment:
    async def test_window_confirm_and_cancel(self, async_client, seed_data, auth_headers, db_session):
        appointment = Appointment(patient_id=seed_data["patient"].patient_id, doctor_id=seed_data["doctor"].doctor_id, specialist=0, department_id=seed_data["department"].department_id, prefer_time="上午", appointment_time=datetime.datetime.now(), time=datetime.date.today(), status=0)
        db_session.add(appointment)
        db_session.commit()
        headers = auth_headers(seed_data["registrar_user"].username)
        listing = await async_client.get("/api/windowRegistration/appointments", headers=headers, params={"identity": seed_data["patient"].identity})
        assert listing.json()["data"][0]["confirmed"] == 0
        confirmed = await async_client.post("/api/windowRegistration/appointmentConfirm", headers=headers, json={"uuid": appointment.registration_uuid})
        assert confirmed.json()["code"] == 200
        cancelled = await async_client.post("/api/windowRegistration/appointmentCancel", headers=headers, json={"uuid": appointment.registration_uuid})
        assert cancelled.json()["code"] == 200
        repeated = await async_client.post("/api/windowRegistration/appointmentCancel", headers=headers, json={"uuid": appointment.registration_uuid})
        assert repeated.json() == {"code": 500, "msg": "预约已取消，无需重复操作"}

    async def test_window_appointment_cancel_returns_source_schedule(self, async_client, seed_data, auth_headers, db_session):
        source = DoctorSchedule(week="星期一", time="03", number=0, specialist=0, doctor_id=seed_data["doctor"].doctor_id)
        other = DoctorSchedule(week="星期二", time="03", number=7, specialist=0, doctor_id=seed_data["doctor"].doctor_id)
        db_session.add_all([source, other])
        db_session.commit()
        appointment = Appointment(
            schedule_id=source.schedule_id,
            patient_id=seed_data["patient"].patient_id,
            doctor_id=seed_data["doctor"].doctor_id,
            specialist=0,
            department_id=seed_data["department"].department_id,
            prefer_time="上午",
            appointment_time=datetime.datetime.now(),
            time=datetime.date.today(),
            status=0,
        )
        db_session.add(appointment)
        db_session.commit()
        response = await async_client.post(
            "/api/windowRegistration/appointmentCancel",
            headers=auth_headers(seed_data["cashier_user"].username),
            json={"uuid": appointment.registration_uuid},
        )
        assert response.json()["code"] == 200
        db_session.expire_all()
        assert db_session.get(DoctorSchedule, source.schedule_id).number == 1
        assert db_session.get(DoctorSchedule, other.schedule_id).number == 7
