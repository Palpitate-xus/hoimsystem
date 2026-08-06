import pytest


@pytest.mark.asyncio
class TestEmergencyTriage:
    async def test_four_level_triage_lifecycle(self, async_client, seed_data, auth_headers):
        nurse_headers = auth_headers(seed_data["nurse_user"].username)
        doctor_headers = auth_headers(seed_data["doctor_user"].username)
        created = await async_client.post("/api/emergency/triage/create", headers=nurse_headers, json={"patient_id": seed_data["patient"].patient_id, "triage_level": 1, "chief_complaint": "意识障碍", "vital_signs": "BP 80/50", "green_channel": 1})
        assert created.json()["code"] == 200
        triage_id = created.json()["data"]["triage_id"]
        assert created.json()["data"]["triage_level_text"].startswith("一级")
        listed = await async_client.get("/api/emergency/triage/list", headers=doctor_headers)
        assert next(row for row in listed.json()["data"] if row["triage_id"] == triage_id)["green_channel"] == 1
        updated = await async_client.put("/api/emergency/triage/update", headers=nurse_headers, json={"triage_id": triage_id, "status": 1, "triage_level": 2})
        assert updated.json()["code"] == 200
        assert updated.json()["data"]["status"] == 1

    async def test_triage_validates_patient_and_level(self, async_client, seed_data, auth_headers):
        headers = auth_headers(seed_data["nurse_user"].username)
        unknown = await async_client.post("/api/emergency/triage/create", headers=headers, json={"patient_id": 999999, "triage_level": 2, "chief_complaint": "胸痛"})
        assert unknown.json()["code"] == 500
        invalid = await async_client.post("/api/emergency/triage/create", headers=headers, json={"patient_id": seed_data["patient"].patient_id, "triage_level": 5, "chief_complaint": "胸痛"})
        assert invalid.status_code == 422
