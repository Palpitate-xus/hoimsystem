import pytest


@pytest.mark.asyncio
class TestIcd10:
    async def test_diagnosis_and_operation_catalog(self, async_client, seed_data, auth_headers):
        admin_headers = auth_headers(seed_data["admin_user"].username)
        doctor_headers = auth_headers(seed_data["doctor_user"].username)
        diagnosis = await async_client.post("/api/icd10/diagnosis/create", headers=admin_headers, json={"code": "I10", "name": "高血压", "category": "循环系统"})
        assert diagnosis.json()["code"] == 200
        diagnosis_id = diagnosis.json()["data"]["id"]
        listing = await async_client.get("/api/icd10/diagnosis/list", headers=doctor_headers, params={"keyword": "高血压"})
        assert listing.json()["data"][0]["code"] == "I10"
        updated = await async_client.put("/api/icd10/diagnosis/update", headers=admin_headers, json={"id": diagnosis_id, "name": "原发性高血压"})
        assert updated.json()["code"] == 200
        operation = await async_client.post("/api/icd10/operation/create", headers=admin_headers, json={"code": "00.1", "name": "操作示例"})
        assert operation.json()["code"] == 200
        operations = await async_client.get("/api/icd10/operation/list", headers=doctor_headers)
        assert operations.json()["data"][0]["code"] == "00.1"
