import pytest
import datetime


@pytest.mark.asyncio
class TestQueue:
    async def test_get_list(self, async_client, seed_data, auth_headers):
        r = await async_client.get("/api/queue/getList", headers=auth_headers(seed_data["admin_user"].username))
        assert r.status_code == 200
        assert r.json()["code"] == 200

    async def test_call_next_no_patient(self, async_client, seed_data, auth_headers):
        headers = auth_headers(seed_data["admin_user"].username)
        r = await async_client.post("/api/queue/callNext", headers=headers, json={"doctor_id": seed_data["doctor"].doctor_id})
        # No queue items, should return 500 or success with no data
        assert r.status_code == 200


@pytest.mark.asyncio
class TestCheckIn:
    async def test_check_in_fail_wrong_identity(self, async_client, seed_data):
        r = await async_client.post("/api/checkIn/checkIn", json={
            "appointment_uuid": "nonexistent-uuid", "identity": "wrong-id"
        })
        assert r.status_code == 200
        assert r.json()["code"] == 500


@pytest.mark.asyncio
class TestVitalSign:
    async def test_create_vital_sign(self, async_client, seed_data, auth_headers):
        r = await async_client.post("/api/vitalSign/create", headers=auth_headers(seed_data["admin_user"].username), json={
            "patient_id": seed_data["patient"].patient_id,
            "temperature": 36.5, "blood_pressure_systolic": 120,
            "blood_pressure_diastolic": 80, "pulse": 75, "weight": 70.0
        })
        assert r.status_code == 200
        assert r.json()["code"] == 200

    async def test_get_list(self, async_client, seed_data, auth_headers):
        r = await async_client.get("/api/vitalSign/getList", headers=auth_headers(seed_data["admin_user"].username))
        assert r.status_code == 200
        body = r.json()
        assert body["code"] == 200


@pytest.mark.asyncio
class TestLab:
    async def test_create_lab_result(self, async_client, seed_data, auth_headers):
        # create a lab order first
        doctor_headers = auth_headers(seed_data["doctor_user"].username)
        admin_headers = auth_headers(seed_data["admin_user"].username)
        r = await async_client.post("/api/labOrder/create", headers=doctor_headers, json={
            "patient_id": seed_data["patient"].patient_id, "check_type": "尿常规",
            "check_items": ["尿蛋白"], "urgent": 0
        })
        assert r.json()["code"] == 200
        lab_order_id = r.json()["data"]["lab_order_id"]

        # create result
        r = await async_client.post("/api/labResult/create", headers=admin_headers, json={
            "lab_order_id": lab_order_id, "sample_id": "S001",
            "result": "正常", "abnormal_flag": 0
        })
        assert r.status_code == 200
        assert r.json()["code"] == 200

    async def test_get_pending(self, async_client, seed_data, auth_headers):
        r = await async_client.get("/api/labResult/getPending", headers=auth_headers(seed_data["admin_user"].username))
        assert r.status_code == 200
        body = r.json()
        assert body["code"] == 200

    async def test_get_lab_result_list(self, async_client, seed_data, auth_headers):
        r = await async_client.get("/api/labResult/getList", headers=auth_headers(seed_data["admin_user"].username))
        assert r.status_code == 200
        body = r.json()
        assert body["code"] == 200

    async def test_audit_lab_result(self, async_client, seed_data, auth_headers):
        # create order and result
        doctor_headers = auth_headers(seed_data["doctor_user"].username)
        admin_headers = auth_headers(seed_data["admin_user"].username)
        r = await async_client.post("/api/labOrder/create", headers=doctor_headers, json={
            "patient_id": seed_data["patient2"].patient_id, "check_type": "心电图",
            "check_items": ["心率"], "urgent": 1
        })
        lab_order_id = r.json()["data"]["lab_order_id"]

        r = await async_client.post("/api/labResult/create", headers=admin_headers, json={
            "lab_order_id": lab_order_id, "sample_id": "S002",
            "result": "窦性心律", "abnormal_flag": 0
        })

        # get result id
        r = await async_client.get("/api/labResult/getList", headers=admin_headers)
        results = r.json()["data"]
        target = [x for x in results if x["check_name"] == "心电图"][0]

        r = await async_client.post("/api/labResult/audit", headers=admin_headers, json={"lab_result_id": target["id"]})
        assert r.status_code == 200
        assert r.json()["code"] == 200

    async def test_lab_result_detail(self, async_client, seed_data, auth_headers):
        admin_headers = auth_headers(seed_data["admin_user"].username)
        r = await async_client.get("/api/labResult/getList", headers=admin_headers)
        results = r.json()["data"]
        if results:
            r = await async_client.post("/api/labResult/detail", headers=admin_headers, json={"lab_result_id": results[0]["id"]})
            assert r.status_code == 200
            assert r.json()["code"] == 200
