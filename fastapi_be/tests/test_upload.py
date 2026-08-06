import pytest


@pytest.mark.asyncio
class TestReportDownloadSecurity:
    async def test_report_download_requires_authentication(self, async_client):
        r = await async_client.get("/api/uploads/reports/not-found.pdf")
        assert r.status_code == 401

    async def test_authenticated_report_download_returns_not_found_for_missing_file(
        self, async_client, seed_data, auth_headers
    ):
        r = await async_client.get(
            "/api/uploads/reports/not-found.pdf",
            headers=auth_headers(seed_data["patient_user"].username),
        )
        assert r.status_code == 404
