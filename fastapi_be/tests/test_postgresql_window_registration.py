"""Actual PostgreSQL patient locking protects both registration entry points."""

import os
import threading
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.database import Base
from app.models import Charge, Department, Doctor, DoctorSchedule, Patient, Registration, User
from app.routers.charge import get_window_registration_patient, window_registration
from app.routers.patient import patient_registration
from app.schemas import RegistrationCreateRequest


@pytest.fixture
def registration_database():
    value = os.getenv("HOIM_TEST_POSTGRES_URL")
    if not value:
        pytest.skip("requires the explicitly isolated local PostgreSQL benchmark database")
    url = make_url(value)
    if url.get_backend_name() != "postgresql" or url.database != "hoimsystem_benchmark" or url.host not in {"127.0.0.1", "localhost", "::1"}:
        pytest.fail("refusing non-benchmark PostgreSQL target")
    schema = "validation_registration_" + uuid4().hex
    control = create_engine(url)
    with control.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(url, connect_args={"options": f"-c search_path={schema} -c statement_timeout=10000"}, pool_size=12, max_overflow=0)
    try:
        Base.metadata.create_all(engine)
        with Session(engine) as db:
            actor = User(username="window-reg", password="synthetic-unused", user_role="cashier")
            patient_user = User(username="synthetic-patient", password="synthetic-unused", user_role="patient")
            doctor_user = User(username="synthetic-doctor", password="synthetic-unused", user_role="doctor")
            dept = Department(name="合成窗口科室")
            patient = Patient(name="合成窗口对象", identity=patient_user.username, permission="allow", prepaid_balance=0)
            db.add_all([actor, patient_user, doctor_user, dept, patient])
            db.flush()
            doctor = Doctor(name="合成医生", department_id=dept.department_id, user_id=doctor_user.user_id)
            db.add(doctor)
            db.flush()
            schedule = DoctorSchedule(doctor_id=doctor.doctor_id, specialist=1, week="星期一", time="01", number=20)
            db.add(schedule)
            db.commit()
            ids = dict(actor=actor.user_id, patient_user=patient_user.user_id, patient=patient.patient_id, doctor=doctor.doctor_id, department=dept.department_id, schedule=schedule.schedule_id, identity=patient.identity)
        yield engine, ids
    finally:
        engine.dispose()
        with control.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        control.dispose()


def register(engine, ids, *, window=True):
    with Session(engine) as db:
        if window:
            actor = db.get(User, ids["actor"])
            return window_registration({"identity": ids["identity"], "schedule_id": ids["schedule"], "doctor_id": ids["doctor"], "department_id": ids["department"], "specialist": 1}, db=db, current_user=actor)
        actor = db.get(User, ids["patient_user"])
        return patient_registration(RegistrationCreateRequest(id=ids["schedule"], doctor_id=ids["doctor"], department_id=ids["department"], specialist=1, patient_id=ids["patient"]), current_user=actor, db=db)


def test_window_waits_for_actual_patient_row_before_creating_registration(registration_database):
    engine, ids = registration_database
    entered = threading.Event()
    def contender():
        entered.set()
        return register(engine, ids)
    with Session(engine) as holder, ThreadPoolExecutor(max_workers=1) as pool:
        holder.query(Patient).filter_by(patient_id=ids["patient"]).with_for_update().one()
        future = pool.submit(contender)
        try:
            assert entered.wait(timeout=3)
            threading.Event().wait(.2)
            assert not future.done(), "window registration escaped the held patient lock"
        finally:
            holder.rollback()
        assert future.result(timeout=10)["code"] == 200


def test_identity_preview_does_not_wait_for_registration_patient_lock(registration_database):
    engine, ids = registration_database
    def preview():
        with Session(engine) as db:
            return get_window_registration_patient(identity=ids["identity"], db=db, current_user=db.get(User, ids["actor"]))
    with Session(engine) as holder, ThreadPoolExecutor(max_workers=1) as pool:
        holder.query(Patient).filter_by(patient_id=ids["patient"]).with_for_update().one()
        future = pool.submit(preview)
        try:
            assert future.result(timeout=3)["data"]["patient_id"] == ids["patient"]
        finally:
            holder.rollback()


@pytest.mark.parametrize("mixed", [False, True], ids=["window-window", "window-patient"])
def test_actual_concurrent_registration_entries_create_one_registration_and_charge(registration_database, mixed):
    engine, ids = registration_database
    barrier = threading.Barrier(10)
    def contender(index):
        barrier.wait(timeout=10)
        return register(engine, ids, window=not mixed or index % 2 == 0)
    with ThreadPoolExecutor(max_workers=10) as pool:
        results = list(pool.map(contender, range(10)))
    assert sum(row["code"] == 200 for row in results) == 1
    with Session(engine) as db:
        registrations = db.query(Registration).filter_by(patient_id=ids["patient"], status=0).all()
        assert len(registrations) == 1
        assert db.get(DoctorSchedule, ids["schedule"]).number == 19
        assert db.query(Charge).filter_by(registration_uuid=registrations[0].registration_uuid).count() == 1
