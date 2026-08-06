import pytest


@pytest.mark.asyncio
class TestEmergencyObservation:
    async def _triage(self, async_client, seed_data, auth_headers):
        response = await async_client.post(
            "/api/emergency/triage/create",
            headers=auth_headers(seed_data["nurse_user"].username),
            json={"patient_id": seed_data["patient"].patient_id, "triage_level": 3, "chief_complaint": "腹痛"},
        )
        return response.json()["data"]["triage_id"]

    async def test_observation_lifecycle_and_fee(self, async_client, seed_data, auth_headers):
        triage_id = await self._triage(async_client, seed_data, auth_headers)
        nurse_headers = auth_headers(seed_data["nurse_user"].username)
        created = await async_client.post("/api/emergency/observation/create", headers=nurse_headers, json={"triage_id": triage_id, "condition": "腹痛缓解，生命体征平稳", "medical_advice": "继续观察", "fee_amount": 35.5})
        assert created.json()["code"] == 200
        observation_id = created.json()["data"]["observation_id"]
        duplicate = await async_client.post("/api/emergency/observation/create", headers=nurse_headers, json={"triage_id": triage_id, "condition": "重复留观"})
        assert duplicate.json()["code"] == 500
        updated = await async_client.put("/api/emergency/observation/update", headers=auth_headers(seed_data["doctor_user"].username), json={"observation_id": observation_id, "condition": "症状稳定", "fee_status": 1, "status": 2})
        assert updated.json()["data"]["status_text"] == "已结束"
        listed = await async_client.get("/api/emergency/observation/list", headers=nurse_headers, params={"status": 2})
        assert len(listed.json()["data"]) == 1
        assert listed.json()["data"][0]["fee_amount"] == 35.5

    async def test_observation_rejects_invalid_triage_and_transition(self, async_client, seed_data, auth_headers):
        nurse_headers = auth_headers(seed_data["nurse_user"].username)
        missing = await async_client.post("/api/emergency/observation/create", headers=nurse_headers, json={"triage_id": "missing", "condition": "无效"})
        assert missing.json()["code"] == 500
        triage_id = await self._triage(async_client, seed_data, auth_headers)
        created = await async_client.post("/api/emergency/observation/create", headers=nurse_headers, json={"triage_id": triage_id, "condition": "观察中"})
        observation_id = created.json()["data"]["observation_id"]
        ended = await async_client.put("/api/emergency/observation/update", headers=nurse_headers, json={"observation_id": observation_id, "status": 3})
        assert ended.json()["code"] == 200
        restored = await async_client.put("/api/emergency/observation/update", headers=nurse_headers, json={"observation_id": observation_id, "status": 1})
        assert restored.json()["code"] == 500
