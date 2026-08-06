import pytest


@pytest.mark.asyncio
class TestMonitor:
    async def test_monitor_summary(self, async_client, seed_data, auth_headers):
        headers = auth_headers(seed_data["admin_user"].username)
        response = await async_client.get("/api/monitor/summary", headers=headers)
        assert response.json()["code"] == 200
        assert {"total_requests", "failed_requests", "error_rate", "online_users", "average_response_time_ms"}.issubset(response.json()["data"])
