"""Actual whole-family capture with research permissions before any body."""

import copy
import datetime as dt
import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import event, text

from app.ai import research_cohort_collection as collection
from app.ai.research_cohort_registry import create_registry_original, review_registry_original
from app.ai.research_cohort_sources import hash_content
from app.models import MedicalRecord, Patient, Registration
from tests.test_ai_research_cohort_contract import BASIS
from tests.test_ai_research_cohort_registry import acl_request, anchors, permitted
from tests.test_ai_research_cohort_sources import research_case as research_case  # noqa: F401


def clinical_case(db, case):
    pid = case["patient"].patient_id
    doctor = case["doctor"].doctor_id
    reg = Registration(registration_uuid=str(uuid.uuid4()), patient_id=pid, doctor_id=doctor, department_id=case["doctor"].department_id, specialist=0, time=dt.datetime(2026, 10, 11, 9), status=1)
    db.add(reg)
    db.flush()
    notes = [
        MedicalRecord(
            medical_record_id=str(uuid.uuid4()),
            patient_id=pid,
            doctor_id=doctor,
            registration_uuid=reg.registration_uuid,
            consultation_time=dt.datetime(2026, 10, 11, 9),
            symptom="\ufeff否认胸痛\r\n🧪原始字面量",
            result=None,
            status=1,
            sign_time=None,
        ),
        MedicalRecord(medical_record_id=str(uuid.uuid4()), patient_id=pid, doctor_id=doctor, registration_uuid=None, consultation_time=None, symptom="未知日期完整原文", result="未签署", status=0),
        MedicalRecord(medical_record_id=str(uuid.uuid4()), patient_id=pid, doctor_id=doctor, consultation_time=dt.datetime(2025, 10, 1), symptom="明确窗口外不得纳入", result=None, status=1),
    ]
    db.add_all(notes)
    db.commit()
    return reg, notes


def test_actual_whole_capture_keeps_unknown_clocks_literal_text_zero_and_all_roots(db_session, research_case):
    db, case = db_session, research_case
    case["scope_request"]["data_families"] = ["medical_records", "patient_demographics", "registrations"]
    scope, acl, permission = permitted(db, case)
    reg, notes = clinical_case(db, case)
    value = collection.capture_sources(db, case["admin_user"], anchors(scope), locking=True)
    assert collection.verify_capture(value) == value
    assert value["actor_acl"]["content_hash"] == acl["content_hash"]
    assert value["patient_authorizations"][0]["content_hash"] == permission["content_hash"]
    raw = {r["record_id"]: r for r in value["records"]}
    assert raw[notes[0].medical_record_id]["original"]["symptom"] == notes[0].symptom
    assert raw[notes[1].medical_record_id]["window_status"] == "unknown_clock"
    assert raw[notes[1].medical_record_id]["parent_binding"]["status"] == "unknown_parent"
    assert notes[2].medical_record_id not in raw
    assert raw[reg.registration_uuid]["original"]["specialist"] == 0
    assert all("name" not in r["original"] and "identity" not in r["original"] for r in raw.values())
    again = collection.capture_sources(db, case["admin_user"], anchors(scope))
    assert again["captured_at"] != value["captured_at"] and again["collection_digest"] == value["collection_digest"]


@pytest.mark.parametrize("actor_key", ["admin_user", "super_admin_user"])
def test_unpermitted_or_withdrawn_patient_blocks_every_clinical_body_even_super(db_session, research_case, actor_key):
    db, case = db_session, research_case
    scope, _, permission = permitted(db, case)
    clinical_case(db, case)
    review_registry_original(db, case["super_admin_user"], "authorization", permission["source_record_id"], {"expected_revision": 2, "basis_note": BASIS}, revoke=True)
    statements = []

    def seen(conn, cursor, statement, params, context, many):
        statements.append(statement)

    event.listen(db.bind, "before_cursor_execute", seen)
    try:
        with pytest.raises(HTTPException) as error:
            collection.capture_sources(db, case[actor_key], anchors(scope), locking=True)
        assert error.value.status_code == 403
    finally:
        event.remove(db.bind, "before_cursor_execute", seen)
    assert not any("hoimsystem_medical_record.symptom" in s or "hoimsystem_patient.sex" in s for s in statements)


