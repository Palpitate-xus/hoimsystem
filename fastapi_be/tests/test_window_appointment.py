import datetime

import pytest

from app.models import Appointment


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
