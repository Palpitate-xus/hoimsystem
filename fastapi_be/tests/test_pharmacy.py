import pytest


@pytest.mark.asyncio
class TestPharmaceuticalManagement:
    async def test_get_list(self, async_client, seed_data, auth_headers):
        r = await async_client.get("/api/pharmaceuticalManagement/getList", headers=auth_headers(seed_data["pharmacist_user"].username))
        assert r.status_code == 200
        body = r.json()
        assert body["code"] == 200
        assert len(body["data"]) >= 1
        assert body["data"][0]["name"] == "阿司匹林"

    async def test_create(self, async_client, seed_data, auth_headers):
        headers = auth_headers(seed_data["pharmacist_user"].username)
        r = await async_client.post("/api/pharmaceuticalManagement/create", headers=headers, json={
            "name": "布洛芬", "stock": 200, "price": "20.0",
            "expireddate": "2028-01-01", "supplier": "测试供应商", "remark": "退烧药"
        })
        assert r.status_code == 200
        assert r.json()["code"] == 200

    async def test_update(self, async_client, seed_data, auth_headers):
        pha = seed_data["pharmaceutical"]
        headers = auth_headers(seed_data["pharmacist_user"].username)
        r = await async_client.post("/api/pharmaceuticalManagement/update", headers=headers, json={
            "pharmaceutical_id": pha.pharmaceutical_id, "name": "阿司匹林改",
            "stock": 150, "price": "18.0", "expireddate": "2027-12-01",
            "supplier": "新供应商", "remark": "备注改"
        })
        assert r.status_code == 200
        assert r.json()["code"] == 200

    async def test_delete(self, async_client, seed_data, auth_headers):
        headers = auth_headers(seed_data["pharmacist_user"].username)
        r = await async_client.post("/api/pharmaceuticalManagement/create", headers=headers, json={
            "name": "待删除药", "stock": 10, "price": "5.0",
            "expireddate": "2028-01-01", "supplier": "测试", "remark": ""
        })
        assert r.json()["code"] == 200
        r = await async_client.get("/api/pharmaceuticalManagement/getList", headers=headers)
        phas = r.json()["data"]
        target = [p for p in phas if p["name"] == "待删除药"][0]

        r = await async_client.post("/api/pharmaceuticalManagement/delete", headers=headers, json={"pharmaceutical_id": target["id"]})
        assert r.status_code == 200
        assert r.json()["code"] == 200

    async def test_stock_query(self, async_client, seed_data, auth_headers):
        r = await async_client.post("/api/pharmaceuticalManagement/stock_query", headers=auth_headers(seed_data["pharmacist_user"].username), json={"id": seed_data["pharmaceutical"].pharmaceutical_id})
        assert r.status_code == 200
        body = r.json()
        assert body["code"] == 200
        assert "stock" in body["data"]


@pytest.mark.asyncio
class TestPharmacy:
    async def test_dispense_list(self, async_client, seed_data, auth_headers):
        r = await async_client.get("/api/pharmacy/dispenseList", headers=auth_headers(seed_data["pharmacist_user"].username))
        assert r.status_code == 200
        body = r.json()
        assert body["code"] == 200
        assert len(body["data"]) >= 1

    async def test_audit(self, async_client, seed_data, auth_headers):
        pre = seed_data["prescription"]
        headers = auth_headers(seed_data["pharmacist_user"].username)
        r = await async_client.post("/api/pharmacy/audit", headers=headers, json={"prescription_id": str(pre.prescription_id)})
        assert r.status_code == 200
        assert r.json()["code"] == 200

    async def test_dispense(self, async_client, seed_data, auth_headers):
        pharmacist_headers = auth_headers(seed_data["pharmacist_user"].username)
        doctor_headers = auth_headers(seed_data["doctor_user"].username)
        r = await async_client.post("/api/prescriptionManagement/create", headers=doctor_headers, json={
            "patient": seed_data["patient2"].patient_id,
            "phas": [{"id": seed_data["pharmaceutical"].pharmaceutical_id, "number": 1}]
        })
        assert r.json()["code"] == 200
        r = await async_client.get("/api/prescriptionManagement/getList", headers=doctor_headers)
        pres = r.json()["data"]
        target = [p for p in pres if p["status"] == 0][0]

        r = await async_client.post("/api/pharmacy/audit", headers=pharmacist_headers, json={"prescription_id": target["uuid"]})
        assert r.json()["code"] == 200

        r = await async_client.post("/api/pharmacy/dispense", headers=pharmacist_headers, json={"prescription_id": target["uuid"]})
        assert r.status_code == 200
        assert r.json()["code"] == 200

    async def test_return(self, async_client, seed_data, auth_headers):
        r = await async_client.post("/api/pharmacy/return", headers=auth_headers(seed_data["pharmacist_user"].username), json={
            "prescription_id": str(seed_data["prescription"].prescription_id),
            "pha_id": seed_data["pharmaceutical"].pharmaceutical_id,
            "number": 1, "reason": "过敏"
        })
        assert r.status_code == 200
        assert r.json()["code"] == 200
