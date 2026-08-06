import pytest


@pytest.mark.asyncio
class TestInfusion:
    async def test_infusion_lifecycle(self, async_client, seed_data, auth_headers):
        doctor_headers = auth_headers(seed_data["doctor_user"].username)
        nurse_headers = auth_headers(seed_data["nurse_user"].username)
        created = await async_client.post(
            "/api/infusion/create",
            headers=doctor_headers,
            json={"patient_id": seed_data["patient"].patient_id, "pharmaceutical_id": seed_data["pharmaceutical"].pharmaceutical_id, "dose": "100ml", "batch_no": "B-001", "drip_rate": 40},
        )
        assert created.status_code == 200
        infusion_id = created.json()["data"]["infusion_id"]
        executed = await async_client.post("/api/infusion/execute", headers=nurse_headers, json={"infusion_id": infusion_id})
        assert executed.json()["code"] == 200
        observed = await async_client.post("/api/infusion/observe", headers=nurse_headers, json={"infusion_id": infusion_id, "drip_rate": 45, "volume": 80, "condition": "滴速平稳，无不适"})
        assert observed.json()["code"] == 200
        completed = await async_client.post("/api/infusion/complete", headers=nurse_headers, json={"infusion_id": infusion_id})
        assert completed.json()["code"] == 200
        listed = await async_client.get("/api/infusion/list", headers=nurse_headers)
        target = next(item for item in listed.json()["data"] if item["infusion_id"] == infusion_id)
        assert target["status"] == 2
        assert target["observations"][0]["drip_rate"] == 45

    async def test_infusion_rejects_invalid_transitions_and_unauthorized_completion(self, async_client, seed_data, auth_headers):
        doctor_headers = auth_headers(seed_data["doctor_user"].username)
        nurse_headers = auth_headers(seed_data["nurse_user"].username)
        created = await async_client.post(
            "/api/infusion/create",
            headers=doctor_headers,
            json={"patient_id": seed_data["patient"].patient_id, "pharmaceutical_id": seed_data["pharmaceutical"].pharmaceutical_id, "dose": "100ml", "batch_no": "B-002"},
        )
        infusion_id = created.json()["data"]["infusion_id"]
        not_running = await async_client.post("/api/infusion/observe", headers=nurse_headers, json={"infusion_id": infusion_id, "drip_rate": 40, "condition": "不应成功"})
        assert not_running.json()["code"] == 500
        completed = await async_client.post("/api/infusion/complete", headers=auth_headers(seed_data["director_user"].username), json={"infusion_id": infusion_id})
        assert completed.status_code == 403
        cancelled = await async_client.post("/api/infusion/cancel", headers=doctor_headers, json={"infusion_id": infusion_id})
        assert cancelled.json()["code"] == 200
        execute_cancelled = await async_client.post("/api/infusion/execute", headers=nurse_headers, json={"infusion_id": infusion_id})
        assert execute_cancelled.json()["code"] == 500
