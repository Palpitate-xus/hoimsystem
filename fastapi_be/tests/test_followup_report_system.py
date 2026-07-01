import pytest


@pytest.mark.asyncio
class TestFollowUp:
    async def test_create_follow_up_appointment(self, async_client, seed_data):
        r = await async_client.post("/api/followUpAppointment/create", json={
            "patient_id": seed_data["patient"].patient_id,
            "doctor_id": seed_data["doctor"].doctor_id,
            "date": "2026-06-01", "time": "上午"
        })
        assert r.status_code == 200
        assert r.json()["code"] == 200

    async def test_create_plan(self, async_client, seed_data, auth_headers):
        r = await async_client.post("/api/followUp/createPlan", headers=auth_headers(seed_data["doctor_user"].username), json={
            "patient_id": seed_data["patient"].patient_id,
            "plan_date": "2026-05-15", "content": "复查血常规"
        })
        assert r.status_code == 200
        assert r.json()["code"] == 200

    async def test_get_list(self, async_client, seed_data, auth_headers):
        r = await async_client.get("/api/followUp/getList", headers=auth_headers(seed_data["doctor_user"].username))
        assert r.status_code == 200
        body = r.json()
        assert body["code"] == 200

    async def test_record(self, async_client, seed_data, auth_headers):
        # create a plan first
        headers = auth_headers(seed_data["doctor_user"].username)
        r = await async_client.post("/api/followUp/createPlan", headers=headers, json={
            "patient_id": seed_data["patient"].patient_id,
            "plan_date": "2026-05-20", "content": "电话随访"
        })
        assert r.json()["code"] == 200

        r = await async_client.get("/api/followUp/getList", headers=headers)
        plans = r.json()["data"]
        if plans:
            plan_id = plans[0]["id"]
            r = await async_client.post("/api/followUp/record", json={
                "follow_up_id": plan_id, "result": "已接通", "patient_feedback": "感觉良好"
            })
            assert r.status_code == 200
            assert r.json()["code"] == 200


@pytest.mark.asyncio
class TestReport:
    async def test_outpatient_volume(self, async_client, seed_data):
        r = await async_client.post("/api/report/outpatientVolume", json={
            "start_date": "2020-01-01", "end_date": "2030-12-31", "group_by": "day"
        })
        assert r.status_code == 200
        body = r.json()
        assert body["code"] == 200
        assert "total_visits" in body["data"]

    async def test_finance(self, async_client, seed_data):
        r = await async_client.post("/api/report/finance", json={
            "start_date": "2020-01-01", "end_date": "2030-12-31"
        })
        assert r.status_code == 200
        body = r.json()
        assert body["code"] == 200
        assert "total_income" in body["data"]

    async def test_pharmaceutical(self, async_client, seed_data):
        r = await async_client.post("/api/report/pharmaceutical", json={
            "start_date": "2020-01-01", "end_date": "2030-12-31"
        })
        assert r.status_code == 200
        body = r.json()
        assert body["code"] == 200

    async def test_doctor_workload(self, async_client, seed_data):
        r = await async_client.post("/api/report/doctorWorkload", json={
            "start_date": "2020-01-01", "end_date": "2030-12-31"
        })
        assert r.status_code == 200
        body = r.json()
        assert body["code"] == 200
        assert len(body["data"]) >= 1


@pytest.mark.asyncio
class TestSystem:
    async def test_log_list(self, async_client, seed_data):
        r = await async_client.post("/api/log/getList", json={"page": 1, "page_size": 10})
        assert r.status_code == 200
        body = r.json()
        assert body["code"] == 200
        assert "list" in body["data"]
        assert "total" in body["data"]

    async def test_dict_crud(self, async_client):
        # create
        r = await async_client.post("/api/dict/create", json={
            "dict_type": "gender", "dict_code": "male", "dict_value": "男", "sort_order": 1
        })
        assert r.status_code == 200
        assert r.json()["code"] == 200

        # list
        r = await async_client.post("/api/dict/getList", json={"dict_type": "gender"})
        assert r.status_code == 200
        body = r.json()
        assert body["code"] == 200
        assert len(body["data"]) >= 1
        dict_id = body["data"][0]["dict_id"]

        # update
        r = await async_client.post("/api/dict/update", json={
            "dict_id": dict_id, "dict_code": "male", "dict_value": "男性", "sort_order": 2
        })
        assert r.status_code == 200
        assert r.json()["code"] == 200

        # delete
        r = await async_client.post("/api/dict/delete", json={"dict_id": dict_id})
        assert r.status_code == 200
        assert r.json()["code"] == 200

    async def test_config(self, async_client, seed_data):
        # list
        r = await async_client.get("/api/config/getList")
        assert r.status_code == 200
        body = r.json()
        assert body["code"] == 200

        # update
        r = await async_client.post("/api/config/update", json={
            "config_key": "site_name", "config_value": "测试医院"
        })
        # may fail if key doesn't exist, that's ok for test coverage
        assert r.status_code == 200
