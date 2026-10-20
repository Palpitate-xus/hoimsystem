"""Scoped history cannot mix another case or widen requester and current-care permissions."""

import datetime

import pytest

from app.ai.models import AIRun
from app.models import Registration


@pytest.mark.asyncio
async def test_history_filters_patient_and_encounter_before_limiting_and_retains_requester_scope(async_client, seed_data, db_session, auth_headers):
    doctor = seed_data["doctor"]
    encounters = [
        Registration(patient_id=patient.patient_id, doctor_id=doctor.doctor_id, department_id=doctor.department_id, time=datetime.datetime.now(), status=0)
        for patient in (seed_data["patient"], seed_data["patient"], seed_data["patient2"])
    ]
    db_session.add_all(encounters)
    db_session.flush()
    runs = [
        AIRun(
            feature_key="patient_summary",
            patient_id=visit.patient_id,
            encounter_ref=visit.registration_uuid,
            requested_by=seed_data["doctor_user"].user_id,
            prompt_hash="test",
            context_digest="test",
            status="succeeded",
        )
        for visit in encounters
    ]
    other_requester = AIRun(
        feature_key="patient_summary",
        patient_id=encounters[0].patient_id,
        encounter_ref=encounters[0].registration_uuid,
        requested_by=seed_data["super_admin_user"].user_id,
        prompt_hash="test",
        context_digest="test",
        status="succeeded",
    )
    db_session.add_all([*runs, other_requester])
    db_session.commit()
    headers = auth_headers(seed_data["doctor_user"].username)
    query = {"feature_key": "patient_summary", "patient_id": encounters[0].patient_id}
    response = await async_client.get("/api/ai/runs", headers=headers, params=query)
    assert response.status_code == 200, response.text
    assert {row["run_id"] for row in response.json()["data"]} == {row.run_id for row in runs[:2]}
    query["encounter_ref"] = encounters[0].registration_uuid
    response = await async_client.get("/api/ai/runs", headers=headers, params=query)
    assert [row["run_id"] for row in response.json()["data"]] == [runs[0].run_id]
    query["patient_id"] = encounters[2].patient_id
    response = await async_client.get("/api/ai/runs", headers=headers, params=query)
    assert response.json()["data"] == []


@pytest.mark.asyncio
async def test_deleted_encounter_does_not_break_other_authorized_history(async_client, seed_data, db_session, auth_headers):
    run = AIRun(
        feature_key="patient_summary",
        patient_id=seed_data["patient"].patient_id,
        encounter_ref="deleted-test-encounter",
        requested_by=seed_data["doctor_user"].user_id,
        prompt_hash="test",
        context_digest="test",
        status="succeeded",
    )
    db_session.add(run)
    db_session.commit()
    response = await async_client.get("/api/ai/runs", headers=auth_headers(seed_data["doctor_user"].username), params={"feature_key": "patient_summary"})
    assert response.status_code == 200, response.text
    assert run.run_id not in {row["run_id"] for row in response.json()["data"]}
