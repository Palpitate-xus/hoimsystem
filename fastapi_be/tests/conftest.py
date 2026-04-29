import os
import sys
import datetime
import uuid as uuid_module
import pytest
import pytest_asyncio

# Must set before any app imports so BaseSettings picks it up
os.environ["DATABASE_URL"] = "sqlite:///:memory:"

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.database import Base, get_db
from app.models import (
    User, Patient, Doctor, Department, Notice, DoctorSchedule,
    Pharmaceutical, Prescription, PrePha, Charge, MedicalRecord,
    Registration, Appointment, Queue, VitalSign, LabOrder, LabResult,
    Invoice, FollowUp, Review, OperationLog, Dict, Config,
)

engine = create_engine(
    os.environ["DATABASE_URL"],
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db


@pytest.fixture(scope="session", autouse=True)
def setup_database():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def db_session() -> Session:
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest_asyncio.fixture
async def async_client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.fixture
def seed_data(db_session: Session):
    """Create a consistent baseline dataset for tests."""
    sess = db_session

    # Admin user
    admin_user = User(username="admin", password="admin123", user_role="admin")
    sess.add(admin_user)
    sess.flush()

    # Department
    dept = Department(name="内科", phone="01012345678", location="1号楼", director=None)
    sess.add(dept)
    sess.flush()

    # Doctor user + doctor
    doc_user = User(username="doc01", password="123456", user_role="doctor")
    sess.add(doc_user)
    sess.flush()
    doctor = Doctor(
        name="王医生", sex=1, department_id=dept.department_id,
        title="主任医师", education="博士", phone="13900139000",
        permission="doctor", user_id=doc_user.user_id,
    )
    sess.add(doctor)
    sess.flush()
    dept.director = doctor.doctor_id
    sess.add(dept)

    # Doctor schedule
    for week, time in [("星期一", "01"), ("星期一", "02"), ("星期二", "01")]:
        sched = DoctorSchedule(week=week, time=time, number=20, specialist=1, doctor_id=doctor.doctor_id)
        sess.add(sched)
    sess.flush()

    # Patient user + patient
    pat_user = User(username="370101199001011234", password="123456", user_role="patient")
    sess.add(pat_user)
    sess.flush()
    patient = Patient(
        name="张三", sex=1, identity="370101199001011234",
        birthday=datetime.date(1990, 1, 1), phone="13800138000",
        address="北京", permission="allow",
    )
    sess.add(patient)
    sess.flush()

    # Second patient
    pat_user2 = User(username="370101199001015678", password="123456", user_role="patient")
    sess.add(pat_user2)
    sess.flush()
    patient2 = Patient(
        name="李四", sex=0, identity="370101199001015678",
        birthday=datetime.date(1992, 2, 2), phone="13700137000",
        address="上海", permission="allow",
    )
    sess.add(patient2)
    sess.flush()

    # Pharmaceutical
    pha = Pharmaceutical(
        name="阿司匹林", stock=100, price=15.5,
        expireddate=datetime.date(2027, 6, 1),
        purchasing_time=datetime.datetime.now(),
        supplier="华北制药", remark="常用药",
    )
    sess.add(pha)
    sess.flush()

    # Prescription + Charge
    pre = Prescription(
        patient_id=patient.patient_id, doctor_id=doctor.doctor_id,
        status=0, create_time=datetime.datetime.now(),
    )
    sess.add(pre)
    sess.flush()
    pp = PrePha(prescription_id=pre.prescription_id, pharmaceutical_id=pha.pharmaceutical_id, number=2)
    sess.add(pp)
    charge = Charge(
        charge_time=datetime.datetime.now(), time=datetime.datetime(1970, 1, 1),
        prescription_id=pre.prescription_id, amount=31.0, status=0,
    )
    sess.add(charge)
    sess.flush()

    # Medical record
    mr = MedicalRecord(
        consultation_time=datetime.datetime.now(),
        doctor_id=doctor.doctor_id, patient_id=patient.patient_id,
        symptom="头痛发热", result="上呼吸道感染",
    )
    sess.add(mr)

    # Notice
    notice = Notice(
        title="系统通知", content="系统维护通知", isemergency=0,
        towho="['医生', '病人']", sendtime=datetime.datetime.now(),
        expiredtime=datetime.datetime(2026, 12, 31), readnum=0, writer_id=admin_user.user_id,
    )
    sess.add(notice)

    sess.commit()

    data = {
        "admin_user": admin_user,
        "doctor_user": doc_user,
        "doctor": doctor,
        "patient_user": pat_user,
        "patient": patient,
        "patient2_user": pat_user2,
        "patient2": patient2,
        "department": dept,
        "pharmaceutical": pha,
        "prescription": pre,
        "charge": charge,
        "medical_record": mr,
        "notice": notice,
    }
    return data
