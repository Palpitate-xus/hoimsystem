import datetime

from sqlalchemy import event

from app.models import Admission, Appointment, Bed, Invoice, MedicalRecordHome, Ward
from app.routers.admission import get_available_beds, get_inpatient_list
from app.routers.charge import get_invoice_list
from app.routers.checkin import get_appointments_for_checkin
from app.routers.doctor import get_attendance_list, get_slot_pool
from app.routers.medical_record_home import list_medical_record_admissions, list_medical_record_homes


def _count_selects(engine, operation):
    statements = []

    def before_cursor_execute(_conn, _cursor, statement, _parameters, _context, _executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    event.listen(engine, "before_cursor_execute", before_cursor_execute)
    try:
        result = operation()
    finally:
        event.remove(engine, "before_cursor_execute", before_cursor_execute)
    return result, statements


def test_invoice_list_eager_loads_patient_in_one_query(seed_data, db_session):
    db_session.add(
        Invoice(
            charge_id=seed_data["charge"].charge_id,
            invoice_no="PERF-INVOICE",
            amount=31,
            invoice_time=datetime.datetime.now(),
            status=0,
        )
    )
    db_session.commit()

    result, statements = _count_selects(
        db_session.get_bind(),
        lambda: get_invoice_list(None, db_session, seed_data["cashier_user"]),
    )

    assert result["code"] == 200
    assert len(statements) == 1


def test_admission_lists_eager_load_relationships(seed_data, db_session):
    ward = Ward(name="性能病区", department_id=seed_data["department"].department_id, status=0)
    db_session.add(ward)
    db_session.flush()
    beds = [
        Bed(ward_id=ward.ward_id, bed_no=f"P{index}", bed_type="普通", status=0)
        for index in range(3)
    ]
    db_session.add_all(beds)
    db_session.flush()
    admission = Admission(
        admission_no="PERF-ADMISSION",
        patient_id=seed_data["patient"].patient_id,
        doctor_id=seed_data["doctor"].doctor_id,
        department_id=seed_data["department"].department_id,
        ward_id=ward.ward_id,
        bed_id=beds[0].bed_id,
        admission_time=datetime.datetime.now(),
        status=1,
        create_time=datetime.datetime.now(),
    )
    db_session.add(admission)
    db_session.commit()

    beds_result, bed_statements = _count_selects(
        db_session.get_bind(),
        lambda: get_available_beds(None, seed_data["nurse_user"], db_session),
    )
    inpatient_result, inpatient_statements = _count_selects(
        db_session.get_bind(),
        lambda: get_inpatient_list(None, None, seed_data["nurse_user"], db_session),
    )

    assert beds_result["code"] == inpatient_result["code"] == 200
    assert len(bed_statements) == 1
    assert len(inpatient_statements) == 1


def test_checkin_list_uses_two_queries_regardless_of_rows(seed_data, db_session):
    patient = seed_data["patient"]
    doctor = seed_data["doctor"]
    db_session.add_all(
        [
            Appointment(
                registration_uuid=f"PERF-CHECKIN-{index}",
                patient_id=patient.patient_id,
                doctor_id=doctor.doctor_id,
                department_id=doctor.department_id,
                appointment_time=datetime.datetime.now(),
                time=datetime.date.today(),
                status=0,
            )
            for index in range(3)
        ]
    )
    db_session.commit()
    identity = patient.identity
    phone_tail = patient.phone[-4:]

    result, statements = _count_selects(
        db_session.get_bind(),
        lambda: get_appointments_for_checkin(identity, phone_tail, db_session),
    )

    assert result["code"] == 200
    assert len(statements) == 2


def test_slot_pool_is_one_aggregate_query(seed_data, db_session):
    result, statements = _count_selects(
        db_session.get_bind(),
        lambda: get_slot_pool(seed_data["admin_user"], db_session),
    )

    assert result["code"] == 200
    assert len(statements) == 1


def test_medical_record_home_lists_have_fixed_query_counts(seed_data, db_session):
    admission = db_session.query(Admission).filter(Admission.admission_no == "PERF-ADMISSION").first()
    if admission is None:
        admission = Admission(
            admission_no="PERF-HOME-ADMISSION",
            patient_id=seed_data["patient"].patient_id,
            doctor_id=seed_data["doctor"].doctor_id,
            department_id=seed_data["department"].department_id,
            admission_time=datetime.datetime.now(),
            status=1,
            create_time=datetime.datetime.now(),
        )
        db_session.add(admission)
        db_session.flush()
    db_session.add(
        MedicalRecordHome(
            admission_id=admission.admission_id,
            patient_id=admission.patient_id,
            doctor_id=admission.doctor_id,
            admission_diagnosis="性能测试",
            discharge_diagnosis="",
            discharge_status=0,
            total_fee=0,
            status=0,
            creator_id=seed_data["admin_user"].user_id,
            create_time=datetime.datetime.now(),
            update_time=datetime.datetime.now(),
        )
    )
    db_session.commit()
    admin_user = seed_data["admin_user"]
    _ = admin_user.user_role

    admissions_result, admission_statements = _count_selects(
        db_session.get_bind(),
        lambda: list_medical_record_admissions(admin_user, db_session),
    )
    homes_result, home_statements = _count_selects(
        db_session.get_bind(),
        lambda: list_medical_record_homes(None, None, admin_user, db_session),
    )

    assert admissions_result["code"] == homes_result["code"] == 200
    assert len(admission_statements) == 1
    assert len(home_statements) == 1


def test_attendance_list_eager_loads_doctors(seed_data, db_session):
    result, statements = _count_selects(
        db_session.get_bind(),
        lambda: get_attendance_list(None, None, None, seed_data["admin_user"], db_session),
    )

    assert result["code"] == 200
    assert len(statements) == 1
