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
        assert "一1" in body["data"][0]["schedule"]


@pytest.mark.asyncio
class TestPrescriptionTemplate:
    async def test_doctor_can_create_apply_update_and_delete_template(self, async_client, seed_data, auth_headers):
        headers = auth_headers(seed_data["doctor_user"].username)
        created = await async_client.post(
            "/api/prescriptionTemplate/create",
            headers=headers,
            json={"name": "感冒常用方", "items": [{"id": seed_data["pharmaceutical"].pharmaceutical_id, "number": 2}]},
        )
        assert created.status_code == 200, created.text
        assert created.json()["code"] == 200
        template = created.json()["data"]
        template_id = template["template_id"]
        assert template["items"][0]["name"] == "阿司匹林"

        listed = await async_client.get("/api/prescriptionTemplate/list", headers=headers)
        assert listed.status_code == 200
        assert any(item["template_id"] == template_id for item in listed.json()["data"])
        applied = await async_client.post("/api/prescriptionTemplate/apply", headers=headers, json={"template_id": template_id})
        assert applied.status_code == 200
        assert applied.json()["data"][0]["number"] == 2

        updated = await async_client.put(
            "/api/prescriptionTemplate/update",
            headers=headers,
            json={"template_id": template_id, "name": "感冒备用方", "items": [{"id": seed_data["pharmaceutical"].pharmaceutical_id, "number": 3}]},
        )
        assert updated.status_code == 200
        assert updated.json()["data"]["name"] == "感冒备用方"

        deleted = await async_client.post("/api/prescriptionTemplate/delete", headers=headers, json={"template_id": template_id})
        assert deleted.status_code == 200
        assert deleted.json()["code"] == 200

    async def test_template_validates_items_and_isolates_doctors(self, async_client, seed_data, auth_headers):
        doctor_headers = auth_headers(seed_data["doctor_user"].username)
        invalid = await async_client.post(
            "/api/prescriptionTemplate/create",
            headers=doctor_headers,
            json={"name": "无效模板", "items": [{"id": 999999, "number": 1}]},
        )
        assert invalid.status_code == 200
        assert invalid.json()["code"] == 500

        created = await async_client.post(
            "/api/prescriptionTemplate/create",
            headers=doctor_headers,
            json={"name": "隔离模板", "items": [{"id": seed_data["pharmaceutical"].pharmaceutical_id, "number": 1}]},
        )
        template_id = created.json()["data"]["template_id"]
        other_doctor = await async_client.post(
            "/api/prescriptionTemplate/apply",
            headers=auth_headers(seed_data["director_user"].username),
            json={"template_id": template_id},
        )
        assert other_doctor.status_code == 200
        assert other_doctor.json()["code"] == 404


