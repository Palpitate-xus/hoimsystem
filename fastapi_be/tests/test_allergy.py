import pytest


@pytest.mark.asyncio
class TestPatientAllergy:
    async def test_allergy_create_update_disable_and_sync_history(self, async_client, seed_data, auth_headers):
        doctor_headers = auth_headers(seed_data["doctor_user"].username)
        patient_id = seed_data["patient"].patient_id
        created = await async_client.post("/api/allergy/create", headers=doctor_headers, json={"patient_id": patient_id, "allergen": "青霉素", "reaction": "皮疹", "severity": 2})
        assert created.json()["code"] == 200
        allergy_id = created.json()["data"]["allergy_id"]
        assert created.json()["data"]["patient_name"] == seed_data["patient"].name
        patients = await async_client.get("/api/patientManagement/getList", headers=doctor_headers)
        patient_row = next(row for row in patients.json()["data"] if row.get("id") == patient_id)
        assert "青霉素" in patient_row["allergy_history"]
        updated = await async_client.put("/api/allergy/update", headers=doctor_headers, json={"allergy_id": allergy_id, "patient_id": patient_id, "allergen": "头孢", "reaction": "呼吸困难", "severity": 3})
        assert updated.json()["code"] == 200
        assert updated.json()["data"]["severity_text"] == "重度"
        listed = await async_client.get("/api/allergy/list", headers=doctor_headers, params={"patient_id": patient_id})
        assert listed.json()["data"][0]["allergen"] == "头孢"
        assert (await async_client.post("/api/allergy/disable", headers=doctor_headers, json={"allergy_id": allergy_id})).json()["code"] == 200
        assert (await async_client.post("/api/allergy/disable", headers=doctor_headers, json={"allergy_id": allergy_id})).json()["code"] == 500

    async def test_allergy_rejects_unknown_patient(self, async_client, seed_data, auth_headers):
        response = await async_client.post("/api/allergy/create", headers=auth_headers(seed_data["nurse_user"].username), json={"patient_id": 999999, "allergen": "药物", "reaction": "皮疹", "severity": 1})
        assert response.json()["code"] == 500
