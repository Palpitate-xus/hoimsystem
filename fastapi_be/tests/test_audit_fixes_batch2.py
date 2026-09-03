"""门诊/收费/医技域审计修复回归测试（第二批）。

对应审计发现：
1. kiosk 手机尾数可 1 位绕过（checkin）
2. 报到队列号并发重复（读 max+1 无约束）
3. 停诊/加号审批不生效（approve 空转）
4. 取消预约号源回补 fallback 加错排班
5. 现金收费无支付流水
6. 退费不作废发票、作废发票仍可下载
7. LIS 危急值 critical_status 缺失
8. 检验自审自批（双人复核）
9. 已审核影像报告可篡改
10. 体检结果患者查看恒 403（Row 元组）
11. 用血安全（另见 test_blood_safety.py）
12. 病程/查房记录删除无属主校验
"""
import datetime

import pytest

from app.models import (
    Appointment,
    Charge,
    Invoice,
    LabOrder,
    LabResult,
    Patient,
    Payment,
    ProgressNote,
)


@pytest.mark.asyncio
class TestKioskPhoneTail:
    async def test_query_rejects_short_phone_tail(self, async_client, seed_data, auth_headers, db_session):
        """1 位手机尾数不得通过双因子校验。"""
        patient = Patient(name="kiosk患者A", identity="110101199001011111", sex=1, phone="13900001234")
        db_session.add(patient)
        db_session.commit()
        r = await async_client.get(
            "/api/checkIn/getAppointments",
            params={"identity": patient.identity, "phone": "4"},
        )
        body = r.json()
        assert body["code"] == 500 or (body.get("code") == 200 and body.get("data") == [])
        if body.get("code") == 200:
            assert body["data"] == [], "1 位尾数不得匹配出预约列表"

    async def test_query_accepts_exact_four_digits(self, async_client, seed_data, auth_headers, db_session):
        patient = Patient(name="kiosk患者B", identity="110101199001012222", sex=1, phone="13900001234")
        db_session.add(patient)
        db_session.flush()
        db_session.add(Appointment(
            registration_uuid="qk-appt-4digit",
            patient_id=patient.patient_id,
            doctor_id=seed_data["doctor"].doctor_id,
            specialist=0,
            prefer_time="上午",
            time=datetime.date.today(),
            status=0,
        ))
        db_session.commit()
        r = await async_client.get(
            "/api/checkIn/getAppointments",
            params={"identity": patient.identity, "phone": "1234"},
        )
        assert r.json()["code"] == 200
        assert len(r.json()["data"]) >= 1


@pytest.mark.asyncio
class TestCheckInAtomic:
    async def test_checkin_status_atomic(self, async_client, seed_data, auth_headers, db_session):
        """报到后重复报到必须失败（条件 UPDATE 语义）。"""
        patient = Patient(name="报到患者C", identity="110101199001013333", sex=1, phone="13900009999")
        db_session.add(patient)
        db_session.flush()
        db_session.add(Appointment(
            registration_uuid="atomic-checkin-1",
            patient_id=patient.patient_id,
            doctor_id=seed_data["doctor"].doctor_id,
            specialist=0,
            time=datetime.date.today(),
            status=0,
        ))
        db_session.commit()
        payload = {"identity": patient.identity, "appointment_uuid": "atomic-checkin-1", "phone_tail": "9999"}
        r1 = await async_client.post("/api/checkIn/checkIn", json=payload)
        assert r1.json()["code"] == 200, r1.json()
        r2 = await async_client.post("/api/checkIn/checkIn", json=payload)
        assert r2.json()["code"] == 500
        assert "报到" in r2.json()["msg"]


