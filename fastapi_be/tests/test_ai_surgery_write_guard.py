"""Legacy surgery gate order and real SQLite transactions, not lock-wait proof."""

import datetime
import uuid

import pytest
from sqlalchemy import event, text
from sqlalchemy.exc import IntegrityError

from app.ai.models import AIAuditEvent
from app.ai.surgery_models import AISurgeryWriteGate
from app.ai.surgery_write_guard import current_surgery_rows, lock_surgery_write
from app.models import Admission, AnesthesiaRecord, InpatientCharge, PerioperativeAntibiotic, SurgeryApplication, SurgerySchedule
from app.routers import surgery

NOW = datetime.datetime(2026, 10, 20, 10, 0, 0, 123456)
WRITES = {
    "/surgery/perioperative/create",
    "/surgery/perioperative/status",
    "/surgeryApplication/create",
    "/surgeryApplication/approve",
    "/surgeryApplication/cancel",
    "/surgerySchedule/create",
    "/surgerySchedule/start",
    "/surgerySchedule/complete",
    "/anesthesiaRecord/create",
}


@pytest.fixture
def legacy_case(db_session, seed_data):
    db = db_session
    admission = Admission(
        admission_id=str(uuid.uuid4()),
        patient_id=seed_data["patient"].patient_id,
        doctor_id=seed_data["doctor"].doctor_id,
        department_id=seed_data["department"].department_id,
        status=1,
        admission_time=NOW,
    )
    application = SurgeryApplication(
        application_id=str(uuid.uuid4()),
        admission_id=admission.admission_id,
        patient_id=admission.patient_id,
        doctor_id=seed_data["doctor"].doctor_id,
        surgery_name="合成门控手术",
        scheduled_date=NOW.date(),
        status=1,
        create_time=NOW,
    )
    schedule = SurgerySchedule(
        schedule_id=str(uuid.uuid4()),
        application_id=application.application_id,
        patient_id=admission.patient_id,
        operating_room="synthetic-" + uuid.uuid4().hex,
        surgery_date=NOW.date(),
        status=0,
        create_time=NOW,
    )
    db.add_all([admission, application, schedule])
    db.commit()
    return {"seed": seed_data, "admission": admission, "application": application, "schedule": schedule}


def request_for(db, case, path):
    application, schedule, seed = case["application"], case["schedule"], case["seed"]
    if path == "/surgeryApplication/create":
        return {"admission_id": case["admission"].admission_id, "doctor_id": seed["doctor"].doctor_id, "surgery_name": "合成新申请", "scheduled_date": "2026-10-21"}
    if path == "/surgeryApplication/approve":
        application.status = 0
        return {"application_id": application.application_id}
    if path == "/surgeryApplication/cancel":
        application.status = 2
        return {"application_id": application.application_id}
    if path == "/surgerySchedule/create":
        db.delete(schedule)
        return {
            "application_id": application.application_id,
            "operating_room": "synthetic-new-" + uuid.uuid4().hex,
            "surgery_date": "2026-10-22",
            "surgeon_id": seed["doctor"].doctor_id,
            "assistant_ids": "explicit-team-original",
        }
    if path == "/surgerySchedule/complete":
        schedule.status, schedule.start_time = 1, NOW
        return {"schedule_id": schedule.schedule_id}
    if path == "/surgerySchedule/start":
        return {"schedule_id": schedule.schedule_id}
    if path == "/anesthesiaRecord/create":
        return {
            "schedule_id": schedule.schedule_id,
            "anesthesiologist_id": seed["doctor"].doctor_id,
            "enter_time": "2026-10-20 09:59:00",
            "leave_time": "2026-10-20 11:01:00",
            "anesthesia_method": "合成原记录",
        }
    pharmaceutical = seed["pharmaceutical"]
    pharmaceutical.status, pharmaceutical.antibiotic_level = 0, 1
    if path == "/surgery/perioperative/create":
        return {"application_id": application.application_id, "pharmaceutical_id": pharmaceutical.pharmaceutical_id, "dose": "合成原剂量", "timing_minutes": 0}
    if path == "/surgery/perioperative/status":
        item = PerioperativeAntibiotic(
            application_id=application.application_id,
            patient_id=application.patient_id,
            pharmaceutical_id=pharmaceutical.pharmaceutical_id,
            prescriber_id=seed["doctor_user"].user_id,
            dose="合成原剂量",
            timing_minutes=0,
            status=0,
            create_time=NOW,
        )
        db.add(item)
        db.flush()
        return {"perioperative_id": item.perioperative_id, "status": 1}
    raise AssertionError(path)


