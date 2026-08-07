import pytest
import datetime

from app.models import Appointment, Patient, Queue


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

    async def test_queue_state_and_patient_visibility(self, async_client, seed_data, auth_headers, db_session):
        completed = Queue(
            patient_id=seed_data["patient2"].patient_id,
            doctor_id=seed_data["doctor"].doctor_id,
            queue_number=999,
            type=0,
            status=2,
            create_time=datetime.datetime.now(),
        )
        db_session.add(completed)
        db_session.commit()

        patient_list = await async_client.get(
            "/api/queue/getList", headers=auth_headers(seed_data["patient_user"].username)
        )
        assert patient_list.json()["code"] == 200
        assert all(item["queue_id"] != completed.queue_id for item in patient_list.json()["data"])

        admin_headers = auth_headers(seed_data["admin_user"].username)
        emergency = await async_client.post(
            "/api/queue/emergency", headers=admin_headers, json={"queue_id": completed.queue_id}
        )
        assert emergency.json()["code"] == 500

        passed = await async_client.post(
            "/api/queue/pass", headers=admin_headers, json={"queue_id": completed.queue_id}
        )
        assert passed.json()["code"] == 500


@pytest.mark.asyncio
class TestCheckIn:
    async def test_check_in_fail_wrong_identity(self, async_client, seed_data):
        r = await async_client.post("/api/checkIn/checkIn", json={
            "appointment_uuid": "nonexistent-uuid", "identity": "wrong-id"
        })
        assert r.status_code == 200
        assert r.json()["code"] == 500

    async def test_check_in_is_one_time_and_updates_appointment(self, async_client, seed_data, db_session):
        patient = Patient(name="报到测试", identity="110101199001019999", sex=1)
        db_session.add(patient)
        db_session.flush()
        appointment = Appointment(
            patient_id=patient.patient_id,
            doctor_id=seed_data["doctor"].doctor_id,
            specialist=0,
            department_id=seed_data["department"].department_id,
            appointment_time=datetime.datetime.now(),
            time=datetime.date.today(),
            status=0,
        )
        db_session.add(appointment)
        db_session.commit()
        appointment_uuid = appointment.registration_uuid

        payload = {"appointment_uuid": appointment_uuid, "identity": patient.identity}
        first = await async_client.post("/api/checkIn/checkIn", json=payload)
        assert first.status_code == 200
        assert first.json()["code"] == 200

        second = await async_client.post("/api/checkIn/checkIn", json=payload)
        assert second.status_code == 200
        assert second.json()["code"] == 500

        db_session.refresh(appointment)
        assert appointment.status == 1
        assert db_session.query(Queue).filter(Queue.registration_uuid == appointment_uuid).count() == 1


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

    @pytest.mark.parametrize(
        "field,value",
        [
            ("temperature", -1),
            ("temperature", 50),
            ("blood_pressure_systolic", -1),
            ("blood_pressure_systolic", 301),
            ("blood_pressure_diastolic", -1),
            ("blood_pressure_diastolic", 201),
            ("pulse", -1),
            ("pulse", 301),
            ("weight", -1),
            ("weight", 501),
        ],
    )
    async def test_rejects_invalid_vital_sign_ranges(self, async_client, seed_data, auth_headers, field, value):
        payload = {
            "patient_id": seed_data["patient"].patient_id,
            "temperature": 36.5,
            "blood_pressure_systolic": 120,
            "blood_pressure_diastolic": 80,
            "pulse": 75,
            "weight": 70.0,
        }
        payload[field] = value

        r = await async_client.post(
            "/api/vitalSign/create",
            headers=auth_headers(seed_data["admin_user"].username),
            json=payload,
        )

        assert r.status_code == 422

    async def test_rejects_invalid_blood_pressure_relationship(self, async_client, seed_data, auth_headers):
        r = await async_client.post(
            "/api/vitalSign/create",
            headers=auth_headers(seed_data["admin_user"].username),
            json={
                "patient_id": seed_data["patient"].patient_id,
                "temperature": 36.5,
                "blood_pressure_systolic": 80,
                "blood_pressure_diastolic": 120,
                "pulse": 75,
                "weight": 70.0,
            },
        )

        assert r.status_code == 200
        assert r.json() == {"code": 400, "msg": "收缩压必须高于舒张压"}

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

        r = await async_client.post("/api/lab/sampleReceive", headers=admin_headers, json={
            "lab_order_id": lab_order_id
        })
        assert r.json()["code"] == 200
        pending = await async_client.get("/api/labResult/getPending", headers=admin_headers)
        pending_row = next(row for row in pending.json()["data"] if row["id"] == str(lab_order_id))
        assert pending_row["sample_status"] == 1

        # create result
        r = await async_client.post("/api/labResult/create", headers=admin_headers, json={
            "lab_order_id": lab_order_id, "sample_id": "S001",
            "result": "正常", "abnormal_flag": 0
        })
        assert r.status_code == 200
        assert r.json()["code"] == 200

        tracking = await async_client.get(
            "/api/lab/sampleTracking", headers=admin_headers, params={"lab_order_id": lab_order_id}
        )
        assert [item["stage"] for item in tracking.json()["data"]] == ["申请创建", "样本已接收", "结果已录入"]

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

        r = await async_client.post("/api/lab/sampleReceive", headers=admin_headers, json={
            "lab_order_id": lab_order_id
        })
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

    async def test_lab_state_transitions_reject_invalid_steps(self, async_client, seed_data, auth_headers):
        doctor_headers = auth_headers(seed_data["doctor_user"].username)
        lab_headers = auth_headers(seed_data["admin_user"].username)
        r = await async_client.post("/api/labOrder/create", headers=doctor_headers, json={
            "patient_id": seed_data["patient"].patient_id, "check_type": "血常规",
            "check_items": ["白细胞"], "urgent": 0
        })
        lab_order_id = r.json()["data"]["lab_order_id"]

        r = await async_client.post("/api/labResult/create", headers=lab_headers, json={
            "lab_order_id": lab_order_id, "sample_id": "S003",
            "result": "正常", "abnormal_flag": 0
        })
        assert r.json()["code"] == 500

        r = await async_client.post("/api/lab/sampleReject", headers=lab_headers, json={
            "lab_order_id": lab_order_id
        })
        assert r.json()["code"] == 200

        r = await async_client.post("/api/lab/sampleReceive", headers=lab_headers, json={
            "lab_order_id": lab_order_id
        })
        assert r.json()["code"] == 500

        r = await async_client.post("/api/labResult/create", headers=lab_headers, json={
            "lab_order_id": lab_order_id, "sample_id": "S003",
            "result": "正常", "abnormal_flag": 0
        })
        assert r.json()["code"] == 500

    async def test_lab_result_cannot_be_created_or_audited_twice(self, async_client, seed_data, auth_headers):
        doctor_headers = auth_headers(seed_data["doctor_user"].username)
        lab_headers = auth_headers(seed_data["admin_user"].username)
        r = await async_client.post("/api/labOrder/create", headers=doctor_headers, json={
            "patient_id": seed_data["patient2"].patient_id, "check_type": "肝功能",
            "check_items": ["谷丙转氨酶"], "urgent": 0
        })
        lab_order_id = r.json()["data"]["lab_order_id"]
        await async_client.post("/api/lab/sampleReceive", headers=lab_headers, json={
            "lab_order_id": lab_order_id
        })

        payload = {
            "lab_order_id": lab_order_id, "sample_id": "S004",
            "result": "正常", "abnormal_flag": 0
        }
        r = await async_client.post("/api/labResult/create", headers=lab_headers, json=payload)
        assert r.json()["code"] == 200
        r = await async_client.post("/api/labResult/create", headers=lab_headers, json=payload)
        assert r.json()["code"] == 500

        results = (await async_client.get("/api/labResult/getList", headers=lab_headers)).json()["data"]
        result_id = [item["id"] for item in results if item["check_name"] == "肝功能"][0]
        r = await async_client.post("/api/labResult/audit", headers=lab_headers, json={"lab_result_id": result_id})
        assert r.json()["code"] == 200
        r = await async_client.post("/api/labResult/audit", headers=lab_headers, json={"lab_result_id": result_id})
        assert r.json()["code"] == 500

    async def test_lab_result_detail(self, async_client, seed_data, auth_headers):
        admin_headers = auth_headers(seed_data["admin_user"].username)
        r = await async_client.get("/api/labResult/getList", headers=admin_headers)
        results = r.json()["data"]
        if results:
            r = await async_client.post("/api/labResult/detail", headers=admin_headers, json={"lab_result_id": results[0]["id"]})
            assert r.status_code == 200
            assert r.json()["code"] == 200