def test_all_patients_authorized_before_first_body_not_partial_first_patient(db_session, research_case):
    db, case = db_session, research_case
    other = Patient(name="隔离第二患者未授权", sex=None)
    db.add(other)
    db.commit()
    case["scope_request"]["patient_ids"] = sorted([case["patient"].patient_id, other.patient_id])
    scope, _, _ = permitted(db, case)
    clinical_case(db, case)
    statements = []

    def seen(conn, cursor, statement, params, context, many):
        statements.append(statement)

    event.listen(db.bind, "before_cursor_execute", seen)
    try:
        with pytest.raises(HTTPException):
            collection.capture_sources(db, case["admin_user"], anchors(scope))
    finally:
        event.remove(db.bind, "before_cursor_execute", seen)
    assert not any("hoimsystem_medical_record.symptom" in s or "hoimsystem_patient.sex" in s for s in statements)


def test_new_root_same_count_body_mutation_and_nonwinner_revocation_change_complete_digest(db_session, research_case):
    db, case = db_session, research_case
    case["scope_request"]["data_families"] = ["medical_records", "patient_demographics"]
    scope, _, _ = permitted(db, case)
    _, notes = clinical_case(db, case)
    first = collection.capture_sources(db, case["admin_user"], anchors(scope))
    db.execute(text("UPDATE hoimsystem_medical_record SET symptom=:value WHERE medical_record_id=:id"), {"value": "新原量保持记录数不变", "id": notes[0].medical_record_id})
    db.commit()
    second = collection.capture_sources(db, case["admin_user"], anchors(scope))
    assert len(second["records"]) == len(first["records"]) and first["collection_digest"] != second["collection_digest"]
    # Unrelated member ACL is not an actor winner, but remains in full roots.
    body = {**acl_request(case, scope), "user_id": case["reviewer"].user_id}
    draft = create_registry_original(db, case["super_admin_user"], "acl", body)
    third = collection.capture_sources(db, case["admin_user"], anchors(scope))
    assert third["collection_digest"] != second["collection_digest"]
    review_registry_original(db, case["super_admin_user"], "acl", draft["source_record_id"], {"expected_revision": 1, "basis_note": BASIS}, revoke=True)
    fourth = collection.capture_sources(db, case["admin_user"], anchors(scope))
    assert fourth["collection_digest"] != third["collection_digest"]
    assert collection.verify_capture(fourth) == fourth


@pytest.mark.parametrize("limit", ["roots", "bytes"])
def test_real_capture_bounds_refuse_whole_instead_of_partial(db_session, research_case, monkeypatch, limit):
    db, case = db_session, research_case
    scope, _, _ = permitted(db, case)
    clinical_case(db, case)
    monkeypatch.setattr(collection, "MAX_ROOTS" if limit == "roots" else "MAX_BYTES", 2 if limit == "roots" else 100)
    with pytest.raises(HTTPException) as error:
        collection.capture_sources(db, case["admin_user"], anchors(scope))
    assert error.value.status_code == 413


@pytest.mark.parametrize("damage", ["body", "scope", "permissions", "calendar", "member", "foreign"])
def test_rehashed_false_capture_cannot_hide_original_binding_damage(db_session, research_case, damage):
    db, case = db_session, research_case
    case["scope_request"]["data_families"] = ["medical_records", "patient_demographics"]
    scope, _, _ = permitted(db, case)
    clinical_case(db, case)
    value = copy.deepcopy(collection.capture_sources(db, case["admin_user"], anchors(scope)))
    if damage == "body":
        value["records"][0]["original"]["symptom"] = "replaced"
    elif damage == "scope":
        value["scope_original"]["payload"]["patient_ids"] = [2147483647]
    elif damage == "permissions":
        value["patient_authorizations"] = []
    elif damage == "calendar":
        value["records"][0]["original"]["consultation_time"] = "2026-02-30T00:00:00.000000"
    elif damage == "member":
        value["member_manifest"] = []
    else:
        value["records"][0]["original"]["patient_id"] = 2147483647
    value["collection_digest"] = hash_content({k: v for k, v in value.items() if k not in {"collection_digest", "captured_at"}})
    with pytest.raises(HTTPException) as error:
        collection.verify_capture(value)
    assert error.value.status_code == 409


def test_mysql_compiled_keyset_is_current_and_does_not_lock_a_whole_unbounded_text_batch():
    from sqlalchemy import select
    from sqlalchemy.dialects import mysql

    statement = select(MedicalRecord.medical_record_id).where(MedicalRecord.patient_id == 7).order_by(MedicalRecord.medical_record_id).limit(collection.BATCH_SIZE).with_for_update()
    sql = str(statement.compile(dialect=mysql.dialect()))
    assert "FOR UPDATE" in sql and "LIMIT" in sql and "symptom" not in sql
