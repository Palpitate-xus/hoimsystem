import pytest


@pytest.mark.asyncio
async def test_login_rate_limit_after_repeated_failures(async_client):
    username = "rate-limit-nonexistent-user"
    for _ in range(5):
        response = await async_client.post("/api/login", json={"username": username, "password": "wrong-password"})
        assert response.status_code == 400
        assert response.json()["code"] == 500
    blocked = await async_client.post("/api/login", json={"username": username, "password": "wrong-password"})
    assert blocked.status_code == 429
    assert blocked.json()["code"] == 429


@pytest.mark.asyncio
async def test_state_changing_request_rejects_untrusted_origin(async_client, seed_data, auth_headers):
    response = await async_client.post(
        "/api/departmentManagement/create",
        headers={**auth_headers(seed_data["admin_user"].username), "Origin": "https://evil.example"},
        json={"name": "跨站测试科室", "phone": "01000000000", "location": "测试楼"},
    )
    assert response.status_code == 403
    assert response.json()["code"] == 403
