import pytest


@pytest.mark.asyncio
async def test_login_rate_limit_after_repeated_failures(async_client):
    username = "rate-limit-nonexistent-user"
    for _ in range(5):
        response = await async_client.post("/api/login", json={"username": username, "password": "wrong-password"})
        assert response.json()["code"] == 500
    blocked = await async_client.post("/api/login", json={"username": username, "password": "wrong-password"})
    assert blocked.status_code == 429
    assert blocked.json()["code"] == 429
