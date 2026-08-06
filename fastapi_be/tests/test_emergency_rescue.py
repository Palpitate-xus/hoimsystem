import pytest


@pytest.mark.asyncio
class TestEmergencyRescue:
    async def test_rescue_event_timeline(self, async_client, seed_data, auth_headers):
        nurse_headers = auth_headers(seed_data["nurse_user"].username)
        created = await async_client.post("/api/emergency/triage/create", headers=nurse_headers, json={"patient_id": seed_data["patient"].patient_id, "triage_level": 1, "chief_complaint": "休克"})
        triage_id = created.json()["data"]["triage_id"]
        event = await async_client.post("/api/emergency/rescue/create", headers=nurse_headers, json={"triage_id": triage_id, "event_type": "用药", "description": "建立静脉通道并给药", "medication": "肾上腺素 1mg"})
        assert event.json()["code"] == 200
        listed = await async_client.get("/api/emergency/rescue/list", headers=auth_headers(seed_data["doctor_user"].username), params={"triage_id": triage_id})
        assert len(listed.json()["data"]) == 1
        assert listed.json()["data"][0]["medication"] == "肾上腺素 1mg"

    async def test_rescue_requires_active_triage(self, async_client, seed_data, auth_headers):
        response = await async_client.post("/api/emergency/rescue/create", headers=auth_headers(seed_data["nurse_user"].username), json={"triage_id": "missing", "event_type": "操作", "description": "无效"})
        assert response.json()["code"] == 500