@pytest.mark.asyncio
@pytest.mark.parametrize("path", sorted(WRITES))
async def test_every_actual_legacy_write_takes_same_gate_before_related_sql_and_keeps_success(path, db_session, legacy_case, async_client, auth_headers):
    case, db = legacy_case, db_session
    request = request_for(db, case, path)
    db.commit()
    statements, commits = [], []
    engine = db.get_bind()

    def capture(connection, cursor, statement, parameters, context, executemany):
        compiled = getattr(context, "compiled", None)
        original = getattr(compiled, "statement", None)
        statements.append((statement.lower(), getattr(original, "_for_update_arg", None) is not None))

    def committed(connection):
        commits.append(len(statements))

    event.listen(engine, "before_cursor_execute", capture)
    event.listen(engine, "commit", committed)
    try:
        response = await async_client.post("/api" + path, headers=auth_headers(case["seed"]["admin_user"].username), json=request)
    finally:
        event.remove(engine, "before_cursor_execute", capture)
        event.remove(engine, "commit", committed)
    assert response.status_code == 200 and response.json()["code"] == 200, response.text
    gate = [index for index, (sql, _) in enumerate(statements) if "hoimsystem_ai_surgery_write_gate" in sql]
    assert len(gate) == 2 and "insert into" in statements[gate[0]][0] and statements[gate[1]][1]
    related = [
        index
        for index, (sql, _) in enumerate(statements)
        if any(
            name in sql
            for name in ("hoimsystem_surgery_application", "hoimsystem_surgery_schedule", "hoimsystem_perioperative_antibiotic", "hoimsystem_anesthesia_record", "hoimsystem_inpatient_charge")
        )
    ]
    assert related and all(gate[1] < index for index in related)
    assert commits and all(index < commits[0] for index in related if statements[index][0].lstrip().startswith(("insert", "update", "delete")))
    # Serialization can perform read-only refreshes after commit. Current
    # mutation decisions must instead be locking reads inside the gate's tx.
    related_reads = [
        (sql, locked) for sql, locked in statements[: commits[0]] if sql.lstrip().startswith("select") and ("hoimsystem_surgery_application" in sql or "hoimsystem_surgery_schedule" in sql)
    ]
    assert all(locked for _, locked in related_reads)
    assert db.get(AISurgeryWriteGate, 1) is not None
    db.expire_all()
    if path == "/surgerySchedule/create":
        created = db.get(SurgerySchedule, response.json()["data"]["schedule_id"])
        assert created.assistant_ids == "explicit-team-original"
    if path == "/anesthesiaRecord/create":
        created = db.get(AnesthesiaRecord, response.json()["data"]["record_id"])
        assert created.enter_time == datetime.datetime(2026, 10, 20, 9, 59)
        assert created.leave_time == datetime.datetime(2026, 10, 20, 11, 1)


def test_actual_router_write_set_is_closed_so_future_mutation_cannot_escape_gate_tests():
    actual = {route.path for route in surgery.router.routes if route.methods & {"POST", "PUT", "PATCH", "DELETE"}}
    assert actual == WRITES


