import datetime

import pytest

from app.models import Queue


@pytest.mark.asyncio
async def test_patient_queue_progress(async_client, seed_data, auth_headers, db_session):
    db_session.add_all([
        Queue(queue_number=1, patient_id=seed_data["patient2"].patient_id, doctor_id=seed_data["doctor"].doctor_id, status=0, create_time=datetime.datetime.now()),
        Queue(queue_number=2, patient_id=seed_data["patient"].patient_id, doctor_id=seed_data["doctor"].doctor_id, status=0, create_time=datetime.datetime.now()),
    ])
    db_session.commit()
    response = await async_client.get("/api/queue/progress", headers=auth_headers(seed_data["patient_user"].username))
    assert response.json()["data"][0]["ahead_count"] == 1
    assert response.json()["data"][0]["estimated_wait_minutes"] == 10
