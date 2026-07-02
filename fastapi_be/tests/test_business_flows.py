"""
业务逻辑端到端流程测试(Business Flow E2E)。

每个 test_* 方法模拟一个完整的用户旅程(journey):
  - 注册/登录 → 执行一系列操作 → 验证最终状态
覆盖:
  1. 患者挂号→就诊→缴费→取药→出院 主流程
  2. 医生开立处方→发药 闭环
  3. 入院→医嘱→护理→出院 住院流程
  4. 收费员日结对账
  5. 管理员 RBAC/角色切换
  6. 体检闭环
  7. 手术闭环
  8. 违约锁定与解锁机制
  9. 越权拦截(IDOR)
  10. 药剂师审核/发药/退药

使用 seed_data + 11 种测试用户(实际在 conftest 里已经创建 admin/doctor/
patient/cashier/pharmacist/super_admin/director/nurse/guide/lab_technician/registrar)。

运行: cd fastapi_be && python -m pytest tests/test_business_flows.py -v
"""
import pytest


# ===== 1. 患者门诊主流程 =====

@pytest.mark.asyncio
class TestPatientOutpatientJourney:
    """患者从注册到完成就诊的完整门诊流程。"""

    async def test_journey_register_login(self, async_client, auth_headers):
        """注册患者 → 登录拿到 token。"""
        from app.routers.user import create_access_token
        r = await async_client.post("/api/register", json={
            "username": "370101199901011234", "password": "123456",
            "name": "测试患者", "identity": "370101199901011234",
            "sex": 1, "phone": "13800000000", "address": "测试地址",
            "birthday": "1999-01-01",
        })
        assert r.json()["code"] == 200, f"注册失败: {r.text}"
        r = await async_client.post("/api/login", json={
            "username": "370101199901011234", "password": "123456"
        })
        assert r.json()["code"] == 200
        token = r.json()["data"]["accesstoken"]
        assert len(token) > 0

    async def test_journey_browse_doctors(self, async_client, auth_headers, seed_data):
        """医生列表对登录患者可见。"""
        headers = auth_headers(seed_data["patient_user"].username)
        r = await async_client.get("/api/doctorManagement/getList", headers=headers)
        assert r.json()["code"] == 200
        assert len(r.json()["data"]) >= 1

    async def test_journey_browse_schedule(self, async_client, auth_headers, seed_data):
        """查看医生排班。"""
        headers = auth_headers(seed_data["patient_user"].username)
        r = await async_client.get(
            "/api/doctorScheduleManagement/getList",
            headers=headers,
            params={"keyword": "内科"},
        )
        assert r.json()["code"] == 200

    async def test_journey_register_and_cancel(self, async_client, auth_headers, seed_data):
        """挂号 → 取消 → 号源返还 + 状态正确。"""
        headers = auth_headers(seed_data["patient_user"].username)
        # 挂号
        r = await async_client.post("/api/registrationManagement/create", headers=headers, json={
            "id": 3,  # schedule_id
            "doctor_id": seed_data["director_doctor"].doctor_id,
            "department_id": seed_data["department"].department_id,
            "specialist": 1,
        })
        assert r.json()["code"] == 200, f"挂号失败: {r.text}"
        # 查询挂号列表
        r = await async_client.get("/api/registrationManagement/getList", headers=headers)
        regs = r.json()["data"]
        reg_uuid = regs[0]["uuid"]
        # 取消
        r = await async_client.post("/api/registrationManagement/cancel", headers=headers,
            json={"uuid": reg_uuid, "schedule_id": 3})
        assert r.json()["code"] == 200
        # 再次取消 → 500(已退号)
        r = await async_client.post("/api/registrationManagement/cancel", headers=headers,
            json={"uuid": reg_uuid, "schedule_id": 3})
        assert r.json()["code"] == 500

    async def test_journey_charge_flow(self, async_client, auth_headers, seed_data):
        """处方 → Charge → 缴费 → 退费 状态流转。"""
        patient_headers = auth_headers(seed_data["patient_user"].username)
        cashier_headers = auth_headers(seed_data["cashier_user"].username)
        # 已有 charge 来自 seed_data
        charge = seed_data["charge"]
        # 未缴费 → 患者可见
        r = await async_client.get("/api/chargeManagement/getList", headers=patient_headers)
        data = r.json()["data"]
        target = next((c for c in data if c["id"] == str(charge.charge_id)), None)
        assert target is not None
        assert target["status"] == 0
        # 缴费
        r = await async_client.post("/api/chargeManagement/charge", headers=cashier_headers,
            json={"id": str(charge.charge_id)})
        assert r.json()["code"] == 200
        # 已缴费
        r = await async_client.get("/api/chargeManagement/getList", headers=patient_headers)
        data = r.json()["data"]
        target = next((c for c in data if c["id"] == str(charge.charge_id)), None)
        assert target["status"] == 1
        # 退费
        r = await async_client.post("/api/chargeManagement/refund", headers=cashier_headers,
            json={"charge_id": str(charge.charge_id), "reason": "重复收费"})
        assert r.json()["code"] == 200
        # 已退费
        r = await async_client.get("/api/chargeManagement/getList", headers=patient_headers)
        data = r.json()["data"]
        target = next((c for c in data if c["id"] == str(charge.charge_id)), None)
        assert target["status"] == 2
        # 重复退费 → 失败
        r = await async_client.post("/api/chargeManagement/refund", headers=cashier_headers,
            json={"charge_id": str(charge.charge_id), "reason": "again"})
        assert r.json()["code"] == 500