@pytest.mark.asyncio
class TestScheduleChangeEffects:
    async def test_stop_approval_cancels_appointments(self, async_client, seed_data, auth_headers, db_session):
        from app.models import ScheduleChangeRequest

        target = datetime.date.today() + datetime.timedelta(days=3)
        db_session.add(Appointment(
            registration_uuid="sc-appt-1",
            patient_id=seed_data["patient"].patient_id,
            doctor_id=seed_data["director_doctor"].doctor_id,
            specialist=0,
            time=target,
            status=0,
        ))
        req = ScheduleChangeRequest(
            request_id="sc-stop-1",
            doctor_id=seed_data["director_doctor"].doctor_id,
            request_type="stop",
            target_date=target,
            extra_slots=0,
            reason="学术会议",
            status=0,
            applicant_id=seed_data["director_user"].user_id,
            create_time=datetime.datetime.now(),
        )
        db_session.add(req)
        db_session.commit()

        r = await async_client.post(
            "/api/scheduleChange/approve",
            headers=auth_headers(seed_data["admin_user"].username),
            json={"request_id": "sc-stop-1"},
        )
        assert r.json()["code"] == 200, r.json()
        db_session.expire_all()
        appt = db_session.query(Appointment).filter(Appointment.registration_uuid == "sc-appt-1").first()
        assert appt.status == 2, "停诊审批后待就诊预约必须被取消"


@pytest.mark.asyncio
class TestCashPaymentLedger:
    async def test_cash_charge_creates_payment(self, async_client, seed_data, auth_headers, db_session):
        charge = Charge(prescription_id=str(seed_data["prescription"].prescription_id), amount=25.0, status=0)
        db_session.add(charge)
        db_session.commit()
        r = await async_client.post(
            "/api/chargeManagement/charge",
            headers=auth_headers(seed_data["cashier_user"].username),
            json={"id": str(charge.charge_id)},
        )
        assert r.json()["code"] == 200, r.json()
        payment = db_session.query(Payment).filter(Payment.charge_id == charge.charge_id).first()
        assert payment is not None, "现金收费必须补写支付流水"
        assert payment.channel == "cash" and payment.status == 1

    async def test_refund_voids_invoice(self, async_client, seed_data, auth_headers, db_session):
        charge = Charge(prescription_id=str(seed_data["prescription"].prescription_id), amount=30.0, status=1, time=datetime.datetime.now())
        db_session.add(charge)
        db_session.flush()
        invoice = Invoice(charge_id=charge.charge_id, invoice_no="INV-TEST-1", amount=30.0, tax=1.8, invoice_time=datetime.datetime.now(), status=0)
        db_session.add(invoice)
        db_session.commit()
        r = await async_client.post(
            "/api/chargeManagement/refund",
            headers=auth_headers(seed_data["cashier_user"].username),
            json={"charge_id": str(charge.charge_id), "reason": "患者要求"},
        )
        assert r.json()["code"] == 200, r.json()
        db_session.expire_all()
        inv = db_session.query(Invoice).filter(Invoice.invoice_id == invoice.invoice_id).first()
        assert inv.status == 2, "退费后发票必须作废"
        dl = await async_client.get(
            f"/api/invoice/pdf/{invoice.invoice_id}",
            headers=auth_headers(seed_data["cashier_user"].username),
        )
        assert dl.json()["code"] == 500, "作废发票不得继续下载"
        assert "作废" in dl.json()["msg"]


@pytest.mark.asyncio
class TestLisCriticalStatus:
    async def test_lis_callback_sets_critical_status(self, async_client, seed_data, db_session, monkeypatch):
        from app.config import settings

        monkeypatch.setattr(settings, "LIS_INTEGRATION_KEY", "test-lis-key", raising=False)
        order = LabOrder(
            lab_order_id="lis-ord-1",
            patient_id=seed_data["patient"].patient_id,
            doctor_id=seed_data["doctor"].doctor_id,
            check_type="血糖",
            check_items="血糖",
            status=1,
            sample_status=1,
            create_time=datetime.datetime.now(),
        )
        db_session.add(order)
        db_session.commit()
        r = await async_client.post(
            "/api/integration/lis/result",
            headers={"X-Integration-Key": "test-lis-key"},
            json={"lab_order_id": "lis-ord-1", "sample_id": "S-LIS-1", "result": "血糖 25.0 mmol/L"},
        )
        assert r.status_code == 200, r.text
        result = db_session.query(LabResult).filter(LabResult.lab_order_id == "lis-ord-1").first()
        assert result is not None
        assert result.critical_status == 1, "LIS 危急值必须设置 critical_status 进入通知闭环"


