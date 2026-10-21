"""Current note ownership/signature boundaries; SQLite is not a lock oracle."""

import datetime as dt

import pytest
from fastapi import HTTPException
from sqlalchemy import event, text
from sqlalchemy.dialects import mysql
from sqlalchemy.exc import OperationalError

from app.medical_record_write_guard import current_rows, medical_record_transaction
from app.models import Doctor, MedicalRecord
from app.routers.doctor import sign_medical_record, update_medical_record
from app.schemas import MedicalRecordSignRequest, MedicalRecordUpdateRequest


def unsigned(db, data):
    # The shared fixture appends Doctor aliases for a reused User each test.
    # Bind this new original to the exact first alias the legacy writer uses;
    # a later fixture alias is not an authorization grant.
    owner = db.query(Doctor).filter_by(user_id=data["doctor_user"].user_id).first()
    row = MedicalRecord(patient_id=data["patient"].patient_id, doctor_id=owner.doctor_id, status=0, sign_time=None, symptom="原完整未签正文", result="原结果")
    db.add(row)
    db.commit()
    return row.medical_record_id


def test_current_unsigned_update_then_sign_keeps_literal_content_and_duplicate_business_codes(db_session, seed_data):
    db, data = db_session, seed_data
    identifier = unsigned(db, data)
    exact = "\ufeff合成原文\r\n😀2026-10-21T12:00:00.123456Z"
    response = update_medical_record(MedicalRecordUpdateRequest(medical_record_id=identifier, symptom=exact, result="未规范化原结果"), data["doctor_user"], db)
    assert response == {"code": 200, "msg": "success"}
    assert sign_medical_record(MedicalRecordSignRequest(medical_record_id=identifier), data["doctor_user"], db)["code"] == 200
    row = db.query(MedicalRecord).populate_existing().filter_by(medical_record_id=identifier).one()
    assert row.status == 1 and row.sign_time is not None and row.symptom == exact
    original_clock = row.sign_time
    assert update_medical_record(MedicalRecordUpdateRequest(medical_record_id=identifier, symptom="不应改写", result="不应改写"), data["doctor_user"], db) == {"code": 403, "msg": "已签名病历不可修改"}
    assert sign_medical_record(MedicalRecordSignRequest(medical_record_id=identifier), data["doctor_user"], db) == {"code": 500, "msg": "病历已签名"}
    db.refresh(row)
    assert (row.status, row.sign_time, row.symptom) == (1, original_clock, exact)


@pytest.mark.parametrize("signing", [False, True])
def test_missing_and_other_doctor_business_denials_are_not_expanded(db_session, seed_data, signing):
    data, db = seed_data, db_session
    function = sign_medical_record if signing else update_medical_record

    def request(identifier):
        return MedicalRecordSignRequest(medical_record_id=identifier) if signing else MedicalRecordUpdateRequest(medical_record_id=identifier, symptom="不应写", result="不应写")

    assert function(request("actual-legacy-missing-id"), data["doctor_user"], db) == {"code": 500, "msg": "病历不存在"}
    result = function(request(data["medical_record"].medical_record_id), data["director_user"], db)
    assert result == {"code": 403, "msg": "无权签名他人病历" if signing else "无权修改他人病历"}


@pytest.mark.parametrize("signing", [False, True])
@pytest.mark.parametrize("change", ["role", "epoch"])
def test_actual_cached_actor_role_or_token_change_rejected_before_any_note_text(db_session, seed_data, signing, change):
    db, data = db_session, seed_data
    identifier = unsigned(db, data)
    actor = data["doctor_user"]
    _ = actor.user_role, actor.token_invalid_before
    if change == "role":
        db.execute(text("UPDATE hoimsystem_users SET user_role='patient' WHERE user_id=:id"), {"id": actor.user_id})
    else:
        db.execute(text("UPDATE hoimsystem_users SET token_invalid_before=:clock WHERE user_id=:id"), {"id": actor.user_id, "clock": dt.datetime(2030, 1, 1)})
    db.flush()
    statements = []

    def observe(conn, cursor, statement, parameters, context, many):
        statements.append(statement)

    event.listen(db.bind, "before_cursor_execute", observe)
    try:
        with pytest.raises(HTTPException) as error:
            if signing:
                sign_medical_record(MedicalRecordSignRequest(medical_record_id=identifier), actor, db)
            else:
                update_medical_record(MedicalRecordUpdateRequest(medical_record_id=identifier, symptom="不应写", result="不应写"), actor, db)
        assert error.value.status_code == 403
    finally:
        event.remove(db.bind, "before_cursor_execute", observe)
    assert not any("hoimsystem_medical_record.symptom" in statement for statement in statements)


@pytest.mark.parametrize("errno", [1205, 1213, 3572, 1054])
def test_only_actual_named_mysql_lock_conflicts_are_rolled_back_and_mapped(db_session, monkeypatch, errno):
    class DriverError(Exception):
        pass

    error = OperationalError("synthetic statement", {}, DriverError(errno, "synthetic test"))
    rolled_back = []
    monkeypatch.setattr(db_session, "rollback", lambda: rolled_back.append(True))
    with pytest.raises(HTTPException if errno != 1054 else OperationalError) as caught:
        with medical_record_transaction(db_session):
            raise error
    assert rolled_back == [True]
    if errno != 1054:
        assert caught.value.status_code == 409
    else:
        assert caught.value is error


def test_compiled_mysql_locator_and_note_locks_explicit_current_nowait(db_session, seed_data):
    query = db_session.query(MedicalRecord.patient_id, MedicalRecord.doctor_id).filter_by(medical_record_id=seed_data["medical_record"].medical_record_id)
    locator = str(current_rows(query, shared=True).statement.compile(dialect=mysql.dialect()))
    writer = str(current_rows(query).statement.compile(dialect=mysql.dialect()))
    assert "LOCK IN SHARE MODE NOWAIT" in locator and "symptom" not in locator
    assert "FOR UPDATE NOWAIT" in writer


@pytest.mark.parametrize("wrong_registration_doctor", [False, True])
def test_sign_completes_only_current_same_patient_and_doctor_children(db_session, seed_data, wrong_registration_doctor):
    from app.models import Queue, Registration

    db, data = db_session, seed_data
    identifier = unsigned(db, data)
    patient_id = data["patient"].patient_id
    record = db.get(MedicalRecord, identifier)
    doctor_id = record.doctor_id
    other_id = data["director_doctor"].doctor_id
    registration = Registration(patient_id=patient_id, doctor_id=other_id if wrong_registration_doctor else doctor_id, status=0)
    own = Queue(patient_id=patient_id, doctor_id=doctor_id, status=0)
    other = Queue(patient_id=patient_id, doctor_id=other_id, status=0)
    db.add_all([registration, own, other])
    db.flush()
    record.registration_uuid = registration.registration_uuid
    db.commit()
    assert sign_medical_record(MedicalRecordSignRequest(medical_record_id=identifier), data["doctor_user"], db)["code"] == 200
    db.refresh(registration)
    db.refresh(own)
    db.refresh(other)
    assert registration.status == (0 if wrong_registration_doctor else 1)
    assert own.status == 2 and other.status == 0