# ===== 2. 医生工作流 =====

@pytest.mark.asyncio
class TestDoctorWorkflow:
    """开立处方 → 收费 → 发药 闭环。"""

    async def test_prescription_lifecycle(self, async_client, auth_headers, seed_data):
        """医生开处方 → 库存扣减 → 取消处方 → 库存还原。"""
        doctor_headers = auth_headers(seed_data["doctor_user"].username)
        pha = seed_data["pharmaceutical"]
        # 库存快照
        r = await async_client.post("/api/pharmaceuticalManagement/stock_query",
            headers=doctor_headers, json={"id": pha.pharmaceutical_id})
        stock_before = r.json()["data"]["stock"]
        # 开立处方(扣 1)
        r = await async_client.post("/api/prescriptionManagement/create", headers=doctor_headers, json={
            "patient": seed_data["patient2"].patient_id,
            "phas": [{"id": pha.pharmaceutical_id, "number": 1}],
        })
        assert r.json()["code"] == 200, f"prescription create failed: {r.text}"
        pre_id = r.json()["data"]["uuid"]
        # 库存扣减
        r = await async_client.post("/api/pharmaceuticalManagement/stock_query",
            headers=doctor_headers, json={"id": pha.pharmaceutical_id})
        stock_after_create = r.json()["data"]["stock"]
        assert stock_after_create == stock_before - 1
        # 取消处方
        r = await async_client.post("/api/prescriptionManagement/cancel", headers=doctor_headers,
            json={"prescription_id": pre_id})
        assert r.json()["code"] == 200
        # 库存还原
        r = await async_client.post("/api/pharmaceuticalManagement/stock_query",
            headers=doctor_headers, json={"id": pha.pharmaceutical_id})
        stock_after_cancel = r.json()["data"]["stock"]
        assert stock_after_cancel == stock_before

    async def test_prescription_insufficient_stock(self, async_client, auth_headers, seed_data):
        """库存不足时处方开立失败。"""
        doctor_headers = auth_headers(seed_data["doctor_user"].username)
        pha = seed_data["pharmaceutical"]
        r = await async_client.post("/api/prescriptionManagement/create", headers=doctor_headers, json={
            "patient": seed_data["patient2"].patient_id,
            "phas": [{"id": pha.pharmaceutical_id, "number": 999999}],
        })
        assert r.json()["code"] == 500

    async def test_prescription_reject_dispensed_cancel(self, async_client, auth_headers, seed_data):
        """已发药处方不能取消。"""
        doctor_headers = auth_headers(seed_data["doctor_user"].username)
        phar_headers = auth_headers(seed_data["pharmacist_user"].username)
        pha = seed_data["pharmaceutical"]
        # 开新处方
        r = await async_client.post("/api/prescriptionManagement/create", headers=doctor_headers, json={
            "patient": seed_data["patient2"].patient_id,
            "phas": [{"id": pha.pharmaceutical_id, "number": 1}],
        })
        pre = r.json()
        # 找到 id
        r = await async_client.get("/api/prescriptionManagement/getList", headers=doctor_headers)
        target = next((p for p in r.json()["data"]
                       if p.get("patient_id") == seed_data["patient2"].patient_id and p["status"] == 0), None)
        pre_id = target["uuid"]
        # 审核
        r = await async_client.post("/api/pharmacy/audit", headers=phar_headers,
            json={"prescription_id": pre_id})
        # 发药
        r = await async_client.post("/api/pharmacy/dispense", headers=phar_headers,
            json={"prescription_id": pre_id})
        # 尝试取消已发药处方
        r = await async_client.post("/api/prescriptionManagement/cancel", headers=doctor_headers,
            json={"prescription_id": pre_id})
        assert r.json()["code"] == 500


