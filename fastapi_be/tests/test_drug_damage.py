import pytest


@pytest.mark.asyncio
class TestDrugDamage:
    async def test_pharmacist_creates_and_admin_approves_damage(self, async_client, seed_data, auth_headers):
        pharmacist_headers = auth_headers(seed_data["pharmacist_user"].username)
        created = await async_client.post(
            "/api/pharmacy/drugDamage/create",
            headers=pharmacist_headers,
            json={"pharmaceutical_id": seed_data["pharmaceutical"].pharmaceutical_id, "quantity": 3, "damage_type": "expired", "reason": "效期到期", "batch_no": "B2026"},
        )
        assert created.json()["code"] == 200
        damage_id = created.json()["data"]["damage_id"]
        approved = await async_client.post(
            "/api/pharmacy/drugDamage/approve", headers=auth_headers(seed_data["admin_user"].username), json={"damage_id": damage_id}
        )
        assert approved.json()["data"]["status_text"] == "已通过"

    async def test_damage_cannot_exceed_stock(self, async_client, seed_data, auth_headers):
        response = await async_client.post(
            "/api/pharmacy/drugDamage/create",
            headers=auth_headers(seed_data["pharmacist_user"].username),
            json={"pharmaceutical_id": seed_data["pharmaceutical"].pharmaceutical_id, "quantity": 9999, "reason": "盘点损坏"},
        )
        assert response.json()["code"] == 400
