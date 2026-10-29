"""Public business pages must not require permissions absent from the catalog."""

import json

import pytest

from app.access_models import AccessPolicy, AccessPolicyAudit


@pytest.fixture(autouse=True)
def clean_policies(db_session):
    db_session.query(AccessPolicyAudit).delete()
    db_session.query(AccessPolicy).delete()
    db_session.commit()
    yield
    db_session.rollback()
    db_session.query(AccessPolicyAudit).delete()
    db_session.query(AccessPolicy).delete()
    db_session.commit()


@pytest.mark.asyncio
@pytest.mark.parametrize("actor_key", ["patient_user", "guide_user"])
async def test_public_pages_survive_default_and_empty_business_policies(async_client, seed_data, auth_headers, db_session, actor_key):
    actor = seed_data[actor_key]
    headers = auth_headers(actor.username)
    public_codes = {"POST /api/triage/suggest", "GET /api/checkIn/getAppointments"}
    for restricted in (False, True):
        if restricted:
            db_session.add(AccessPolicy(kind="user", subject_key=str(actor.user_id), version=1, allowed_json=json.dumps([]), data_scope="existing", disabled=False))
            db_session.commit()
        response = await async_client.get("/api/access/me", headers=headers)
        assert response.status_code == 200, response.text
        snapshot = response.json()["data"]
        assert not public_codes.intersection(snapshot["permission_codes"])
        assert {"Triage", "CheckInPage"}.isdisjoint(snapshot["denied_route_names"])
        if restricted:
            assert snapshot["permission_codes"] == []
            assert "PatientMedicalRecord" in snapshot["denied_route_names"]
            assert (await async_client.get("/api/medicalRecord/getList", headers=headers)).status_code == 403


@pytest.mark.asyncio
async def test_public_triage_and_checkin_keep_their_actual_unauthenticated_contracts(async_client, seed_data):
    response = await async_client.post("/api/triage/suggest", json={"symptom": "头痛"})
    assert response.status_code == 200 and response.json()["code"] == 200
    patient = seed_data["patient"]
    response = await async_client.get("/api/checkIn/getAppointments", params={"identity": patient.identity, "phone": patient.phone[-4:]})
    assert response.status_code == 200 and response.json()["code"] == 200
