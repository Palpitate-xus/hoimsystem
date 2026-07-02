import pytest


@pytest.mark.asyncio
class TestDoctorSchedule:
    async def test_register_schedule(self, async_client, seed_data, auth_headers):
        doctor = seed_data["doctor"]
        r = await async_client.post("/api/doctorScheduleManagement/register", headers=auth_headers(seed_data["admin_user"].username), json={
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

    async def test_update_medical_record(self, async_client, seed_data, auth_headers):
        mr = seed_data["medical_record"]
        r = await async_client.post("/api/medicalRecord/update", headers=auth_headers(seed_data["doctor_user"].username), json={
            "medical_record_id": str(mr.medical_record_id), "symptom": "头痛发热改", "result": "感冒"
        })
        assert r.status_code == 200
        assert r.json()["code"] == 200

    async def test_update_medical_record_rejects_other(self, async_client, seed_data, auth_headers):
        mr = seed_data["medical_record"]
        r = await async_client.post("/api/medicalRecord/update", headers=auth_headers(seed_data["director_user"].username), json={
            "medical_record_id": str(mr.medical_record_id), "symptom": "hack", "result": "hack"
        })
        assert r.status_code == 200
        assert r.json()["code"] == 403


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

    async def test_cancel_prescription(self, async_client, seed_data, auth_headers):
        doctor_headers = auth_headers(seed_data["doctor_user"].username)
        # 开一个新处方,避免被前面的 test_dispense 把原始处方 status 改成 2
        r = await async_client.post("/api/prescriptionManagement/create", headers=doctor_headers, json={
            "patient": seed_data["patient2"].patient_id,
            "phas": [{"id": seed_data["pharmaceutical"].pharmaceutical_id, "number": 1}]
        })
        assert r.json()["code"] == 200, f"prepare prescription failed: {r.text}"
        new_pre_id = r.json()["data"]["uuid"]
        # doctor 取消自己开立的新处方 — 成功
        r = await async_client.post("/api/prescriptionManagement/cancel", headers=doctor_headers, json={"prescription_id": new_pre_id})
        assert r.status_code == 200
        assert r.json()["code"] == 200

    async def test_cancel_prescription_rejects_dispensed(self, async_client, seed_data, auth_headers):
        pre = seed_data["prescription"]
        # 原始处方在 test_dispense 之前 status=0,但 test_dispense 会把 status 改成 2
        # 直接验证:医生不能取消已发药的处方
        # 先发药:pharmacist audit → dispense
        phar_headers = auth_headers(seed_data["pharmacist_user"].username)
        # 确保原始处方是 status=0(可能已经被 audit 或 dispense 过)
        # 直接用一个 fresh 的 prescription 走 dispense 路径然后 cancel
        # 这里只是验证 cancel 会拒绝已发药处方
        doctor_headers = auth_headers(seed_data["doctor_user"].username)
        # 开立新处方
        r = await async_client.post("/api/prescriptionManagement/create", headers=doctor_headers, json={
            "patient": seed_data["patient2"].patient_id,
            "phas": [{"id": seed_data["pharmaceutical"].pharmaceutical_id, "number": 1}]
        })
        pre_id = r.json()["data"]["uuid"]
        # 审核
        r = await async_client.post("/api/pharmacy/audit", headers=phar_headers, json={"prescription_id": pre_id})
        # 发药
        r = await async_client.post("/api/pharmacy/dispense", headers=phar_headers, json={"prescription_id": pre_id})
        # 取消 — 期望失败
        r = await async_client.post("/api/prescriptionManagement/cancel", headers=doctor_headers, json={"prescription_id": pre_id})
        assert r.status_code == 200
        assert r.json()["code"] == 500


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
