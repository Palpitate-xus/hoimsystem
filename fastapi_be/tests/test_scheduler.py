import pytest


@pytest.mark.asyncio
class TestScheduler:
    async def test_admin_can_view_and_run_scheduled_job(self, async_client, seed_data, auth_headers):
        headers = auth_headers(seed_data["admin_user"].username)
        status = await async_client.get("/api/scheduler/status", headers=headers)
        assert status.json()["data"]["interval_seconds"] == 3600
        assert {job["name"] for job in status.json()["data"]["jobs"]} == {"inventory_alert", "breach_statistics", "breach_scan", "backup"}
        result = await async_client.post("/api/scheduler/run/inventory_alert", headers=headers)
        assert result.json()["code"] == 200
        assert "low_stock_count" in result.json()["data"]["result"]

    async def test_patient_cannot_run_scheduler(self, async_client, seed_data, auth_headers):
        response = await async_client.get("/api/scheduler/status", headers=auth_headers(seed_data["patient_user"].username))
        assert response.status_code == 403
