import pytest


@pytest.mark.asyncio
class TestMonitor:
    async def test_monitor_summary(self, async_client, seed_data, auth_headers):
        headers = auth_headers(seed_data["admin_user"].username)
        response = await async_client.get("/api/monitor/summary", headers=headers)
        assert response.json()["code"] == 200
        assert {"total_requests", "failed_requests", "error_rate", "online_users", "average_response_time_ms"}.issubset(response.json()["data"])
        assert response.json()["data"]["scope"] == "current_worker"

    async def test_metrics_and_request_id(self, async_client):
        response = await async_client.get("/health/live", headers={"x-request-id": "test-request-42"})
        assert response.status_code == 200
        assert response.headers["x-request-id"] == "test-request-42"

        metrics = await async_client.get("/metrics")
        assert metrics.status_code == 200
        assert "hoimsystem_http_requests_total" in metrics.text
        assert "hoimsystem_http_request_duration_seconds" in metrics.text

    async def test_readiness_checks_database(self, async_client):
        response = await async_client.get("/health/ready")
        assert response.status_code == 200
        assert response.json()["status"] == "ready"