@pytest.mark.asyncio
class TestDiagnosisTemplate:
    async def test_doctor_can_create_apply_update_and_delete_diagnosis_template(self, async_client, seed_data, auth_headers):
        headers = auth_headers(seed_data["doctor_user"].username)
        created = await async_client.post("/api/diagnosisTemplate/create", headers=headers, json={"code": "i10", "name": "原发性高血压"})
        assert created.status_code == 200
        template_id = created.json()["data"]["template_id"]
        assert created.json()["data"]["code"] == "I10"
        listed = await async_client.get("/api/diagnosisTemplate/list", headers=headers)
        assert any(item["template_id"] == template_id for item in listed.json()["data"])
        applied = await async_client.post("/api/diagnosisTemplate/apply", headers=headers, json={"template_id": template_id})
        assert applied.json()["data"] == {"code": "I10", "name": "原发性高血压"}
        updated = await async_client.put("/api/diagnosisTemplate/update", headers=headers, json={"template_id": template_id, "code": "J06.9", "name": "急性上呼吸道感染"})
        assert updated.json()["data"]["code"] == "J06.9"
        deleted = await async_client.post("/api/diagnosisTemplate/delete", headers=headers, json={"template_id": template_id})
        assert deleted.json()["code"] == 200

    async def test_diagnosis_template_isolated_between_doctors(self, async_client, seed_data, auth_headers):
        doctor_headers = auth_headers(seed_data["doctor_user"].username)
        created = await async_client.post("/api/diagnosisTemplate/create", headers=doctor_headers, json={"code": "R51", "name": "头痛"})
        template_id = created.json()["data"]["template_id"]
        other = await async_client.post("/api/diagnosisTemplate/apply", headers=auth_headers(seed_data["director_user"].username), json={"template_id": template_id})
        assert other.status_code == 200
        assert other.json()["code"] == 404


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
        doctor_headers = auth_headers(seed_data["doctor_user"].username)
        # 新开一份病历,避免受 seed_data 原有记录的 doctor 归属干扰
        r = await async_client.post("/api/medicalRecord/create", headers=doctor_headers, json={
            "patient_id": seed_data["patient2"].patient_id, "symptom": "测试病历", "result": "初始诊断"
        })
        assert r.json()["code"] == 200
        r = await async_client.get("/api/medicalRecord/getList", headers=doctor_headers)
        mine = [m for m in r.json()["data"] if m.get("symptom") == "测试病历"]
        assert len(mine) >= 1
        my_mr_id = mine[0]["uuid"]
        # 更新自己的 — 成功
        r = await async_client.post("/api/medicalRecord/update", headers=doctor_headers, json={
            "medical_record_id": my_mr_id, "symptom": "头痛发热改", "result": "感冒"
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

    async def test_signed_outpatient_record_cannot_be_updated(self, async_client, seed_data, auth_headers):
        headers = auth_headers(seed_data["doctor_user"].username)
        created = await async_client.post("/api/medicalRecord/create", headers=headers, json={
            "patient_id": seed_data["patient2"].patient_id, "symptom": "签名门诊病历", "result": "初步诊断",
        })
        assert created.json()["code"] == 200
        record_id = created.json()["data"]["medical_record_id"]
        signed = await async_client.post("/api/medicalRecord/sign", headers=headers, json={"medical_record_id": record_id})
        assert signed.json()["code"] == 200
        blocked = await async_client.post("/api/medicalRecord/update", headers=headers, json={
            "medical_record_id": record_id, "symptom": "篡改", "result": "篡改",
        })
        assert blocked.json() == {"code": 403, "msg": "已签名病历不可修改"}
        repeated = await async_client.post("/api/medicalRecord/sign", headers=headers, json={"medical_record_id": record_id})
        assert repeated.json()["code"] == 500
        detail = await async_client.post("/api/medicalRecord/detail", headers=headers, json={"medical_record_id": record_id})
        assert detail.json()["data"]["status_text"] == "已签名"

    async def test_doctor_cannot_view_other_doctor_medical_record(self, async_client, seed_data, auth_headers):
        mr = seed_data["medical_record"]
        r = await async_client.post(
            "/api/medicalRecord/detail",
            headers=auth_headers(seed_data["doctor_user"].username),
            json={"medical_record_id": str(mr.medical_record_id)},
        )
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

    async def test_create_prescription_rejects_invalid_medication_lines(self, async_client, seed_data, auth_headers):
        headers = auth_headers(seed_data["doctor_user"].username)
        base = {"patient": seed_data["patient"].patient_id}
        for phas, message in [
            ([], "处方至少需要一项药品"),
            ([{"id": seed_data["pharmaceutical"].pharmaceutical_id, "number": 0}], "药品数量必须大于0"),
            ([{"id": 999999, "number": 1}], "药品不存在"),
        ]:
            r = await async_client.post(
                "/api/prescriptionManagement/create",
                headers=headers,
                json={**base, "phas": phas},
            )
            assert r.status_code == 200
            assert r.json() == {"code": 500, "msg": message}

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
        repeated = await async_client.post("/api/prescriptionManagement/cancel", headers=doctor_headers, json={"prescription_id": new_pre_id})
        assert repeated.json()["code"] == 500

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
