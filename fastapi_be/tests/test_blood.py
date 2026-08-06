import pytest


@pytest.mark.asyncio
class TestBlood:
    async def test_blood_request_recheck_crossmatch_issue_and_reaction(self, async_client, seed_data, auth_headers):
        doctor_headers = auth_headers(seed_data["doctor_user"].username)
        request = await async_client.post("/api/blood/request/create", headers=doctor_headers, json={"patient_id": seed_data["patient"].patient_id, "blood_type": "A+", "component": "红细胞", "volume": 2, "reason": "手术备血"})
        assert request.json()["code"] == 200
        request_id = request.json()["data"]["request_id"]
        director_headers = auth_headers(seed_data["director_user"].username)
        assert (await async_client.post("/api/blood/request/review", headers=director_headers, json={"request_id": request_id, "status": 1})).json()["code"] == 200
        nurse_headers = auth_headers(seed_data["nurse_user"].username)
        assert (await async_client.post("/api/blood/recheck", headers=nurse_headers, json={"request_id": request_id, "verified": True})).json()["code"] == 200
        assert (await async_client.post("/api/blood/crossMatch", headers=nurse_headers, json={"request_id": request_id, "donor_blood_type": "A+", "result": "相合", "pass_flag": 1})).json()["code"] == 200
        issue = await async_client.post("/api/blood/issue", headers=nurse_headers, json={"request_id": request_id, "unit_no": "UNIT-001", "volume": 2})
        assert issue.json()["code"] == 200
        reaction = await async_client.post("/api/blood/reaction/create", headers=nurse_headers, json={"request_id": request_id, "symptoms": "轻微发热", "action_taken": "暂停输血并观察"})
        assert reaction.json()["code"] == 200

    async def test_patient_cannot_create_blood_request(self, async_client, seed_data, auth_headers):
        response = await async_client.post("/api/blood/request/create", headers=auth_headers(seed_data["patient_user"].username), json={})
        assert response.status_code == 403
