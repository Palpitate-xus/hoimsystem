import pytest


@pytest.mark.asyncio
class TestSpecialDrug:
    async def test_dual_check_ledger_updates_stock(self, async_client, seed_data, auth_headers, db_session):
        pharmacist_headers = auth_headers(seed_data["pharmacist_user"].username)
        admin_headers = auth_headers(seed_data["admin_user"].username)
        created = await async_client.post("/api/specialDrug/create", headers=pharmacist_headers, json={"pharmaceutical_id": seed_data["pharmaceutical"].pharmaceutical_id, "action": "out", "quantity": 3, "reason": "特殊处方发出"})
        assert created.json()["code"] == 200
        register_id = created.json()["data"]["register_id"]
        same_user = await async_client.post("/api/specialDrug/approve", headers=pharmacist_headers, json={"register_id": register_id})
        assert same_user.status_code == 403
        initial_stock = seed_data["pharmaceutical"].stock
        approved = await async_client.post("/api/specialDrug/approve", headers=admin_headers, json={"register_id": register_id})
        assert approved.json()["code"] == 200
        db_session.refresh(seed_data["pharmaceutical"])
        assert seed_data["pharmaceutical"].stock == initial_stock - 3
        listed = await async_client.get("/api/specialDrug/list", headers=pharmacist_headers)
        item = next(row for row in listed.json()["data"] if row["register_id"] == register_id)
        assert item["status"] == 1

    async def test_special_drug_rejects_invalid_action(self, async_client, seed_data, auth_headers):
        response = await async_client.post("/api/specialDrug/create", headers=auth_headers(seed_data["pharmacist_user"].username), json={"pharmaceutical_id": seed_data["pharmaceutical"].pharmaceutical_id, "action": "transfer", "quantity": 1, "reason": "错误操作"})
        assert response.json()["code"] == 500
