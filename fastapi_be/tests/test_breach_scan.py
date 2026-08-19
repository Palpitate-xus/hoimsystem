"""违约扫描定时任务回归测试。

对应设计限制 #3 落地：爽约（预约日已过仍未报到、未取消）由每日任务
记违约并回补号源，激活"30 天 3 次暂停预约"机制。
"""
import datetime

import pytest

from app.models import Appointment, BreachRecord, DoctorSchedule
from app.scheduler import run_job


@pytest.mark.asyncio
class TestBreachScan:
    def test_breach_scan_records_and_releases(self, seed_data, db_session):
        import app.database as _db
        from tests.conftest import TestingSessionLocal

        schedule = DoctorSchedule(week="星期一", time="01", number=5, specialist=0, doctor_id=seed_data["doctor"].doctor_id)
        db_session.add(schedule)
        db_session.flush()
        # 昨日爽约预约（status=0 未报到）
        db_session.add(Appointment(
            registration_uuid="breach-appt-1",
            schedule_id=schedule.schedule_id,
            patient_id=seed_data["patient"].patient_id,
            doctor_id=seed_data["doctor"].doctor_id,
            specialist=0,
            time=datetime.date.today() - datetime.timedelta(days=1),
            status=0,
        ))
        # 今日正常预约（不动）
        db_session.add(Appointment(
            registration_uuid="breach-appt-2",
            schedule_id=schedule.schedule_id,
            patient_id=seed_data["patient"].patient_id,
            doctor_id=seed_data["doctor"].doctor_id,
            specialist=0,
            time=datetime.date.today(),
            status=0,
        ))
        db_session.commit()

        # 调度器用 SessionLocal —— 测试环境替换
        original = _db.SessionLocal
        _db.SessionLocal = TestingSessionLocal
        try:
            result = run_job("breach_scan")
        finally:
            _db.SessionLocal = original

        assert result["breaches_recorded"] == 1
        assert result["slots_released"] == 1

        db_session.expire_all()
        stale = db_session.query(Appointment).filter(Appointment.registration_uuid == "breach-appt-1").first()
        today_appt = db_session.query(Appointment).filter(Appointment.registration_uuid == "breach-appt-2").first()
        assert stale.status == 2, "爽约预约应被置为取消"
        assert today_appt.status == 0, "未到期预约不受影响"
        assert db_session.query(BreachRecord).filter(BreachRecord.registration_id == "breach-appt-1").count() == 1
        db_session.refresh(schedule)
        assert schedule.number == 6, "号源应回补"

    def test_breach_scan_idempotent(self, seed_data, db_session):
        import app.database as _db
        from tests.conftest import TestingSessionLocal

        db_session.add(Appointment(
            registration_uuid="breach-appt-dup",
            patient_id=seed_data["patient"].patient_id,
            doctor_id=seed_data["doctor"].doctor_id,
            specialist=0,
            time=datetime.date.today() - datetime.timedelta(days=2),
            status=0,
        ))
        db_session.commit()
        original = _db.SessionLocal
        _db.SessionLocal = TestingSessionLocal
        try:
            r1 = run_job("breach_scan")
            r2 = run_job("breach_scan")
        finally:
            _db.SessionLocal = original
        assert r1["breaches_recorded"] == 1
        assert r2["breaches_recorded"] == 0, "重复扫描不得重复记违约"
