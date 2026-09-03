import datetime
import os
import sys

import pytest
import pytest_asyncio

# Must set before any app imports so BaseSettings picks it up
os.environ["DATABASE_URL"] = "sqlite:///:memory:"

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app import database as _app_database
from app.database import Base, get_db
from app.main import app
from app.models import (
    Charge,
    Department,
    Doctor,
    DoctorSchedule,
    MedicalRecord,
    Notice,
    Patient,
    Pharmaceutical,
    PrePha,
    Prescription,
    User,
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

# 让中间件内的 SessionLocal() 也指向同一个内存数据库
_app_database.SessionLocal = TestingSessionLocal


@pytest.fixture(scope="session", autouse=True)
def setup_database():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="module", autouse=True)
def isolate_module_database():
    """Keep workflow order inside a module while isolating modules from each other."""
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield


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

    from app.security import hash_password

    def baseline_user(username: str, password: str, role: str) -> User:
        user = sess.query(User).filter(User.username == username).one_or_none()
        if user is None:
            user = User(username=username)
            sess.add(user)
        user.password = hash_password(password)
        user.user_role = role
        user.token_invalid_before = None
        sess.flush()
        return user

    def baseline_patient(*, name: str, sex: int, identity: str, birthday, phone: str, address: str) -> Patient:
        patient = sess.query(Patient).filter(Patient.identity == identity).one_or_none()
        if patient is None:
            patient = Patient(identity=identity)
            sess.add(patient)
        patient.name = name
        patient.sex = sex
        patient.birthday = birthday
        patient.phone = phone
        patient.address = address
        patient.permission = "allow"
        patient.prepaid_balance = 0
        sess.flush()
        return patient

    # Admin user
    admin_user = baseline_user("admin", "admin123", "admin")
    cashier_user = baseline_user("cashier01", "123456", "cashier")
    pharmacist_user = baseline_user("pharmacist01", "123456", "pharmacist")
    super_admin_user = baseline_user("super01", "123456", "super_admin")
    director_user = baseline_user("director01", "123456", "director")
    nurse_user = baseline_user("nurse01", "123456", "nurse")
    guide_user = baseline_user("guide01", "123456", "guide")
    lab_tech_user = baseline_user("lab01", "123456", "lab_technician")
    registrar_user = baseline_user("registrar01", "123456", "registrar")

    # Department
    dept = Department(name="内科", phone="01012345678", location="1号楼", director=None)
    sess.add(dept)
    sess.flush()

    director_doctor = Doctor(
        name="李主任", sex=1, department_id=dept.department_id,
        title="科室主任", education="博士", phone="13900139001",
        permission="director", user_id=director_user.user_id,
    )
    sess.add(director_doctor)
    sess.flush()

    # Doctor user + doctor
    doc_user = baseline_user("doc01", "123456", "doctor")
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
    pat_user = baseline_user("370101199001011234", "123456", "patient")
    patient = baseline_patient(
        name="张三", sex=1, identity="370101199001011234",
        birthday=datetime.date(1990, 1, 1), phone="13800138000",
        address="北京",
    )

    # Second patient
    pat_user2 = baseline_user("370101199001015678", "123456", "patient")
    patient2 = baseline_patient(
        name="李四", sex=0, identity="370101199001015678",
        birthday=datetime.date(1992, 2, 2), phone="13700137000",
        address="上海",
    )

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
        status=1,
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
        "super_admin_user": super_admin_user,
        "director_user": director_user,
        "doctor_user": doc_user,
        "nurse_user": nurse_user,
        "cashier_user": cashier_user,
        "pharmacist_user": pharmacist_user,
        "guide_user": guide_user,
        "lab_tech_user": lab_tech_user,
        "registrar_user": registrar_user,
        "doctor": doctor,
        "director_doctor": director_doctor,
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


def settle_prescription_charges(prescription_id) -> None:
    """测试辅助：模拟缴费（把处方关联收费 status=0 置 1）。发药缴费校验的前置。"""
    import datetime

    from app.models import Charge

    session = TestingSessionLocal()
    try:
        session.query(Charge).filter(
            Charge.prescription_id == str(prescription_id), Charge.status == 0
        ).update({Charge.status: 1, Charge.time: datetime.datetime.now()}, synchronize_session=False)
        session.commit()
    finally:
        session.close()


@pytest.fixture
def auth_headers():
    from app.routers.user import create_access_token

    def _auth_headers(username: str) -> dict[str, str]:
        return {"accesstoken": create_access_token(username)}

    return _auth_headers
