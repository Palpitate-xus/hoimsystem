"""初始化基准测试数据。"""

import argparse
import datetime
import sys
import uuid

from benchmark_database import (  # noqa: F401
    BACKEND_DIR,
    BENCHMARK_DB,
    configure_application_environment,
    validate_benchmark_url,
)
from benchmark_profiles import (
    MAX_FAMILY_MEMBERS,
    PROFILES,
    patient_identity,
    portal_owner_offsets,
)
from sqlalchemy import insert, select

sys.path.insert(0, str(BACKEND_DIR))

# Validate and pin the target before app.database constructs its engine. An
# ambient DATABASE_URL is deliberately ignored; PostgreSQL must use the
# benchmark-specific variable and explicit reset confirmation.
BENCHMARK_DATABASE_URL = configure_application_environment(destructive=True)

from app.database import Base, SessionLocal, engine  # noqa: E402
from app.models import (  # noqa: E402
    Charge,
    Department,
    Doctor,
    DoctorSchedule,
    FamilyMember,
    MedicalRecord,
    OperationLog,
    Patient,
    Pharmaceutical,
    PrePha,
    Prescription,
    User,
)
from app.security import hash_password  # noqa: E402

BATCH_SIZE = 2_000


def _assert_benchmark_engine(candidate_engine=None):
    """Refuse destructive initialization unless the selected target is valid."""
    candidate_engine = candidate_engine or engine
    validate_benchmark_url(candidate_engine.url.render_as_string(hide_password=False), destructive=True)


def _batched_insert(db, model, rows):
    for start in range(0, len(rows), BATCH_SIZE):
        db.execute(insert(model), rows[start : start + BATCH_SIZE])


