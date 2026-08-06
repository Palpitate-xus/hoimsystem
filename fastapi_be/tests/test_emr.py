import pytest


@pytest.mark.asyncio
class TestStructuredMedicalRecordIntegrity:
    async def test_signed_record_cannot_be_updated_or_deleted(self, async_client, seed_data, auth_headers):
        headers = auth_headers(seed_data["doctor_user"].username)
        create = await async_client.post(
            "/api/structuredMedicalRecord/create",
            headers=headers,
            json={
                "patient_id": seed_data["patient"].patient_id,
                "doctor_id": seed_data["doctor"].doctor_id,
                "record_type": 0,
                "chief_complaint": "签名测试",
            },
        )
        assert create.status_code == 200
        assert create.json()["code"] == 200
        record_id = create.json()["data"]["record_id"]

        sign = await async_client.post(
            "/api/structuredMedicalRecord/sign",
            headers=headers,
            json={"record_id": record_id},
        )
        assert sign.status_code == 200
        assert sign.json()["code"] == 200

        update = await async_client.post(
            "/api/structuredMedicalRecord/update",
            headers=headers,
            json={"record_id": record_id, "diagnosis": "不应被修改"},
        )
        assert update.status_code == 200
        assert update.json()["code"] == 403

        repeat_sign = await async_client.post(
            "/api/structuredMedicalRecord/sign",
            headers=headers,
            json={"record_id": record_id},
        )
        assert repeat_sign.status_code == 200
        assert repeat_sign.json()["code"] == 500

        delete = await async_client.post(
            "/api/structuredMedicalRecord/delete",
            headers=headers,
            json={"record_id": record_id},
        )
        assert delete.status_code == 200
        assert delete.json()["code"] == 403

    async def test_doctor_can_only_access_owned_structured_records(self, async_client, seed_data, auth_headers):
        doctor_headers = auth_headers(seed_data["doctor_user"].username)
        director_headers = auth_headers(seed_data["director_user"].username)
        create = await async_client.post(
            "/api/structuredMedicalRecord/create",
            headers=doctor_headers,
            json={
                "patient_id": seed_data["patient2"].patient_id,
                "doctor_id": seed_data["doctor"].doctor_id,
                "record_type": 2,
                "chief_complaint": "归属隔离测试",
            },
        )
        assert create.json()["code"] == 200
        record_id = create.json()["data"]["record_id"]

        detail = await async_client.get(
            "/api/structuredMedicalRecord/detail",
            headers=director_headers,
            params={"record_id": record_id},
        )
        assert detail.status_code == 200
        assert detail.json()["code"] == 403

        records = await async_client.get("/api/structuredMedicalRecord/getList", headers=director_headers)
        assert records.status_code == 200
        assert all(item["record_id"] != record_id for item in records.json()["data"])
