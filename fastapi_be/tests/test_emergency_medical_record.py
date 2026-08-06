import pytest


@pytest.mark.asyncio
class TestEmergencyMedicalRecord:
    async def test_emergency_record_draft_update_and_sign(self, async_client, seed_data, auth_headers):
        nurse_headers = auth_headers(seed_data["nurse_user"].username)
        doctor_headers = auth_headers(seed_data["doctor_user"].username)
        triage = await async_client.post("/api/emergency/triage/create", headers=nurse_headers, json={"patient_id": seed_data["patient"].patient_id, "triage_level": 2, "chief_complaint": "呼吸困难"})
        record = await async_client.post("/api/emergency/medicalRecord/create", headers=doctor_headers, json={"triage_id": triage.json()["data"]["triage_id"], "chief_complaint": "呼吸困难", "present_illness": "突发", "diagnosis": "急性呼吸困难", "treatment_plan": "吸氧并观察"})
        assert record.json()["code"] == 200
        record_id = record.json()["data"]["record_id"]
        updated = await async_client.put("/api/emergency/medicalRecord/update", headers=doctor_headers, json={"record_id": record_id, "physical_exam": "血氧 92%"})
        assert updated.json()["code"] == 200
        signed = await async_client.post("/api/emergency/medicalRecord/sign", headers=doctor_headers, json={"record_id": record_id})
        assert signed.json()["data"]["status_text"] == "已签名"
        blocked = await async_client.put("/api/emergency/medicalRecord/update", headers=doctor_headers, json={"record_id": record_id, "diagnosis": "修改"})
        assert blocked.json()["code"] == 403