def test_pending_orm_changes_cannot_autoflush_before_the_gate(db_session, legacy_case):
    db = db_session
    before = []
    case = legacy_case
    case["application"].surgery_name = "合成待写原件"

    def capture(connection, cursor, statement, parameters, context, executemany):
        before.append(statement.lower())

    event.listen(db.get_bind(), "before_cursor_execute", capture)
    try:
        with db.no_autoflush:
            old_autoflush = db.autoflush
        db.autoflush = True
        lock_surgery_write(db)
        db.flush()
    finally:
        db.autoflush = old_autoflush
        event.remove(db.get_bind(), "before_cursor_execute", capture)
    gate_index = next(index for index, sql in enumerate(before) if "insert into hoimsystem_ai_surgery_write_gate" in sql)
    change_index = next(index for index, sql in enumerate(before) if "update hoimsystem_surgery_application" in sql)
    assert gate_index == 0 and change_index > gate_index
    db.rollback()


def test_current_read_refreshes_stale_identity_map_after_gate(db_session, legacy_case):
    db = db_session
    original = legacy_case["application"]
    assert original.status == 1
    db.execute(text("UPDATE hoimsystem_surgery_application SET status=2 WHERE application_id=:id"), {"id": original.application_id})
    assert original.status == 1  # Literal SQL leaves this ORM original stale.
    lock_surgery_write(db)
    current = current_surgery_rows(db.query(SurgeryApplication).filter_by(application_id=original.application_id)).one()
    assert current is original and current.status == 2
    db.rollback()


def test_actual_sql_failure_rolls_back_gate_and_legacy_application_together(db_session, legacy_case):
    db = db_session
    db.query(AISurgeryWriteGate).delete()
    db.commit()
    application = legacy_case["application"]
    original_status = application.status
    lock_surgery_write(db)
    current = current_surgery_rows(db.query(SurgeryApplication).filter_by(application_id=application.application_id)).one()
    current.status = 4
    db.add(AIAuditEvent(actor_id=legacy_case["seed"]["admin_user"].user_id, action=None, target=application.application_id, detail_json="{}"))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()
    assert db.get(AISurgeryWriteGate, 1) is None
    assert db.get(SurgeryApplication, application.application_id).status == original_status
    assert db.query(AIAuditEvent).filter_by(target=application.application_id).count() == 0


@pytest.mark.asyncio
async def test_unauthorized_nurse_cannot_gain_legacy_clinical_write_permission_or_take_gate(async_client, auth_headers, db_session, legacy_case):
    db_session.query(AISurgeryWriteGate).delete()
    db_session.commit()
    response = await async_client.post("/api/surgerySchedule/start", headers=auth_headers(legacy_case["seed"]["nurse_user"].username), json={"schedule_id": legacy_case["schedule"].schedule_id})
    assert response.status_code == 403
    assert db_session.get(AISurgeryWriteGate, 1) is None
    assert db_session.get(SurgerySchedule, legacy_case["schedule"].schedule_id).status == 0


def test_old_complete_transaction_failure_keeps_original_state_and_no_charge(db_session, legacy_case):
    db, case = db_session, legacy_case
    schedule = case["schedule"]
    schedule.status, schedule.start_time = 1, NOW
    db.commit()
    before = db.query(InpatientCharge).filter_by(admission_id=case["admission"].admission_id).count()
    # An actual constraint failure inside the existing endpoint's commit tests
    # its state/charge rollback, rather than replacing commit with a test stub.
    db.add(AIAuditEvent(actor_id=case["seed"]["admin_user"].user_id, action=None, target=schedule.schedule_id, detail_json="{}"))
    with pytest.raises(IntegrityError):
        surgery.complete_surgery({"schedule_id": schedule.schedule_id}, current_user=case["seed"]["admin_user"], db=db)
    db.rollback()
    db.expire_all()
    assert db.get(SurgerySchedule, schedule.schedule_id).status == 1
    assert db.get(SurgerySchedule, schedule.schedule_id).end_time is None
    assert db.get(SurgeryApplication, case["application"].application_id).status == 1
    assert db.query(InpatientCharge).filter_by(admission_id=case["admission"].admission_id).count() == before


def extra_schedule(db, case, *, status=0, start=None, end=None):
    row = SurgerySchedule(
        schedule_id=str(uuid.uuid4()),
        application_id=case["application"].application_id,
        patient_id=case["application"].patient_id,
        operating_room="synthetic-child",
        surgery_date=NOW.date(),
        status=status,
        start_time=start,
        end_time=end,
        create_time=NOW,
    )
    db.add(row)
    db.flush()
    return row


