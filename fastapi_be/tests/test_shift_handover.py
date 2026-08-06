import pytest


@pytest.mark.asyncio
class TestShiftHandover:
    async def test_handover_receive_lifecycle(self, async_client, seed_data, auth_headers):
        nurse_headers = auth_headers(seed_data["nurse_user"].username)
        created = await async_client.post("/api/shiftHandover/create", headers=nurse_headers, json={"shift_type": "白班", "content": "1床患者待观察体温"})
        assert created.json()["code"] == 200
        handover_id = created.json()["data"]["handover_id"]
        same_nurse = await async_client.post("/api/shiftHandover/receive", headers=nurse_headers, json={"handover_id": handover_id})
        assert same_nurse.json()["code"] == 500
        listed = await async_client.get("/api/shiftHandover/list", headers=nurse_headers)
        assert next(row for row in listed.json()["data"] if row["handover_id"] == handover_id)["status"] == 0

    async def test_handover_validates_content(self, async_client, seed_data, auth_headers):
        response = await async_client.post("/api/shiftHandover/create", headers=auth_headers(seed_data["nurse_user"].username), json={"shift_type": "夜班", "content": ""})
        assert response.status_code == 422
