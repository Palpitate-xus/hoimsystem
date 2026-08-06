import pytest


@pytest.mark.asyncio
class TestScheduleChange:
    async def test_doctor_request_director_approval(self, async_client, seed_data, auth_headers):
        doctor_headers = auth_headers(seed_data["doctor_user"].username)
        director_headers = auth_headers(seed_data["director_user"].username)
        created = await async_client.post("/api/scheduleChange/create", headers=doctor_headers, json={"request_type": "add", "target_date": "2026-09-01", "extra_slots": 3, "reason": "增加专家号"})
        assert created.json()["code"] == 200
        request_id = created.json()["data"]["request_id"]
        own_approval = await async_client.post("/api/scheduleChange/approve", headers=doctor_headers, json={"request_id": request_id})
        assert own_approval.status_code == 403
        approved = await async_client.post("/api/scheduleChange/approve", headers=director_headers, json={"request_id": request_id})
        assert approved.json()["code"] == 200
        listed = await async_client.get("/api/scheduleChange/list", headers=doctor_headers)
        item = next(row for row in listed.json()["data"] if row["request_id"] == request_id)
        assert item["status"] == 1

    async def test_schedule_change_validates_type_and_date(self, async_client, seed_data, auth_headers):
        headers = auth_headers(seed_data["doctor_user"].username)
        invalid_type = await async_client.post("/api/scheduleChange/create", headers=headers, json={"request_type": "swap", "target_date": "2026-09-01", "reason": "调整"})
        assert invalid_type.json()["code"] == 500
        invalid_date = await async_client.post("/api/scheduleChange/create", headers=headers, json={"request_type": "stop", "target_date": "09-01", "reason": "调整"})
        assert invalid_date.json()["code"] == 500
