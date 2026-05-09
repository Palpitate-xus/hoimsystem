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

    async def test_logout(self, async_client):
        r = await async_client.post("/api/logout")
        assert r.status_code == 200
        assert r.json()["code"] == 200

    async def test_echo(self, async_client):
        r = await async_client.post("/api/test", json={"data": "hello"})
        assert r.status_code == 200
        assert r.json()["data"] == "hello"
