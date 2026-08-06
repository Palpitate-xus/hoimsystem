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
