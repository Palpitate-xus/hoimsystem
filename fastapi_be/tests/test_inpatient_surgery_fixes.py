"""住院/手术域业务逻辑审计修复回归测试。

对应审计发现（均实测复现或代码证实）：
1. 入院床位费 admission_id 为 NULL（未 flush 先读主键）→ 孤儿费用、账单漏计
2. 出院只停 0/1 状态医嘱，执行中(2)医嘱出院后仍可被执行 → 医疗安全
3. 出院未取消待执行计划 → 护士执行清单残留脏数据
4. 长期医嘱执行计划按明细条数倍增 → 双倍待执行项
5. 手术申请/排台/麻醉记录把 ISO 字符串直接写 Date/DateTime 列 → 500
6. 手术状态机无前置校验：可取消已完成手术、可完成已取消排台
7. 审批人=申请人（自审自批）
8. 住院医嘱开药无过敏拦截
"""
import datetime

import pytest

from app.models import (
    Admission,
    AnesthesiaRecord,
    Bed,
    InpatientCharge,
    InpatientOrder,
    OrderExecution,
    SurgeryApplication,
    SurgerySchedule,
    Ward,
)


def _make_admission(db, patient_id, doctor_id, department_id, status=1):
    admission = Admission(
        admission_no=f"ZY-RG-{datetime.datetime.now().strftime('%H%M%S%f')}",
        patient_id=patient_id,
        doctor_id=doctor_id,
        department_id=department_id,
        admission_time=datetime.datetime.now(),
        status=status,
        create_time=datetime.datetime.now(),
    )
    db.add(admission)
    db.commit()
    return admission


@pytest.mark.asyncio
class TestAdmissionBedCharge:
    async def test_bed_charge_has_admission_id(self, async_client, seed_data, auth_headers, db_session):
        """入院后床位费必须挂到本次入院（admission_id 非空）。"""
        ward = Ward(name="床位费测试病区", status=0)
        db_session.add(ward)
        db_session.flush()
        bed = Bed(ward_id=ward.ward_id, bed_no="BC01", bed_type="普通", price_per_day=100, status=0)
        db_session.add(bed)
        db_session.commit()

        headers = auth_headers(seed_data["nurse_user"].username)
        r = await async_client.post(
            "/api/admission/create",
            headers=headers,
            json={
                "patient_id": seed_data["patient"].patient_id,
                "doctor_id": seed_data["doctor"].doctor_id,
                "department_id": seed_data["department"].department_id,
                "ward_id": ward.ward_id,
                "bed_id": bed.bed_id,
                "admission_type": 0,
                "admission_diagnosis": "测试诊断",
                "chief_complaint": "测试主诉",
                "deposit_amount": 500,
            },
        )
        assert r.json()["code"] == 200, r.json()
        admission_id = r.json()["data"]["admission_id"]
        charge = (
            db_session.query(InpatientCharge)
            .filter(InpatientCharge.item_type == "bed", InpatientCharge.admission_id == admission_id)
            .first()
        )
        assert charge is not None, "床位费未挂到本次入院（admission_id 为空的孤儿记录即本缺陷）"
        assert float(charge.total_amount) == 100


@pytest.mark.asyncio
class TestDischargeStopsExecutingOrders:
    async def test_discharge_stops_status2_orders_and_cancels_executions(self, async_client, seed_data, auth_headers, db_session):
        """出院必须停止执行中(2)医嘱并取消待执行计划。"""
        admission = _make_admission(
            db_session,
            seed_data["patient"].patient_id,
            seed_data["doctor"].doctor_id,
            seed_data["department"].department_id,
        )
        order = InpatientOrder(
            admission_id=admission.admission_id,
            patient_id=seed_data["patient"].patient_id,
            doctor_id=seed_data["doctor"].doctor_id,
            order_type=0,
            status=2,  # 执行中
            start_time=datetime.datetime.now(),
            create_time=datetime.datetime.now(),
        )
        db_session.add(order)
        db_session.flush()
        db_session.add(OrderExecution(order_id=order.order_id, planned_time=datetime.datetime.now() + datetime.timedelta(hours=1), status=0))
        db_session.commit()

        headers = auth_headers(seed_data["nurse_user"].username)
        r = await async_client.post(
            "/api/discharge/doDischarge",
            headers=headers,
            json={"admission_id": admission.admission_id, "discharge_diagnosis": "痊愈"},
        )
        assert r.json()["code"] == 200, r.json()

        db_session.expire_all()
        db_session.refresh(order)
        assert order.status == 3, "执行中的医嘱在出院后必须被停止"
        execution = db_session.query(OrderExecution).filter(OrderExecution.order_id == order.order_id).first()
        assert execution.status == 3, "待执行计划在出院后必须被取消"