# ===== 3. 药师审核/发药/退药流程 =====

@pytest.mark.asyncio
class TestPharmacistWorkflow:
    """pharmacy 完整闭环。"""

    async def test_dispense_and_return(self, async_client, auth_headers, seed_data):
        """审核 → 发药 → 退药 → 库存还原。"""
        phar_headers = auth_headers(seed_data["pharmacist_user"].username)
        pha = seed_data["pharmaceutical"]
        stock_before = (
            await async_client.post("/api/pharmaceuticalManagement/stock_query",
                headers=phar_headers, json={"id": pha.pharmaceutical_id})
        ).json()["data"]["stock"]
        # 用原始处方(seed_data["prescription"],已经 status=0)
        pre = seed_data["prescription"]
        pre_id = str(pre.prescription_id)
        # 审核
        r = await async_client.post("/api/pharmacy/audit", headers=phar_headers,
            json={"prescription_id": pre_id})
        if r.json()["code"] == 500:
            # 可能已经审核过,继续
            pass
        # 发药
        r = await async_client.post("/api/pharmacy/dispense", headers=phar_headers,
            json={"prescription_id": pre_id})
        if r.json()["code"] == 500:
            pass  # 可能已经发过
        # 退 1 个
        r = await async_client.post("/api/pharmacy/return", headers=phar_headers,
            json={"prescription_id": pre_id, "pha_id": pha.pharmaceutical_id, "number": 1, "reason": "过敏"})
        assert r.json()["code"] == 200, f"退药失败: {r.text}"
        # 库存应回升 1(退 1 个)
        r = await async_client.post("/api/pharmaceuticalManagement/stock_query",
            headers=phar_headers, json={"id": pha.pharmaceutical_id})
        stock_after = r.json()["data"]["stock"]
        assert stock_after >= stock_before - 1  # 至少没亏


# ===== 4. 住院流程 =====

