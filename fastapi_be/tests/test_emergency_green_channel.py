import pytest


@pytest.mark.asyncio
class TestEmergencyGreenChannel:
    async def test_green_channel_approval_lifecycle(self, async_client, seed_data, auth_headers):
        nurse_headers = auth_headers(seed_data["nurse_user"].username)
        triage = await async_client.post("/api/emergency/triage/create", headers=nurse_headers, json={"patient_id": seed_data["patient"].patient_id, "triage_level": 1, "chief_complaint": "胸痛", "green_channel": 1})
        triage_id = triage.json()["data"]["triage_id"]
        created = await async_client.post("/api/emergency/greenChannel/create", headers=nurse_headers, json={"triage_id": triage_id, "reason": "疑似急性心肌梗死，需先救治后付费"})
        assert created.json()["code"] == 200
        channel_id = created.json()["data"]["channel_id"]
        duplicate = await async_client.post("/api/emergency/greenChannel/create", headers=nurse_headers, json={"triage_id": triage_id, "reason": "重复申请"})
        assert duplicate.json()["code"] == 500
        approved = await async_client.post("/api/emergency/greenChannel/approve", headers=auth_headers(seed_data["director_user"].username), json={"channel_id": channel_id, "note": "同意先救治"})
        assert approved.json()["data"]["status_text"] == "已批准"
        closed = await async_client.post("/api/emergency/greenChannel/close", headers=nurse_headers, json={"channel_id": channel_id, "note": "费用已补录"})
        assert closed.json()["data"]["status_text"] == "已关闭"

    async def test_green_channel_requires_flag_and_approval(self, async_client, seed_data, auth_headers):
        nurse_headers = auth_headers(seed_data["nurse_user"].username)
        triage = await async_client.post("/api/emergency/triage/create", headers=nurse_headers, json={"patient_id": seed_data["patient"].patient_id, "triage_level": 2, "chief_complaint": "发热"})
        response = await async_client.post("/api/emergency/greenChannel/create", headers=nurse_headers, json={"triage_id": triage.json()["data"]["triage_id"], "reason": "未标记"})
        assert response.json()["code"] == 500