@pytest.mark.asyncio
class TestSurgeryDateParsing:
    async def test_surgery_application_accepts_iso_date_string(self, async_client, seed_data, auth_headers, db_session):
        """ISO 日期字符串必须被解析而非直接绑定 Date 列（原缺陷：500）。"""
        admission = _make_admission(
            db_session,
            seed_data["patient"].patient_id,
            seed_data["doctor"].doctor_id,
            seed_data["department"].department_id,
        )
        headers = auth_headers(seed_data["doctor"].user.username if seed_data["doctor"].user else "doc01")
        r = await async_client.post(
            "/api/surgeryApplication/create",
            headers=headers,
            json={
                "admission_id": admission.admission_id,
                "patient_id": seed_data["patient"].patient_id,
                "doctor_id": seed_data["doctor"].doctor_id,
                "surgery_name": "阑尾切除术",
                "surgery_level": 2,
                "scheduled_date": "2026-09-01",
                "preop_diagnosis": "急性阑尾炎",
            },
        )
        assert r.status_code == 200, r.text
        assert r.json()["code"] == 200, r.json()
        app_obj = db_session.query(SurgeryApplication).filter(SurgeryApplication.application_id == r.json()["data"]["application_id"]).first()
        assert app_obj.scheduled_date == datetime.date(2026, 9, 1)

    async def test_surgery_application_rejects_bad_date(self, async_client, seed_data, auth_headers, db_session):
        admission = _make_admission(
            db_session,
            seed_data["patient"].patient_id,
            seed_data["doctor"].doctor_id,
            seed_data["department"].department_id,
        )
        headers = auth_headers("doc01")
        r = await async_client.post(
            "/api/surgeryApplication/create",
            headers=headers,
            json={
                "admission_id": admission.admission_id,
                "patient_id": seed_data["patient"].patient_id,
                "surgery_name": "测试",
                "scheduled_date": "not-a-date",
            },
        )
        assert r.json()["code"] == 500
        assert "格式错误" in r.json()["msg"]

    async def test_anesthesia_record_accepts_datetime_string(self, async_client, seed_data, auth_headers, db_session):
        admission = _make_admission(
            db_session,
            seed_data["patient"].patient_id,
            seed_data["doctor"].doctor_id,
            seed_data["department"].department_id,
        )
        application = SurgeryApplication(
            admission_id=admission.admission_id,
            patient_id=seed_data["patient"].patient_id,
            surgery_name="测试手术",
            status=1,
            create_time=datetime.datetime.now(),
        )
        db_session.add(application)
        db_session.flush()
        schedule = SurgerySchedule(
            application_id=application.application_id,
            patient_id=seed_data["patient"].patient_id,
            operating_room="OR-1",
            surgery_date=datetime.date.today(),
            status=1,
            create_time=datetime.datetime.now(),
        )
        db_session.add(schedule)
        db_session.commit()

        headers = auth_headers("doc01")
        r = await async_client.post(
            "/api/anesthesiaRecord/create",
            headers=headers,
            json={
                "schedule_id": schedule.schedule_id,
                "enter_time": "2026-09-01 08:30:00",
                "leave_time": "2026-09-01 11:00:00",
                "anesthesia_method": "全身麻醉",
                "blood_loss": 50,
            },
        )
        assert r.json()["code"] == 200, r.json()
        record = db_session.query(AnesthesiaRecord).filter(AnesthesiaRecord.schedule_id == schedule.schedule_id).first()
        assert record.enter_time == datetime.datetime(2026, 9, 1, 8, 30, 0)


