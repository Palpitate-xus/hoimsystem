import pytest


@pytest.mark.asyncio
class TestDoctorSchedule:
    async def test_register_schedule(self, async_client, seed_data, auth_headers):
        doctor = seed_data["doctor"]
        r = await async_client.post("/api/doctorScheduleManagement/register", headers=auth_headers(seed_data["doctor_user"].username), json={
            "schedule": ["星期三01", "星期三02"], "specialist": 1, "number": 15, "doctor": doctor.doctor_id
        })
        assert r.status_code == 200
        assert r.json()["code"] == 200

    async def test_get_schedule_list(self, async_client, seed_data, auth_headers):
        r = await async_client.get("/api/doctorScheduleManagement/getList", headers=auth_headers(seed_data["doctor_user"].username))
        assert r.status_code == 200
        body = r.json()
        assert body["code"] == 200
        assert len(body["data"]) >= 1


@pytest.mark.asyncio
class TestDoctorMedicalRecord:
    async def test_create_medical_record(self, async_client, seed_data, auth_headers):
        r = await async_client.post("/api/medicalRecord/create", headers=auth_headers(seed_data["doctor_user"].username), json={
            "patient_id": seed_data["patient2"].patient_id, "symptom": "咳嗽", "result": "支气管炎"
        })
        assert r.status_code == 200
        assert r.json()["code"] == 200

    async def test_get_medical_record_list_doctor(self, async_client, seed_data, auth_headers):
        r = await async_client.get("/api/medicalRecord/getList", headers=auth_headers(seed_data["doctor_user"].username))
        assert r.status_code == 200
        body = r.json()
        assert body["code"] == 200
        assert len(body["data"]) >= 1
        assert "patient_name" in body["data"][0]

    async def test_update_medical_record(self, async_client, seed_data):
        mr = seed_data["medical_record"]
        r = await async_client.post("/api/medicalRecord/update", json={
            "medical_record_id": str(mr.medical_record_id), "symptom": "头痛发热改", "result": "感冒"
        })
        assert r.status_code == 200
        assert r.json()["code"] == 200


@pytest.mark.asyncio
class TestDoctorPrescription:
    async def test_create_prescription(self, async_client, seed_data, auth_headers):
        r = await async_client.post("/api/prescriptionManagement/create", headers=auth_headers(seed_data["doctor_user"].username), json={
            "patient": seed_data["patient2"].patient_id, "phas": [{"id": seed_data["pharmaceutical"].pharmaceutical_id, "number": 1}]
        })
        assert r.status_code == 200
        assert r.json()["code"] == 200

    async def test_get_prescription_list_doctor(self, async_client, seed_data, auth_headers):
        r = await async_client.get("/api/prescriptionManagement/getList", headers=auth_headers(seed_data["doctor_user"].username))
        assert r.status_code == 200
        body = r.json()
        assert body["code"] == 200
        assert len(body["data"]) >= 1

    async def test_cancel_prescription(self, async_client, seed_data):
        pre = seed_data["prescription"]
        r = await async_client.post("/api/prescriptionManagement/cancel", json={"prescription_id": str(pre.prescription_id)})
        assert r.status_code == 200
        assert r.json()["code"] == 200


@pytest.mark.asyncio
class TestDoctorLabOrder:
    async def test_create_lab_order(self, async_client, seed_data, auth_headers):
        r = await async_client.post("/api/labOrder/create", headers=auth_headers(seed_data["doctor_user"].username), json={
            "patient_id": seed_data["patient"].patient_id, "check_type": "血常规",
            "check_items": ["白细胞", "红细胞"], "urgent": 0
        })
        assert r.status_code == 200
        body = r.json()
        assert body["code"] == 200
        assert "lab_order_id" in body["data"]

    async def test_get_lab_order_list(self, async_client, seed_data, auth_headers):
        r = await async_client.get("/api/labOrder/getList", headers=auth_headers(seed_data["doctor_user"].username))
        assert r.status_code == 200
        body = r.json()
        assert body["code"] == 200
