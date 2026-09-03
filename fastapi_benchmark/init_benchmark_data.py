"""初始化基准测试数据。"""

import datetime
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = (PROJECT_ROOT / "fastapi_be").resolve()
BENCHMARK_DB = BACKEND_DIR / "benchmark.db"
BENCHMARK_DATABASE_URL = f"sqlite:///{BENCHMARK_DB.as_posix()}"

# This script deletes every table before seeding. Never inherit an ambient URL:
# it may point at a development or production database.
os.environ["DATABASE_URL"] = BENCHMARK_DATABASE_URL
sys.path.insert(0, str(BACKEND_DIR))

from app.database import Base, SessionLocal, engine
from app.models import Department, Doctor, DoctorSchedule, Patient, Pharmaceutical, User
from app.security import hash_password


def _assert_benchmark_engine(candidate_engine=engine):
    """Refuse destructive initialization unless the pinned benchmark DB is active."""
    database = candidate_engine.url.database
    if candidate_engine.url.get_backend_name() != "sqlite" or not database:
        raise RuntimeError("Benchmark initialization requires the pinned SQLite database")
    if BENCHMARK_DB.is_symlink():
        raise RuntimeError(f"Refusing to initialize symlinked benchmark database: {BENCHMARK_DB}")
    if not Path(database).is_absolute() or Path(database) != BENCHMARK_DB:
        raise RuntimeError(f"Refusing to initialize non-benchmark database: {candidate_engine.url}")


def init():
    _assert_benchmark_engine()
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        # 清空旧数据(避免重复)
        for table in reversed(Base.metadata.sorted_tables):
            db.execute(table.delete())

        # 部门
        depts = [
            Department(name="内科", phone="01012345678", location="1号楼", director=None),
            Department(name="外科", phone="01012345679", location="2号楼", director=None),
            Department(name="儿科", phone="01012345680", location="3号楼", director=None),
        ]
        db.add_all(depts)
        db.flush()

        # 用户
        users = [
            User(username="admin", password=hash_password("admin123"), user_role="admin"),
            User(username="doc01", password=hash_password("123456"), user_role="doctor"),
            User(username="doc02", password=hash_password("123456"), user_role="doctor"),
            User(username="nurse01", password=hash_password("123456"), user_role="nurse"),
            User(username="cashier01", password=hash_password("123456"), user_role="cashier"),
            User(username="pharmacist01", password=hash_password("123456"), user_role="pharmacist"),
            User(username="370101199001011234", password=hash_password("123456"), user_role="patient"),
        ]
        db.add_all(users)
        db.flush()

        # 医生
        doctors = [
            Doctor(name="王医生", sex=1, department_id=depts[0].department_id, title="主任医师", education="博士", phone="13900139001", permission="doctor", user_id=users[1].user_id),
            Doctor(name="李医生", sex=1, department_id=depts[1].department_id, title="副主任医师", education="硕士", phone="13900139002", permission="doctor", user_id=users[2].user_id),
        ]
        db.add_all(doctors)
        db.flush()

        # 排班
        schedules = []
        for doc in doctors:
            for week in ["星期一", "星期二", "星期三"]:
                for time_slot in ["01", "02"]:
                    schedules.append(
                        DoctorSchedule(
                            week=week,
                            time=time_slot,
                            number=50,
                            specialist=1,
                            doctor_id=doc.doctor_id,
                        )
                    )
        db.add_all(schedules)
        db.flush()

        # 患者
        patient = Patient(
            name="张三",
            sex=1,
            identity="370101199001011234",
            birthday=datetime.date(1990, 1, 1),
            phone="13800138000",
            address="北京",
            permission="allow",
        )
        db.add(patient)
        db.flush()

        # 药品
        phas = [
            Pharmaceutical(name="阿司匹林", stock=1000, price=15.5, expireddate=datetime.date(2027, 6, 1), purchasing_time=datetime.datetime.now(), supplier="华北制药", remark="常用药"),
            Pharmaceutical(name="布洛芬", stock=800, price=22.0, expireddate=datetime.date(2027, 8, 1), purchasing_time=datetime.datetime.now(), supplier="新华制药", remark="止痛药"),
        ]
        db.add_all(phas)
        db.flush()

        db.commit()
        print(f"Initialized: {len(depts)} departments, {len(doctors)} doctors, {len(schedules)} schedules, {len(phas)} pharmaceuticals")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    init()