@pytest.mark.asyncio
class TestSurgeryStateMachine:
    async def test_cannot_cancel_completed_surgery(self, async_client, seed_data, auth_headers, db_session):
        admission = _make_admission(
            db_session,
            seed_data["patient"].patient_id,
            seed_data["doctor"].doctor_id,
            seed_data["department"].department_id,
        )
        application = SurgeryApplication(
            admission_id=admission.admission_id,
            patient_id=seed_data["patient"].patient_id,
            surgery_name="完成手术",
            status=3,  # 已完成
            create_time=datetime.datetime.now(),
        )
        db_session.add(application)
        db_session.commit()

        headers = auth_headers("doc01")
        r = await async_client.post(
            "/api/surgeryApplication/cancel",
            headers=headers,
            json={"application_id": application.application_id},
        )
        assert r.json()["code"] == 500
        assert "已完成" in r.json()["msg"]

    async def test_cannot_complete_cancelled_schedule(self, async_client, seed_data, auth_headers, db_session):
        admission = _make_admission(
            db_session,
            seed_data["patient"].patient_id,
            seed_data["doctor"].doctor_id,
            seed_data["department"].department_id,
        )
        application = SurgeryApplication(
            admission_id=admission.admission_id,
            patient_id=seed_data["patient"].patient_id,
            surgery_name="取消排台",
            status=2,
            create_time=datetime.datetime.now(),
        )
        db_session.add(application)
        db_session.flush()
        schedule = SurgerySchedule(
            application_id=application.application_id,
            patient_id=seed_data["patient"].patient_id,
            surgery_date=datetime.date.today(),
            status=3,  # 已取消
            create_time=datetime.datetime.now(),
        )
        db_session.add(schedule)
        db_session.commit()

        headers = auth_headers("doc01")
        r = await async_client.post(
            "/api/surgerySchedule/complete",
            headers=headers,
            json={"schedule_id": schedule.schedule_id},
        )
        assert r.json()["code"] == 500

    async def test_approver_cannot_be_applicant(self, async_client, seed_data, auth_headers, db_session):
        """director01 审批自己名下的申请（director_doctor 绑定 director01）应被拒绝。"""
        admission = _make_admission(
            db_session,
            seed_data["patient"].patient_id,
            seed_data["director_doctor"].doctor_id,
            seed_data["department"].department_id,
        )
        application = SurgeryApplication(
            admission_id=admission.admission_id,
            patient_id=seed_data["patient"].patient_id,
            doctor_id=seed_data["director_doctor"].doctor_id,  # 申请人绑定 director01
            surgery_name="自审测试",
            status=0,
            create_time=datetime.datetime.now(),
        )
        db_session.add(application)
        db_session.commit()
        assert application.doctor and application.doctor.user_id is not None, "测试前提：director_doctor 需绑定登录用户"

        headers = auth_headers(seed_data["director_user"].username)  # 同一人审批
        r = await async_client.post(
            "/api/surgeryApplication/approve",
            headers=headers,
            json={"application_id": application.application_id},
        )
        assert r.json()["code"] == 500
        assert "本人" in r.json()["msg"]


@pytest.mark.asyncio
class TestExecutionPlanGeneration:
    async def test_long_order_execution_not_multiplied_by_items(self, async_client, seed_data, auth_headers, db_session):
        """2 个明细 bid×3 天的长期医嘱应生成 3×2=6 条执行（非 12 条）。"""
        admission = _make_admission(
            db_session,
            seed_data["patient"].patient_id,
            seed_data["doctor"].doctor_id,
            seed_data["department"].department_id,
        )
        headers = auth_headers("doc01")
        r = await async_client.post(
            "/api/inpatientOrder/create",
            headers=headers,
            json={
                "admission_id": admission.admission_id,
                "patient_id": seed_data["patient"].patient_id,
                "doctor_id": seed_data["doctor"].doctor_id,
                "order_type": 0,
                "category": "drug",
                "items": [
                    {"item_name": "药A", "item_type": "drug", "quantity": 1, "days": 3, "frequency": "bid", "unit_price": 10},
                    {"item_name": "药B", "item_type": "drug", "quantity": 1, "days": 3, "frequency": "bid", "unit_price": 5},
                ],
            },
        )
        assert r.json()["code"] == 200, r.json()
        order_id = r.json().get("data", {}).get("order_id") if isinstance(r.json().get("data"), dict) else None
        if not order_id:
            orders = db_session.query(InpatientOrder).filter(InpatientOrder.admission_id == admission.admission_id).all()
            order_id = orders[-1].order_id
        count = db_session.query(OrderExecution).filter(OrderExecution.order_id == order_id).count()
        assert count == 6, f"bid×3天×2明细应生成 6 条执行计划，实际 {count}（倍增缺陷）"


@pytest.mark.asyncio
class TestInpatientOrderAllergyGuard:
    async def test_order_rejects_allergen_drug(self, async_client, seed_data, auth_headers, db_session):
        from app.models import Patient, Pharmaceutical

        patient = Patient(
            name="过敏患者",
            identity="110101199001019999",
            sex=1,
            allergy_history="青霉素",
        )
        db_session.add(patient)
        db_session.flush()
        pha = Pharmaceutical(name="青霉素钠注射液", price=10, stock=100, status=0)
        db_session.add(pha)
        db_session.commit()

        admission = _make_admission(db_session, patient.patient_id, seed_data["doctor"].doctor_id, seed_data["department"].department_id, status=1)
        headers = auth_headers("doc01")
        r = await async_client.post(
            "/api/inpatientOrder/create",
            headers=headers,
            json={
                "admission_id": admission.admission_id,
                "patient_id": patient.patient_id,
                "doctor_id": seed_data["doctor"].doctor_id,
                "order_type": 0,
                "category": "drug",
                "items": [
                    {"item_name": "青霉素钠注射液", "item_type": "drug", "item_id_ref": pha.pharmaceutical_id, "quantity": 1, "days": 1, "frequency": "qd", "unit_price": 10},
                ],
            },
        )
        assert r.json()["code"] == 500, r.json()
        assert "过敏" in r.json()["msg"], "住院医嘱开过敏药必须被拦截"
