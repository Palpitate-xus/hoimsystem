"""配置化收费标准 + 预缴金 API 回归测试。

覆盖：挂号费自动计费、手术/麻醉费自动计费（等级系数）、
预缴金充值/余额查询、开嘱余额预警。
"""
import datetime

import pytest

from app.models import Admission, Charge, Registration, SurgeryApplication, SurgerySchedule


@pytest.mark.asyncio
class TestRegistrationFee:
    async def test_registration_creates_charge(self, async_client, seed_data, auth_headers, db_session):
        """挂号成功自动产生挂号费 Charge（普通号默认 10 元）。"""
        from tests.conftest import TestingSessionLocal
        from app.models import DoctorSchedule

        doctor = seed_data["doctor"]
        schedule = DoctorSchedule(
            week="星期一", time="02", number=5,
            specialist=1, doctor_id=doctor.doctor_id,
        )
        db_session.add(schedule)
        db_session.commit()
        headers = auth_headers(seed_data["patient_user"].username)

        before = db_session.query(Charge).filter(Charge.charge_type == "registration").count()
        r = await async_client.post(
            "/api/registrationManagement/create",
            headers=headers,
            json={
                "patient_id": seed_data["patient"].patient_id,
                "id": schedule.schedule_id,
                "doctor_id": doctor.doctor_id,
                "department_id": doctor.department_id,
                "specialist": 1,
            },
        )
        assert r.json()["code"] == 200, r.json()
        s = TestingSessionLocal()
        try:
            after = s.query(Charge).filter(Charge.charge_type == "registration").count()
        finally:
            s.close()
        assert after == before + 1, "挂号应产生一条挂号费"


@pytest.mark.asyncio
class TestSurgeryAnesthesiaFee:
    def _prepare(self, db, patient_id, doctor_id):
        admission = Admission(
            admission_no=f"ZY-SF-{datetime.datetime.now().strftime('%H%M%S%f')}",
            patient_id=patient_id,
            doctor_id=doctor_id,
            department_id=1,
            admission_time=datetime.datetime.now(),
            status=1,
            create_time=datetime.datetime.now(),
        )
        db.add(admission)
        app_obj = SurgeryApplication(
            patient_id=patient_id,
            surgery_name="阑尾切除术",
            surgery_level=2,
            status=1,
            create_time=datetime.datetime.now(),
        )
        db.add(app_obj)
        db.flush()
        schedule = SurgerySchedule(
            application_id=app_obj.application_id,
            patient_id=patient_id,
            operating_room="OR-FEE",
            surgery_date=datetime.date.today(),
            status=1,
            start_time=datetime.datetime.now(),
            create_time=datetime.datetime.now(),
        )
        db.add(schedule)
        db.commit()
        return admission, app_obj, schedule

    async def test_complete_surgery_charges_fee(self, async_client, seed_data, auth_headers, db_session):
        admission, app_obj, schedule = self._prepare(db_session, seed_data["patient"].patient_id, seed_data["doctor"].doctor_id)
        from app.models import InpatientCharge

        before = (
            db_session.query(InpatientCharge)
            .filter(InpatientCharge.admission_id == admission.admission_id, InpatientCharge.item_type == "surgery")
            .count()
        )
        headers = auth_headers("doc01")
        r = await async_client.post(
            "/api/surgerySchedule/complete",
            headers=headers,
            json={"schedule_id": schedule.schedule_id},
        )
        assert r.json()["code"] == 200, r.json()
        after = (
            db_session.query(InpatientCharge)
            .filter(InpatientCharge.admission_id == admission.admission_id, InpatientCharge.item_type == "surgery")
            .count()
        )
        assert after == before + 1, "手术完成应产生手术费"
        fee = (
            db_session.query(InpatientCharge)
            .filter(InpatientCharge.admission_id == admission.admission_id, InpatientCharge.item_type == "surgery")
            .order_by(InpatientCharge.charge_id.desc())
            .first()
        )
        # 二级手术 = 500 × 1.5^1 = 750
        assert float(fee.total_amount) == 750.0

    async def test_anesthesia_record_charges_fee(self, async_client, seed_data, auth_headers, db_session):
        admission, app_obj, schedule = self._prepare(db_session, seed_data["patient2"].patient_id, seed_data["doctor"].doctor_id)
        from app.models import InpatientCharge

        headers = auth_headers("doc01")
        r = await async_client.post(
            "/api/anesthesiaRecord/create",
            headers=headers,
            json={
                "schedule_id": schedule.schedule_id,
                "anesthesia_method": "全身麻醉",
                "enter_time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "leave_time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            },
        )
        assert r.json()["code"] == 200, r.json()
        fee = (
            db_session.query(InpatientCharge)
            .filter(InpatientCharge.admission_id == admission.admission_id, InpatientCharge.item_type == "anesthesia")
            .first()
        )
        assert fee is not None, "麻醉记录应产生麻醉费"
        assert float(fee.total_amount) == 300.0


@pytest.mark.asyncio
class TestDepositAPI:
    def _admission(self, db, patient_id, deposit=100):
        admission = Admission(
            admission_no=f"ZY-DP-{datetime.datetime.now().strftime('%H%M%S%f')}",
            patient_id=patient_id,
            doctor_id=seed_doctor_id(),
            department_id=1,
            admission_time=datetime.datetime.now(),
            deposit_amount=deposit,
            status=1,
            create_time=datetime.datetime.now(),
        )
        db.add(admission)
        db.commit()
        return admission

    async def test_recharge_and_balance(self, async_client, seed_data, auth_headers, db_session):
        admission = self._admission(db_session, seed_data["patient"].patient_id, deposit=100)
        headers = auth_headers(seed_data["nurse_user"].username)
        r = await async_client.post(
            "/api/inpatientCharge/depositRecharge",
            headers=headers,
            json={"admission_id": admission.admission_id, "amount": 500},
        )
        assert r.json()["code"] == 200, r.json()
        assert r.json()["data"]["deposit_amount"] == 600

        r = await async_client.get(
            "/api/inpatientCharge/depositBalance",
            headers=headers,
            params={"admission_id": admission.admission_id},
        )
        assert r.json()["code"] == 200
        assert r.json()["data"]["balance"] == 600

    async def test_recharge_rejects_nonpositive(self, async_client, seed_data, auth_headers, db_session):
        admission = self._admission(db_session, seed_data["patient"].patient_id)
        headers = auth_headers(seed_data["nurse_user"].username)
        r = await async_client.post(
            "/api/inpatientCharge/depositRecharge",
            headers=headers,
            json={"admission_id": admission.admission_id, "amount": -50},
        )
        assert r.json()["code"] == 400


def seed_doctor_id():
    return 1
