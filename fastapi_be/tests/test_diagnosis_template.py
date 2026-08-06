import pytest


@pytest.mark.asyncio
class TestDiagnosisTemplate:
    async def test_doctor_can_create_apply_update_and_delete_template(self, async_client, seed_data, auth_headers):
        headers = auth_headers(seed_data["doctor_user"].username)
        created = await async_client.post(
            "/api/diagnosisTemplate/create", headers=headers, json={"code": "i10", "name": "高血压"}
        )
        assert created.json()["code"] == 200
        template_id = created.json()["data"]["template_id"]

        listed = await async_client.get("/api/diagnosisTemplate/list", headers=headers)
        assert listed.json()["data"][0]["code"] == "I10"
        applied = await async_client.post(
            "/api/diagnosisTemplate/apply", headers=headers, json={"template_id": template_id}
        )
        assert applied.json()["data"] == {"code": "I10", "name": "高血压"}

        updated = await async_client.put(
            "/api/diagnosisTemplate/update",
            headers=headers,
            json={"template_id": template_id, "code": "I11", "name": "高血压性心脏病"},
        )
        assert updated.json()["code"] == 200
        deleted = await async_client.post(
            "/api/diagnosisTemplate/delete", headers=headers, json={"template_id": template_id}
        )
        assert deleted.json()["code"] == 200

    async def test_patient_cannot_manage_diagnosis_template(self, async_client, seed_data, auth_headers):
        response = await async_client.get(
            "/api/diagnosisTemplate/list", headers=auth_headers(seed_data["patient_user"].username)
        )
        assert response.status_code == 403