def child_states(db, application_id):
    return {row.schedule_id: (row.status, row.start_time, row.end_time) for row in db.query(SurgerySchedule).filter_by(application_id=application_id).all()}


@pytest.mark.asyncio
async def test_cancel_updates_all_unstarted_children_and_preserves_already_cancelled_originals(db_session, legacy_case, async_client, auth_headers):
    db, case = db_session, legacy_case
    case["application"].status = 2
    extra_schedule(db, case)
    extra_schedule(db, case)
    cancelled = extra_schedule(db, case, status=3)
    db.commit()
    before = child_states(db, case["application"].application_id)
    response = await async_client.post("/api/surgeryApplication/cancel", headers=auth_headers(case["seed"]["doctor_user"].username), json={"application_id": case["application"].application_id})
    assert response.status_code == 200 and response.json()["code"] == 200
    db.expire_all()
    after = child_states(db, case["application"].application_id)
    assert len(after) == 4 and all(state == (3, None, None) for state in after.values())
    assert after[cancelled.schedule_id] == before[cancelled.schedule_id]
    assert db.get(SurgeryApplication, case["application"].application_id).status == 4


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,start,end",
    [
        (1, NOW, None),
        (1, NOW, NOW + datetime.timedelta(hours=1)),
        (2, NOW, NOW + datetime.timedelta(hours=1)),
        (3, NOW, None),
        (0, NOW, None),
        (0, NOW, NOW + datetime.timedelta(hours=1)),
        (0, None, NOW),
    ],
)
async def test_cancel_rejects_any_unclosed_or_executed_inconsistent_child_before_changing_others(status, start, end, db_session, legacy_case, async_client, auth_headers):
    db, case = db_session, legacy_case
    case["application"].status = 2
    # The ordinary unstarted first row remains: the former .first() path would
    # cancel only that row and miss this later running/completed original.
    extra_schedule(db, case, status=status, start=start, end=end)
    db.commit()
    application_id = case["application"].application_id
    before = child_states(db, application_id)
    response = await async_client.post("/api/surgeryApplication/cancel", headers=auth_headers(case["seed"]["doctor_user"].username), json={"application_id": application_id})
    assert response.status_code == 400 and response.json()["code"] == 500
    db.expire_all()
    assert child_states(db, application_id) == before
    assert db.get(SurgeryApplication, application_id).status == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("parent_status", [3, 4])
async def test_start_cannot_resurrect_unstarted_child_of_completed_or_cancelled_application(parent_status, db_session, legacy_case, async_client, auth_headers):
    db, case = db_session, legacy_case
    case["application"].status = parent_status
    db.commit()
    response = await async_client.post("/api/surgerySchedule/start", headers=auth_headers(case["seed"]["doctor_user"].username), json={"schedule_id": case["schedule"].schedule_id})
    assert response.status_code == 400 and response.json()["code"] == 500
    db.expire_all()
    schedule = db.get(SurgerySchedule, case["schedule"].schedule_id)
    assert (schedule.status, schedule.start_time, schedule.end_time) == (0, None, None)
    assert db.get(SurgeryApplication, case["application"].application_id).status == parent_status


def test_cancel_all_children_sql_failure_rolls_back_every_state_without_invented_clocks(db_session, legacy_case):
    db, case = db_session, legacy_case
    case["application"].status = 2
    extra_schedule(db, case)
    extra_schedule(db, case)
    db.commit()
    application_id = case["application"].application_id
    before = child_states(db, application_id)
    db.add(AIAuditEvent(actor_id=case["seed"]["admin_user"].user_id, action=None, target=application_id, detail_json="{}"))
    with pytest.raises(IntegrityError):
        surgery.cancel_surgery_application({"application_id": application_id}, current_user=case["seed"]["doctor_user"], db=db)
    db.rollback()
    db.expire_all()
    assert child_states(db, application_id) == before
    assert db.get(SurgeryApplication, application_id).status == 2
