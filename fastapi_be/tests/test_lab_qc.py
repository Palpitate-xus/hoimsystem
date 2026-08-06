import pytest


@pytest.mark.asyncio
class TestLabQc:
    async def test_qc_record_and_summary(self, async_client, seed_data, auth_headers):
        headers = auth_headers(seed_data["lab_tech_user"].username)
        passed = await async_client.post("/api/labQc/create", headers=headers, json={"qc_name": "血糖质控", "level": "高值", "target_value": 10, "measured_value": 10.2, "unit": "mmol/L"})
        assert passed.json()["data"]["pass_text"] == "通过"
        failed = await async_client.post("/api/labQc/create", headers=headers, json={"qc_name": "血糖质控", "level": "低值", "target_value": 4, "measured_value": 5, "unit": "mmol/L"})
        assert failed.json()["data"]["pass_text"] == "不通过"
        summary = await async_client.get("/api/labQc/summary", headers=headers)
        assert summary.json()["data"]["failed"] == 1
