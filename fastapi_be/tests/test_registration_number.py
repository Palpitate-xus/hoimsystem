import datetime

import pytest

from app.database import Base
from app.models import Registration
from app.registration import allocate_registration_id


@pytest.fixture(autouse=True)
def isolate_registration_database(db_session):
    bind = db_session.get_bind()
    Base.metadata.drop_all(bind=bind)
    Base.metadata.create_all(bind=bind)
    yield
    Base.metadata.drop_all(bind=bind)


def test_registration_number_increments_per_day(db_session):
    visit_time = datetime.datetime(2026, 8, 8, 9, 0)
    numbers = []
    for offset in range(3):
        registration = Registration(
            registration_id=allocate_registration_id(db_session, visit_time),
            time=visit_time + datetime.timedelta(minutes=offset),
            status=0,
        )
        db_session.add(registration)
        db_session.commit()
        numbers.append(registration.registration_id)

    next_day_number = allocate_registration_id(db_session, visit_time + datetime.timedelta(days=1))

    assert numbers == [1, 2, 3]
    assert next_day_number == 1


@pytest.mark.asyncio
async def test_patient_registration_returns_daily_number(async_client, seed_data, auth_headers, db_session):
    schedule = seed_data["doctor"].schedules[0]
    response = await async_client.post(
        "/api/registrationManagement/create",
        headers=auth_headers(seed_data["patient_user"].username),
        json={
            "id": schedule.schedule_id,
            "doctor_id": seed_data["doctor"].doctor_id,
            "department_id": seed_data["department"].department_id,
            "specialist": schedule.specialist,
        },
    )

    body = response.json()
    assert response.status_code == 200
    assert body["code"] == 200
    assert body["data"]["registration_id"] == 1
    assert db_session.query(Registration).filter_by(registration_uuid=body["data"]["registration_uuid"]).one().registration_id == 1


@pytest.mark.asyncio
async def test_window_registration_returns_daily_number(async_client, seed_data, auth_headers):
    schedule = seed_data["doctor"].schedules[0]
    response = await async_client.post(
        "/api/windowRegistration/create",
        headers=auth_headers(seed_data["cashier_user"].username),
        json={
            "identity": seed_data["patient"].identity,
            "schedule_id": schedule.schedule_id,
            "doctor_id": schedule.doctor_id,
            "department_id": seed_data["department"].department_id,
            "specialist": schedule.specialist,
        },
    )

    body = response.json()
    assert response.status_code == 200
    assert body["code"] == 200
    assert body["data"]["registration_id"] == 1