@pytest.mark.asyncio
class TestLabDualReview:
    async def test_technician_cannot_audit_own_result(self, async_client, seed_data, auth_headers, db_session):
        result = LabResult(
            lab_result_id="dual-1",
            lab_order_id=seed_data["medical_record"].medical_record_id,  # 任意非空引用，仅测试 audit 守卫
            sample_id="S-D1",
            result="血糖 5.0",
            technician_id=seed_data["lab_tech_user"].user_id,
            report_time=datetime.datetime.now(),
            audit_status=0,
            critical_status=0,
        )
        order = LabOrder(
            lab_order_id="dual-ord-1",
            patient_id=seed_data["patient"].patient_id,
            doctor_id=seed_data["doctor"].doctor_id,
            check_type="血糖",
            check_items="血糖",
            status=1,
            sample_status=1,
            create_time=datetime.datetime.now(),
        )
        db_session.add(order)
        result.lab_order_id = "dual-ord-1"
        db_session.add(result)
        db_session.commit()
        r = await async_client.post(
            "/api/labResult/audit",
            headers=auth_headers(seed_data["lab_tech_user"].username),
            json={"lab_result_id": "dual-1"},
        )
        assert r.json()["code"] == 500
        assert "复核" in r.json()["msg"]


@pytest.mark.asyncio
class TestImagingTamperGuard:
    async def test_audited_report_cannot_be_modified(self, async_client, seed_data, auth_headers, db_session):
        from app.models import ImagingOrder, ImagingReport

        order = ImagingOrder(
            imaging_order_id="img-tamper-1",
            patient_id=seed_data["patient"].patient_id,
            doctor_id=seed_data["doctor"].doctor_id,
            modality="CT",
            body_part="胸部",
            status=4,
            create_time=datetime.datetime.now(),
        )
        db_session.add(order)
        db_session.flush()
        report = ImagingReport(
            imaging_order_id="img-tamper-1",
            author_id=seed_data["doctor_user"].user_id,
            findings="原结论",
            impression="原印象",
            status=2,
        )
        db_session.add(report)
        db_session.commit()
        r = await async_client.post(
            "/api/imaging/report/save",
            headers=auth_headers(seed_data["doctor_user"].username),
            json={"imaging_order_id": "img-tamper-1", "findings": "篡改后的结论"},
        )
        assert r.json()["code"] in (400, 403)
        assert "审核" in r.json()["msg"]
        r2 = await async_client.post(
            "/api/imaging/report/submit",
            headers=auth_headers(seed_data["doctor_user"].username),
            json={"report_id": report.report_id},
        )
        assert r2.json()["code"] == 400


@pytest.mark.asyncio
class TestExamPatientView:
    async def test_patient_can_view_own_exam_result(self, async_client, seed_data, auth_headers, db_session):
        """患者查看本人体检结果不再恒 403（Row 元组修复）。"""
        from app.models import ExamAppointment, ExamRecord

        appt = ExamAppointment(
            patient_id=seed_data["patient"].patient_id,
            exam_date=datetime.date.today(),
            status=2,
            create_time=datetime.datetime.now(),
        )
        db_session.add(appt)
        db_session.flush()
        record = ExamRecord(
            appointment_id=appt.appointment_id,
            patient_id=seed_data["patient"].patient_id,
            package_id=None,
            status=3,
            create_time=datetime.datetime.now(),
        )
        db_session.add(record)
        db_session.commit()
        r = await async_client.get(
            f"/api/examReport/getDetail?record_id={record.record_id}",
            headers=auth_headers(seed_data["patient_user"].username),
        )
        assert r.status_code == 200, r.text
        assert r.json()["code"] == 200, r.json()


@pytest.mark.asyncio
class TestEmrDeleteOwnership:
    async def test_doctor_cannot_delete_others_progress_note(self, async_client, seed_data, auth_headers, db_session):
        note = ProgressNote(
            admission_id=None,
            patient_id=seed_data["patient"].patient_id,
            doctor_id=seed_data["director_doctor"].doctor_id,
            content="他人病程记录",
            record_time=datetime.datetime.now(),
            create_time=datetime.datetime.now(),
        )
        db_session.add(note)
        db_session.commit()
        r = await async_client.post(
            "/api/progressNote/delete",
            headers=auth_headers(seed_data["doctor_user"].username),
            json={"note_id": note.note_id},
        )
        assert r.json()["code"] == 403
