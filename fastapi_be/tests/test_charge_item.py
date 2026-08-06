import pytest


@pytest.mark.asyncio
class TestChargeItem:
    async def test_charge_item_crud_and_toggle(self, async_client, seed_data, auth_headers):
        admin_headers = auth_headers(seed_data["admin_user"].username)
        cashier_headers = auth_headers(seed_data["cashier_user"].username)
        created = await async_client.post("/api/chargeItem/create", headers=admin_headers, json={"code": "REG-01", "name": "普通挂号费", "category": "挂号", "price": 15, "note": "门诊"})
        assert created.json()["code"] == 200
        item_id = created.json()["data"]["item_id"]
        duplicate = await async_client.post("/api/chargeItem/create", headers=admin_headers, json={"code": "REG-01", "name": "重复", "category": "挂号", "price": 1})
        assert duplicate.json()["code"] == 500
        assert (await async_client.put("/api/chargeItem/update", headers=admin_headers, json={"item_id": item_id, "code": "REG-01", "name": "普通挂号费调整", "category": "挂号", "price": 18})).json()["code"] == 200
        listed = await async_client.get("/api/chargeItem/list", headers=cashier_headers)
        assert next(row for row in listed.json()["data"] if row["item_id"] == item_id)["price"] == 18
        assert (await async_client.post("/api/chargeItem/toggle", headers=admin_headers, json={"item_id": item_id})).json()["code"] == 200
        disabled = await async_client.get("/api/chargeItem/list", headers=cashier_headers)
        assert next(row for row in disabled.json()["data"] if row["item_id"] == item_id)["status"] == 0

    async def test_cashier_cannot_maintain_charge_item(self, async_client, seed_data, auth_headers):
        response = await async_client.post("/api/chargeItem/create", headers=auth_headers(seed_data["cashier_user"].username), json={"code": "REG-02", "name": "挂号费", "category": "挂号", "price": 10})
        assert response.status_code == 403
