import pytest


@pytest.mark.asyncio
class TestUserAuth:
    async def test_public_key(self, async_client):
        r = await async_client.get("/api/publicKey")
        assert r.status_code == 200
        body = r.json()
        assert body["code"] == 200
        assert "publicKey" in body["data"]

    async def test_register_and_login(self, async_client):
        # register
        r = await async_client.post("/api/register", json={
            "username": "testuser", "password": "123456",
            "identity": "110101200001011111", "address": "测试地址",
            "sex": 1, "phone": "13800138001", "birthday": "2000-01-01"
        })
        assert r.status_code == 200
        assert r.json()["code"] == 200

        # login success
        r = await async_client.post("/api/login", json={
            "username": "110101200001011111", "password": "123456"
        })
        assert r.status_code == 200
        body = r.json()
        assert body["code"] == 200
        assert "accesstoken" in body["data"]
        assert len(body["data"]["accesstoken"]) > 20

    async def test_login_fail(self, async_client):
        r = await async_client.post("/api/login", json={
            "username": "nonexistent", "password": "wrong"
        })
        assert r.status_code == 200
        assert r.json()["code"] == 500

    async def test_user_info(self, async_client, seed_data):
        # login to get JWT token
        r = await async_client.post("/api/login", json={
            "username": seed_data["patient_user"].username, "password": "123456"
        })
        token = r.json()["data"]["accesstoken"]
        r = await async_client.post("/api/userInfo", json={
            "accesstoken": token
        })
        assert r.status_code == 200
        body = r.json()
        assert body["code"] == 200
        assert "permissions" in body["data"]
        assert body["data"]["permissions"] == ["patient"]

    async def test_user_info_extended_role(self, async_client, seed_data):
        r = await async_client.post("/api/login", json={
            "username": seed_data["cashier_user"].username, "password": "123456"
        })
        token = r.json()["data"]["accesstoken"]
        r = await async_client.post("/api/userInfo", json={"accesstoken": token})
        assert r.status_code == 200
        body = r.json()
        assert body["code"] == 200
        assert body["data"]["permissions"] == ["cashier"]

    async def test_logout(self, async_client):
        r = await async_client.post("/api/logout")
        assert r.status_code == 200
        assert r.json()["code"] == 200

    async def test_echo(self, async_client):
        r = await async_client.post("/api/test", json={"data": "hello"})
        assert r.status_code == 200
        assert r.json()["data"] == "hello"


@pytest.mark.asyncio
class TestPrepaidPermissions:
    async def test_patient_can_read_own_balance(self, async_client, seed_data, auth_headers):
        r = await async_client.get(
            "/api/prepaid/getBalance",
            params={"identity": seed_data["patient"].identity},
            headers=auth_headers(seed_data["patient_user"].username),
        )
        assert r.status_code == 200
        body = r.json()
        assert body["code"] == 200
        assert "balance" in body["data"]

    async def test_patient_cannot_read_other_balance(self, async_client, seed_data, auth_headers):
        r = await async_client.get(
            "/api/prepaid/getBalance",
            params={"identity": seed_data["patient2"].identity},
            headers=auth_headers(seed_data["patient_user"].username),
        )
        assert r.status_code == 200
        assert r.json()["code"] == 403

    async def test_cashier_can_recharge_and_deduct(self, async_client, seed_data, auth_headers):
        headers = auth_headers(seed_data["cashier_user"].username)
        r = await async_client.post(
            "/api/prepaid/recharge",
            headers=headers,
            json={"identity": seed_data["patient"].identity, "amount": 100},
        )
        assert r.status_code == 200
        assert r.json()["code"] == 200

        r = await async_client.post(
            "/api/prepaid/deduct",
            headers=headers,
            json={"identity": seed_data["patient"].identity, "amount": 30},
        )
        assert r.status_code == 200
        assert r.json()["code"] == 200
        assert r.json()["data"]["balance"] == 70

    async def test_patient_cannot_recharge_directly(self, async_client, seed_data, auth_headers):
        r = await async_client.post(
            "/api/prepaid/recharge",
            headers=auth_headers(seed_data["patient_user"].username),
            json={"identity": seed_data["patient"].identity, "amount": 100},
        )
        assert r.status_code == 403
