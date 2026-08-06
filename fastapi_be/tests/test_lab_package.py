import pytest


@pytest.mark.asyncio
class TestLabPackage:
    async def test_lab_package_maintenance_and_query(self, async_client, seed_data, auth_headers):
        admin_headers = auth_headers(seed_data["admin_user"].username)
        doctor_headers = auth_headers(seed_data["doctor_user"].username)
        created = await async_client.post("/api/labPackage/create", headers=admin_headers, json={"code": "CBC", "name": "血常规", "category": "血液学", "items": "白细胞,红细胞,血红蛋白", "price": 35})
        assert created.json()["code"] == 200
        package_id = created.json()["data"]["package_id"]
        listed = await async_client.get("/api/labPackage/list", headers=doctor_headers, params={"keyword": "血常规"})
        assert listed.json()["data"][0]["code"] == "CBC"
        updated = await async_client.put("/api/labPackage/update", headers=admin_headers, json={"package_id": package_id, "price": 40})
        assert updated.json()["data"]["price"] == 40