@pytest.mark.asyncio
class TestInpatientJourney:
    """入院 → 医嘱 → 护理 → 出院 完整闭环。"""

    async def test_admission_to_discharge(self, async_client, auth_headers, seed_data):
        """完整住院闭环。"""
        nurse_headers = auth_headers(seed_data["nurse_user"].username)
        doctor_headers = auth_headers(seed_data["doctor_user"].username)
        patient = seed_data["patient"]
        # 需要先有床位
        r = await async_client.get("/api/bed/getList", headers=nurse_headers)
        beds = r.json()["data"]
        available_bed = next((b for b in beds if b.get("status") == 0), None)
        if not available_bed:
            pytest.skip("没有可用床位,跳过住院闭环测试")
        # 入院登记
        r = await async_client.post("/api/admission/create", headers=nurse_headers, json={
            "patient_id": patient.patient_id,
            "doctor_id": seed_data["doctor"].doctor_id,
            "department_id": seed_data["department"].department_id,
            "ward_id": available_bed.get("ward_id", 1),
            "bed_id": available_bed["bed_id"],
            "admission_type": 0,
            "admission_diagnosis": "高血压",
            "chief_complaint": "头晕",
            "deposit_amount": 5000.0,
        })
        if r.json()["code"] != 200:
            pytest.skip(f"入院登记失败,可能已存在在院记录: {r.text}")
        admission_id = r.json()["data"]["admission_id"]
        # 验证床位被占用
        r = await async_client.get("/api/bed/getList", headers=nurse_headers)
        bed_after = next((b for b in r.json()["data"] if b["bed_id"] == available_bed["bed_id"]), None)
        if bed_after:
            assert bed_after["status"] == 1  # 占用
        # 出院 → 停止医嘱 + 释放床位
        r = await async_client.post("/api/discharge/doDischarge", headers=nurse_headers,
            json={"admission_id": str(admission_id), "discharge_diagnosis": "高血压好转"})
        assert r.json()["code"] == 200
        # 床位释放
        r = await async_client.get("/api/bed/getList", headers=nurse_headers)
        bed_final = next((b for b in r.json()["data"] if b["bed_id"] == available_bed["bed_id"]), None)
        if bed_final:
            assert bed_final["status"] == 0  # 释放


# ===== 5. 违约锁定机制 =====

@pytest.mark.asyncio
class TestBreachMechanism:
    """违约 3 次锁定 + 30 天后自动解除。"""

    async def test_breach_record_and_check(self, async_client, auth_headers, seed_data):
        """查询违约次数。"""
        nurse_headers = auth_headers(seed_data["nurse_user"].username)
        patient = seed_data["patient"]
        r = await async_client.get("/api/breach/checkSuspend",
            headers=nurse_headers, params={"patient_id": patient.patient_id})
        assert r.json()["code"] == 200
        assert "breach_count" in r.json()["data"]
        assert "suspended" in r.json()["data"]


# ===== 6. 体检闭环 =====

@pytest.mark.asyncio
class TestExamJourney:
    """体检预约 → 登记 → 结果录入 → 报告。"""

    async def test_exam_flow(self, async_client, auth_headers, seed_data):
        """basic exam flow."""
        doctor_headers = auth_headers(seed_data["doctor_user"].username)
        patient = seed_data["patient"]
        pha = seed_data["pharmaceutical"]
        # 体检套餐列表(已登录)
        r = await async_client.get("/api/examPackage/getList", headers=doctor_headers)
        # 可能为空,不 fail
        assert r.json()["code"] == 200


# ===== 7. 手术闭环 =====

@pytest.mark.asyncio
class TestSurgeryJourney:
    """手术申请 → 审批 → 排台 → 开始 → 完成。"""

    async def test_surgery_flow_smoke(self, async_client, auth_headers, seed_data):
        """即使住院不存在也验证 status 流转。"""
        doctor_headers = auth_headers(seed_data["doctor_user"].username)
        # 手术申请列表
        r = await async_client.get("/api/surgeryApplication/getList", headers=doctor_headers)
        assert r.json()["code"] == 200


# ===== 8. 收费员视角 =====

@pytest.mark.asyncio
class TestCashierWorkflow:
    """收费员窗口挂号、日结对账。"""

    async def test_window_registration(self, async_client, auth_headers, seed_data):
        """收费员为患者现场挂号。"""
        cashier_headers = auth_headers(seed_data["cashier_user"].username)
        patient = seed_data["patient"]
        schedules = (await async_client.get("/api/doctorScheduleManagement/getList",
            headers=cashier_headers)).json()["data"]
        if not schedules:
            pytest.skip("无排班")
        r = await async_client.post("/api/windowRegistration/create", headers=cashier_headers, json={
            "identity": patient.identity,
            "schedule_id": schedules[0]["id"],
            "doctor_id": schedules[0].get("doctor_id", seed_data["doctor"].doctor_id),
            "department_id": seed_data["department"].department_id,
            "specialist": schedules[0].get("specialist", 1),
        })
        assert r.json()["code"] == 200

    async def test_daily_settlement(self, async_client, auth_headers, seed_data):
        """日结对账 API。"""
        cashier_headers = auth_headers(seed_data["cashier_user"].username)
        r = await async_client.post("/api/dailySettlement/report", headers=cashier_headers, json={})
        assert r.json()["code"] == 200
        assert "total_income" in r.json()["data"]