def init(profile_name: str = "smoke"):
    if profile_name not in PROFILES:
        raise ValueError(f"unknown benchmark profile: {profile_name}")
    profile = PROFILES[profile_name]
    _assert_benchmark_engine()
    # The benchmark database is disposable. Recreate it so model changes cannot
    # leave an old SQLite schema that create_all() would silently preserve.
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
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
        doctors.extend(
            Doctor(name=f"合成医生{index + 1}", sex=index % 2, department_id=depts[index % len(depts)].department_id,
                   title="主治医师", education="本科", phone=f"139{index:08d}", permission="doctor")
            for index in range(2, profile.doctors)
        )
        db.add_all(doctors)
        db.flush()

        # 排班
        schedules = []
        for doc in doctors:
            for week in ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"][:profile.schedule_days]:
                for time_slot in ["01", "02"]:
                    schedules.append(
                        DoctorSchedule(
                            week=week,
                            time=time_slot,
                            number=profile.patients * 2,
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

        # Portal households stay bounded while unrelated clinical history grows.
        owner_offsets = portal_owner_offsets(profile)
        member_offsets = {
            member
            for owner in owner_offsets
            for member in range(owner + 1, min(owner + MAX_FAMILY_MEMBERS + 1, profile.patients))
        }
        family_rows = [
            {
                "name": f"压测患者{index:06d}",
                "sex": index % 2,
                "identity": patient_identity(index),
                "birthday": datetime.date(2000, 1, 1),
                "phone": f"139{index:08d}",
                "address": "基准测试",
                "permission": "family" if index in member_offsets else "allow",
            }
            for index in range(1, profile.patients)
        ]
        _batched_insert(db, Patient, family_rows)
        now = datetime.datetime.now()
        household_patient_ids = db.scalars(select(Patient.patient_id).order_by(Patient.patient_id)).all()
        _batched_insert(db, FamilyMember, [
            {"owner_patient_id": household_patient_ids[owner], "member_patient_id": household_patient_ids[member], "relation": "其他", "create_time": now, "update_time": now}
            for owner in owner_offsets
            for member in range(owner + 1, min(owner + MAX_FAMILY_MEMBERS + 1, profile.patients))
        ])
        db.add_all([
            User(username=patient_identity(owner), password=users[-1].password, user_role="patient")
            for owner in owner_offsets if owner != 0
        ])
        db.flush()

        # 药品
        benchmark_expiry = datetime.date.today() + datetime.timedelta(days=3650)
        pharmaceutical_rows = [
            {
                "name": f"基准药品{index:05d}",
                "stock": max(profile.history_rows * 2, 10_000),
                "price": 10 + (index % 100) / 10,
                "expireddate": benchmark_expiry,
                "purchasing_time": now,
                "supplier": "基准供应商",
                "remark": "仅用于隔离性能测试",
                "status": 0,
                "barcode": f"BENCH-{index:08d}",
            }
            for index in range(1, profile.pharmaceuticals + 1)
        ]
        _batched_insert(db, Pharmaceutical, pharmaceutical_rows)
        db.flush()

        patient_ids = db.scalars(select(Patient.patient_id).order_by(Patient.patient_id)).all()
        pharmaceutical_ids = db.scalars(
            select(Pharmaceutical.pharmaceutical_id).order_by(Pharmaceutical.pharmaceutical_id)
        ).all()
        prescription_rows = []
        medical_record_rows = []
        pre_pha_rows = []
        charge_rows = []
        for index in range(profile.history_rows):
            patient_id = patient_ids[index % len(patient_ids)]
            prescription_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"hoimsystem-benchmark-prescription-{index}"))
            prescription_rows.append(
                {
                    "prescription_id": prescription_id,
                    "patient_id": patient_id,
                    "doctor_id": doctors[index % len(doctors)].doctor_id,
                    "status": index % 3,
                    "create_time": now - datetime.timedelta(minutes=index % 43_200),
                }
            )
            pre_pha_rows.append(
                {
                    "pre_pha_id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"hoimsystem-benchmark-prepha-{index}")),
                    "prescription_id": prescription_id,
                    "pharmaceutical_id": pharmaceutical_ids[index % len(pharmaceutical_ids)],
                    "number": 1,
                }
            )
            charge_rows.append(
                {
                    "charge_id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"hoimsystem-benchmark-charge-{index}")),
                    "charge_time": now - datetime.timedelta(minutes=index % 43_200),
                    "prescription_id": prescription_id,
                    "charge_type": "prescription",
                    "amount": 10 + (index % 100) / 10,
                    "status": index % 3,
                }
            )
            medical_record_rows.append(
                {
                    "medical_record_id": str(
                        uuid.uuid5(uuid.NAMESPACE_URL, f"hoimsystem-benchmark-medical-record-{index}")
                    ),
                    "consultation_time": now - datetime.timedelta(minutes=index % 43_200),
                    "doctor_id": doctors[index % len(doctors)].doctor_id,
                    "patient_id": patient_id,
                    "symptom": "基准测试症状",
                    "result": "基准测试诊断",
                    "status": 1,
                    "sign_time": now,
                }
            )
        _batched_insert(db, Prescription, prescription_rows)
        _batched_insert(db, PrePha, pre_pha_rows)
        _batched_insert(db, Charge, charge_rows)
        _batched_insert(db, MedicalRecord, medical_record_rows)

        for start in range(0, profile.audit_logs, BATCH_SIZE):
            _batched_insert(db, OperationLog, [
                {"user_id": users[index % len(users)].user_id, "username": users[index % len(users)].username,
                 "role": users[index % len(users)].user_role, "action": ("查询", "新增", "更新", "导出")[index % 4],
                 "target": "合成压测记录", "result": "失败" if index % 19 == 0 else "成功", "status_code": 400 if index % 19 == 0 else 200,
                 "create_time": now - datetime.timedelta(hours=index % 168), "method": "GET", "path": "/synthetic-benchmark"}
                for index in range(start, min(start + BATCH_SIZE, profile.audit_logs))
            ])

        db.commit()
        print(
            f"Initialized profile={profile_name}: {len(depts)} departments, "
            f"{len(doctors)} doctors, {len(schedules)} schedules, "
            f"{profile.patients} patients, {profile.pharmaceuticals} pharmaceuticals, "
            f"{profile.history_rows} prescriptions/charges/medical records, {profile.audit_logs} audit logs"
        )
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=tuple(PROFILES), default="smoke")
    args = parser.parse_args()
    init(args.profile)
