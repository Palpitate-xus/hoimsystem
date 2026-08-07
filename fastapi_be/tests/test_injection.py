import datetime

import pytest

from app.models import Pharmaceutical


@pytest.mark.asyncio
class TestInjection:
    async def test_injection_lifecycle(self, async_client, seed_data, auth_headers):
        doctor_headers = auth_headers(seed_data["doctor_user"].username)
        nurse_headers = auth_headers(seed_data["nurse_user"].username)
        created = await async_client.post("/api/injection/create", headers=doctor_headers, json={"patient_id": seed_data["patient"].patient_id, "pharmaceutical_id": seed_data["pharmaceutical"].pharmaceutical_id, "route": "im", "dose": "2ml"})
        assert created.json()["code"] == 200
        injection_id = created.json()["data"]["injection_id"]
        assert (await async_client.post("/api/injection/execute", headers=nurse_headers, json={"injection_id": injection_id})).json()["code"] == 200
        assert (await async_client.post("/api/injection/complete", headers=nurse_headers, json={"injection_id": injection_id})).json()["code"] == 200
        listed = await async_client.get("/api/injection/list", headers=nurse_headers)
        item = next(row for row in listed.json()["data"] if row["injection_id"] == injection_id)
        assert item["status"] == 2

    async def test_injection_validates_route_and_transition(self, async_client, seed_data, auth_headers):
        doctor_headers = auth_headers(seed_data["doctor_user"].username)
        invalid = await async_client.post("/api/injection/create", headers=doctor_headers, json={"patient_id": seed_data["patient"].patient_id, "pharmaceutical_id": seed_data["pharmaceutical"].pharmaceutical_id, "route": "iv", "dose": "2ml"})
        assert invalid.json()["code"] == 500

    async def test_injection_rejects_expired_medication(self, async_client, seed_data, auth_headers, db_session):
        expired = Pharmaceutical(name="注射过期药", stock=10, price=1, expireddate=datetime.date.today() - datetime.timedelta(days=1), status=0)
        db_session.add(expired)
        db_session.commit()
        response = await async_client.post("/api/injection/create", headers=auth_headers(seed_data["doctor_user"].username), json={
            "patient_id": seed_data["patient"].patient_id,
            "pharmaceutical_id": expired.pharmaceutical_id,
            "route": "im",
            "dose": "2ml",
        })
        assert response.json()["code"] == 500
        assert "过期" in response.json()["msg"]

    async def test_injection_rejects_patient_allergy(self, async_client, seed_data, auth_headers, db_session):
        seed_data["patient"].allergy_history = "阿司匹林"
        db_session.commit()
        response = await async_client.post("/api/injection/create", headers=auth_headers(seed_data["doctor_user"].username), json={
            "patient_id": seed_data["patient"].patient_id,
            "pharmaceutical_id": seed_data["pharmaceutical"].pharmaceutical_id,
            "route": "im",
            "dose": "2ml",
        })
        assert response.json()["code"] == 500
        assert "过敏史冲突" in response.json()["msg"]