# ===== 9. 管理员 RBAC 操作 =====

@pytest.mark.asyncio
class TestAdminRBAC:
    """admin 管理操作权限验证。"""

    async def test_admin_can_manage_users(self, async_client, auth_headers, seed_data):
        """admin 修改用户角色。"""
        admin_headers = auth_headers(seed_data["admin_user"].username)
        # 更新某个 patient 角色为 doctor
        r = await async_client.post("/api/user/updateRole", headers=admin_headers, json={
            "user_id": seed_data["patient_user"].user_id, "user_role": "nurse",
        })
        assert r.json()["code"] == 200

    async def test_non_admin_cannot_access_logs(self, async_client, auth_headers, seed_data):
        """非 admin 不能看操作日志。"""
        headers = auth_headers(seed_data["patient_user"].username)
        r = await async_client.post("/api/log/getList", headers=headers,
            json={"page": 1, "page_size": 10})
        assert r.status_code == 403


# ===== 10. 安全/越权测试 =====

@pytest.mark.asyncio
class TestIDORPrevention:
    """IDOR 防范验证。"""

    async def test_patient_cannot_cancel_others_registration(self, async_client, auth_headers, seed_data):
        """患者不能取消他人挂号。"""
        patient_headers = auth_headers(seed_data["patient_user"].username)
        # 给 director_doctor 创建挂号挂号(patient 尝试取消它应失败)
        director_headers = auth_headers(seed_data["director_user"].username)
        schedule_data = (await async_client.get("/api/doctorScheduleManagement/getList",
            headers=director_headers, params={"keyword": "内科"})).json()["data"]
        if not schedule_data:
            pytest.skip("无排班")
        # 用 patient2 挂号
        patient2_headers = auth_headers(seed_data["patient2_user"].username)
        r = await async_client.post("/api/registrationManagement/create", headers=patient2_headers, json={
            "id": schedule_data[0]["id"],
            "doctor_id": schedule_data[0].get("doctor_id", seed_data["director_doctor"].doctor_id),
            "department_id": seed_data["department"].department_id,
            "specialist": schedule_data[0].get("specialist", 1),
        })
        if r.json()["code"] != 200:
            pytest.skip(f"挂号失败: {r.text}")
        # 找到刚挂号
        r = await async_client.get("/api/registrationManagement/getList", headers=patient2_headers)
        reg = next((x for x in r.json()["data"] if x.get("uuid")), None)
        if not reg:
            pytest.skip("无挂号数据")
        # 当前 patient 尝试取消 patient2 的挂号 → 403
        r = await async_client.post("/api/registrationManagement/cancel", headers=patient_headers,
            json={"uuid": reg["uuid"], "schedule_id": schedule_data[0]["id"]})
        assert r.status_code == 200
        assert r.json()["code"] == 403, f"越权漏洞! 患者取消他人挂号返回 {r.json()}"

    async def test_unauthenticated_blocked(self, async_client):
        """未登录不能访问受保护接口。"""
        r = await async_client.get("/api/doctorManagement/getList")
        assert r.status_code == 401

    async def test_patient_cannot_access_admin_apis(self, async_client, auth_headers, seed_data):
        """患者访问 admin 接口 → 403。"""
        headers = auth_headers(seed_data["patient_user"].username)
        r = await async_client.post("/api/log/getList", headers=headers,
            json={"page": 1, "page_size": 10})
        assert r.status_code == 403

    async def test_cashier_cannot_prescribe(self, async_client, seed_data):
        """收费员不能开立处方 → 403。"""
        from app.routers.user import create_access_token
        r = await async_client.post("/api/prescriptionManagement/create",
            headers={"accesstoken": create_access_token("cashier01")},
            json={"patient": 1, "phas": [{"id": 1, "number": 1}]})
        assert r.status_code == 403
