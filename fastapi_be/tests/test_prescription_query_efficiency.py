import datetime

from fastapi import BackgroundTasks
from sqlalchemy import event

from app.models import Charge, Pharmaceutical, PrePha, Prescription
from app.routers.doctor import get_prescription_list, prescription_register
from app.schemas import PrescriptionCreateRequest


def _capture_selects(engine, operation):
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


def test_prescription_list_query_count_is_independent_of_rows(seed_data, db_session):
    now = datetime.datetime.now()
    for index in range(25):
        prescription = Prescription(
            patient_id=seed_data["patient"].patient_id,
            doctor_id=seed_data["doctor"].doctor_id,
            status=0,
            create_time=now,
        )
        db_session.add(prescription)
        db_session.flush()
        db_session.add(
            PrePha(
                prescription_id=prescription.prescription_id,
                pharmaceutical_id=seed_data["pharmaceutical"].pharmaceutical_id,
                number=1,
            )
        )
        db_session.add(
            Charge(
                charge_time=now,
                prescription_id=prescription.prescription_id,
                amount=15.5,
                status=0,
            )
        )
    db_session.commit()
    db_session.expire_all()
    # Resolve the caller identity before counting endpoint data queries; in the
    # real request path authentication has already loaded these fields.
    db_session.refresh(seed_data["admin_user"])

    result, statements = _capture_selects(
        db_session.get_bind(),
        lambda: get_prescription_list(seed_data["admin_user"], None, 1, 20, db_session),
    )

    assert result["total"] >= 26
    assert len(result["data"]) == 20
    assert len(statements) == 4


def test_prescription_create_loads_all_drugs_in_one_select(seed_data, db_session):
    drugs = [seed_data["pharmaceutical"]]
    for index in range(4):
        drug = Pharmaceutical(
            name=f"批量药品{index}",
            stock=100,
            price=10,
            expireddate=datetime.date.today() + datetime.timedelta(days=365),
            purchasing_time=datetime.datetime.now(),
            supplier="测试供应商",
            status=0,
        )
        db_session.add(drug)
        drugs.append(drug)
    db_session.commit()

    request = PrescriptionCreateRequest(
        patient=seed_data["patient"].patient_id,
        phas=[{"id": drug.pharmaceutical_id, "number": 1} for drug in drugs],
    )
    result, statements = _capture_selects(
        db_session.get_bind(),
        lambda: prescription_register(
            request,
            BackgroundTasks(),
            seed_data["doctor_user"],
            db_session,
        ),
    )
    drug_selects = [
        statement
        for statement in statements
        if "FROM HOIMSYSTEM_PHARMACEUTICAL" in statement.upper()
    ]

    assert result["code"] == 200
    assert len(drug_selects) == 1
