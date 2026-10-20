"""Actual controlled identities/care/CAS; no legacy execution or hospital data."""

import copy
import datetime
import json
import uuid

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import event
from sqlalchemy.dialects import mysql

from app.ai import surgery_facts as facts
from app.ai.surgery_models import AISurgeryPool, AISurgeryProtectedWitness, AISurgerySource
from app.models import Admission, Department, Doctor, Equipment, SurgeryApplication, SurgerySchedule, User

NOTE = "隔离合成手术工程原件，明确记录实际来源和缺项，全部专业及运营声明仅用于测试，不代表医院验证或真实人员资质。"
NOW = datetime.datetime(2026, 10, 20, 12, 0, 0, 123456)


def registry(db, actor, payload, *, publish=True):
    row = facts.create_registry(db, actor, payload["kind"], {"payload": payload})
    db.commit()
    if publish and hasattr(row, "status"):
        facts.review_registry(
            db, actor, payload["kind"], getattr(row, facts.REGISTRY[payload["kind"]][1]), {"expected_revision": 1, "expected_content_hash": row.content_hash, "decision": "publish", "basis_note": NOTE}
        )
        db.commit()
    return row


@pytest.fixture
def surgery_case(seed_data, db_session, monkeypatch):
    monkeypatch.setattr(facts, "utcnow", lambda: NOW)
    suffix = uuid.uuid4().hex[:10]
    department = Department(name="合成手术科" + suffix)
    foreign = Department(name="合成外科域" + suffix)
    doctor_user = User(username="sdoc" + suffix, password=seed_data["admin_user"].password, user_role="doctor")
    foreign_user = User(username="sdir" + suffix, password=seed_data["admin_user"].password, user_role="director")
    db_session.add_all([department, foreign, doctor_user, foreign_user])
    db_session.flush()
    doctor = Doctor(name="合成手术医师", department_id=department.department_id, user_id=doctor_user.user_id, permission="doctor")
    director = Doctor(name="合成手术主任", department_id=department.department_id, user_id=seed_data["director_user"].user_id, permission="director")
    outsider = Doctor(name="合成域外主任", department_id=foreign.department_id, user_id=foreign_user.user_id, permission="director")
    equipment = Equipment(asset_no="synth-" + suffix, name="合成设备", department_id=department.department_id, status=0, create_time=NOW)
    db_session.add_all([doctor, director, outsider, equipment])
    db_session.flush()
    patient = seed_data["patient"]
    admission = Admission(admission_id=str(uuid.uuid4()), patient_id=patient.patient_id, doctor_id=doctor.doctor_id, department_id=department.department_id, status=1, admission_time=NOW)
    application = SurgeryApplication(
        application_id=str(uuid.uuid4()),
        patient_id=patient.patient_id,
        admission_id=admission.admission_id,
        doctor_id=doctor.doctor_id,
        surgery_name="合成手术",
        scheduled_date=datetime.date(2026, 10, 21),
        status=1,
        create_time=NOW,
    )
    db_session.add_all([admission, application])
    db_session.commit()
    super_user = seed_data["super_admin_user"]
    pool = registry(db_session, super_user, {"kind": "pool", "department_id": department.department_id, "name": "合成受控手术池", "basis_note": NOTE})
    resources = {}
    for kind in ("room", "person", "equipment"):
        resources[kind] = registry(
            db_session,
            super_user,
            {
                "kind": "resource",
                "resource_kind": kind,
                "equipment_id": equipment.equipment_id if kind == "equipment" else None,
                "cssd_instrument_id": None,
                "label": "合成" + kind,
                "basis_note": NOTE,
            },
        )
        registry(db_session, super_user, {"kind": "pool_membership", "pool_id": pool.pool_id, "resource_id": resources[kind].resource_id, "basis_note": NOTE})
    registry(db_session, super_user, {"kind": "person_account", "resource_id": resources["person"].resource_id, "user_id": doctor_user.user_id, "basis_note": NOTE})
    return {
        "seed": seed_data,
        "super": super_user,
        "director": seed_data["director_user"],
        "doctor_user": doctor_user,
        "doctor": doctor,
        "director_doctor": director,
        "foreign_user": foreign_user,
        "foreign": foreign,
        "department": department,
        "pool": pool,
        "resources": resources,
        "equipment": equipment,
        "patient": patient,
        "admission": admission,
        "application": application,
    }


def amount(value=None, reason="unknown"):
    return {"value": value, "absent_reason": None if value is not None else reason}


def unknown_time():
    return {"kind": "unknown", "basis_note": NOTE}


def accounting():
    return {"counted_as_work": True, "absent_reason": None, "breaks": [], "breaks_complete": True, "time_accounting_status": "verified"}


def payload(kind, case):
    if kind == "case_duration_estimate":
        return {
            "kind": kind,
            "method": "reviewed_case_estimate",
            "semantics": "declared_upper_bounds",
            "segments": [{"segment_id": "operative", "start_offset_us": amount("0"), "end_offset_us": amount(None), "basis_note": NOTE}],
            "basis_note": NOTE,
        }
    if kind == "duration_observation":
        return {
            "kind": kind,
            "observed_start_at": "2026-10-19T09:00:00.000000Z",
            "observed_end_at": "2026-10-19T10:00:00.000000Z",
            "observed_at": "2026-10-19T11:00:00.000000Z",
            "legacy_schedule_id": None,
            "clock_interpretation": "explicit_original_utc",
            "basis_note": NOTE,
        }
    if kind == "case_requirements":
        occupation = {
            "segment_ids": ["operative"],
            "occupation_mode": "segments",
            "transition_class_key": None,
            "transition_class_absent_reason": "unknown",
            "counted_as_work": None,
            "counted_as_work_absent_reason": "unknown",
            "basis_note": NOTE,
        }
        return {
            "kind": kind,
            "procedure_group_key": None,
            "procedure_group_absent_reason": "unknown",
            "required": None,
            "required_absent_reason": "unknown",
            "release": unknown_time(),
            "deadline": unknown_time(),
            "patient_segment_ids": ["operative"],
            "patient_occupation_mode": "envelope",
            "room": {"slot_id": "room", "capability_keys": [], "occupation": occupation, "basis_note": NOTE},
            "roles": [],
            "equipment": [],
            "other_requirements_status": "unknown",
            "basis_note": NOTE,
        }
    if kind in {"operating_room_identity_capability", "person_identity_qualification"}:
        result = {"kind": kind, "identity_status": "unknown", "capability_keys": [], "valid_from_at": "2026-10-20T00:00:00.000000Z", "valid_until": unknown_time(), "basis_note": NOTE}
        if kind == "person_identity_qualification":
            result.update(user_id=case["doctor_user"].user_id, doctor_id=case["doctor"].doctor_id, qualification_status="unknown")
        else:
            result.update(capability_status="unknown")
        return result
    if kind == "resource_availability_busy":
        return {"kind": kind, "record_type": "duty", "start_at": "2026-10-20T08:00:00.000000Z", "end_at": "2026-10-20T20:00:00.000000Z", "accounting": accounting(), "basis_note": NOTE}
    if kind == "resource_occupation_policy":
        limit = {"value": None, "unit": "min", "absent_reason": "unknown"}
        return {
            "kind": kind,
            "policy_type": "work",
            "effective_from_at": "2026-10-20T00:00:00.000000Z",
            "effective_until": unknown_time(),
            "max_single_presence": limit,
            "max_work_rolling_24h": limit,
            "max_work_rolling_7d": limit,
            "minimum_rest": {"value": "0", "unit": "min", "absent_reason": None},
            "fixed_windows": [],
            "policy_reference": NOTE,
            "basis_note": NOTE,
        }
    raise AssertionError(kind)


def request(case, kind="case_duration_estimate", *, confirmed=True):
    clinical = kind in facts.CASE_KINDS
    resource_kind = "room" if kind == "operating_room_identity_capability" else "person"
    return {
        "pool_id": case["pool"].pool_id,
        "resource_id": None if clinical else case["resources"][resource_kind].resource_id,
        "application_id": case["application"].application_id if clinical else None,
        "payload": payload(kind, case),
        "professional_attestation": {
            "status": "confirmed" if clinical and confirmed else "unknown",
            "signer_doctor_id": case["doctor"].doctor_id if clinical and confirmed else None,
            "basis_note": NOTE if clinical and confirmed else None,
        },
    }


def create(db, case, kind="case_duration_estimate", actor=None, **kwargs):
    actor = actor or (case["doctor_user"] if kind in facts.CASE_KINDS else case["director"])
    row = facts.create_source(db, actor, kind, request(case, kind, **kwargs))
    db.commit()
    return row


def publish(db, case, row, decision="publish"):
    facts.review_source(db, case["super"], row.source_kind, row.source_record_id, {"expected_revision": 1, "expected_content_hash": row.content_hash, "decision": decision, "basis_note": NOTE})
    db.commit()
    return row


@pytest.mark.parametrize("kind", list(facts.SOURCE_KINDS))
def test_all_seven_actual_immutable_originals_preserve_unknown_and_separate_review(db_session, surgery_case, kind):
    case = surgery_case
    row = create(db_session, case, kind)
    before = row.payload_json, row.parent_binding_json, row.content_hash
    original, _ = facts.source_proof(row)
    assert facts.hash_content(original) == row.content_hash
    publish(db_session, case, row)
    actor = case["doctor_user"] if kind in facts.CASE_KINDS else case["director"]
    data = facts.source_current(db_session, actor, kind, row.source_record_id)
    assert data["eligible_for_new_use"] is True and data["revision"] == 2 and data["payload"] == payload(kind, case)
    assert (row.payload_json, row.parent_binding_json, row.content_hash) == before
    if kind in facts.CASE_KINDS:
        assert row.signed_by_user_id == case["doctor_user"].user_id and row.reviewed_by == case["super"].user_id
        assert row.signed_at == row.recorded_at == NOW
    else:
        assert row.professional_status == "unknown" and row.signed_by_doctor_id is None


def test_super_publication_does_not_create_clinical_signature_or_grant_doctor_ops(db_session, surgery_case):
    case = surgery_case
    data = request(case)
    with pytest.raises(HTTPException) as error:
        facts.create_source(db_session, case["super"], "case_duration_estimate", data)
    assert error.value.status_code == 403
    db_session.rollback()
    row = create(db_session, case, actor=case["super"], confirmed=False)
    publish(db_session, case, row)
    assert row.professional_status == "unknown" and row.signed_by_user_id is None
    with pytest.raises(HTTPException) as error:
        create(db_session, case, "resource_availability_busy", actor=case["doctor_user"])
    assert error.value.status_code == 403
    db_session.rollback()


def test_own_pool_is_not_foreign_patient_care_and_cross_admission_is_rejected(db_session, surgery_case):
    case = surgery_case
    # An explicit pool membership alone cannot confer a physician's patient care.
    new_user = User(username="no-care-" + uuid.uuid4().hex[:8], password=case["doctor_user"].password, user_role="doctor")
    db_session.add(new_user)
    db_session.flush()
    other = Doctor(name="同池无照护医师", department_id=case["department"].department_id, user_id=new_user.user_id)
    db_session.add(other)
    db_session.commit()
    data = request(case)
    data["professional_attestation"]["signer_doctor_id"] = other.doctor_id
    with pytest.raises(HTTPException) as error:
        facts.create_source(db_session, new_user, "case_duration_estimate", data)
    assert error.value.status_code == 403
    db_session.rollback()
    case["admission"].patient_id = case["seed"]["patient2"].patient_id
    db_session.commit()
    with pytest.raises(HTTPException) as error:
        create(db_session, case)
    assert error.value.status_code == 409
    db_session.rollback()


def test_current_parent_change_redacts_ordinary_full_original_but_not_super_audit_or_revoke(db_session, surgery_case):
    case = surgery_case
    row = publish(db_session, case, create(db_session, case))
    before = facts.source_proof(row)[0]
    case["application"].surgery_name = "真实父件更改后的合成手术名"
    db_session.commit()
    ordinary = facts.source_current(db_session, case["doctor_user"], row.source_kind, row.source_record_id)
    assert not ordinary["eligible_for_new_use"] and "original_parent_changed" in ordinary["exclusion_reasons"]
    assert all(ordinary[key] is None for key in ("payload", "parent_binding", "review_basis_note", "revoke_reason"))
    audit = facts.source_current(db_session, case["super"], row.source_kind, row.source_record_id, audit_only=True)
    assert audit["payload"] == before["payload"] and audit["can_revoke"]
    facts.review_source(db_session, case["super"], row.source_kind, row.source_record_id, {"expected_revision": 2, "expected_content_hash": row.content_hash, "basis_note": NOTE}, revoke=True)
    db_session.commit()
    assert facts.source_proof(row)[0] == before and row.revision == 3


def test_bad_own_body_hash_is_never_a_super_frozen_original(db_session, surgery_case):
    row = create(db_session, surgery_case)
    row.payload_json = row.payload_json.replace("declared_upper_bounds", "unknown")
    db_session.commit()
    with pytest.raises(HTTPException) as error:
        facts.source_current(db_session, surgery_case["super"], row.source_kind, row.source_record_id, audit_only=True)
    assert error.value.status_code == 409


@pytest.mark.parametrize("wrong", [True, 1.0, "1"])
def test_registry_real_parent_ids_are_strict_and_do_not_coerce(wrong):
    with pytest.raises(ValidationError):
        facts.RegistryCreate(payload={"kind": "pool", "department_id": wrong, "name": "测试", "basis_note": NOTE})


@pytest.mark.parametrize("replacement", ["2026-10-20T08:00:00Z", "2026-10-20T08:00:00.000000+00:00", "2026-02-30T08:00:00.000000Z"])
def test_exact_utc_originals_reject_missing_precision_offsets_and_invalid_dates(replacement, surgery_case):
    values = request(surgery_case, "resource_availability_busy")
    values["payload"]["start_at"] = replacement
    with pytest.raises(ValidationError):
        facts.SourceCreate.model_validate(values)


def test_capability_raw_keys_and_explicit_zero_null_are_not_changed(surgery_case):
    values = request(surgery_case, "case_duration_estimate")
    result = facts.SourceCreate.model_validate(values).model_dump(mode="json")
    assert result["payload"]["segments"][0]["start_offset_us"] == amount("0")
    assert result["payload"]["segments"][0]["end_offset_us"] == amount(None)
    bad = copy.deepcopy(values)
    bad["payload"]["segments"][0]["end_offset_us"] = amount(1.5)
    with pytest.raises(ValidationError):
        facts.SourceCreate.model_validate(bad)


def test_locking_reads_use_current_for_update_without_claiming_sqlite_row_locks(db_session, surgery_case):
    pool_id = surgery_case["pool"].pool_id
    statements = []

    def capture(orm_state):
        if orm_state.is_select:
            statements.append(str(orm_state.statement.compile(dialect=mysql.dialect())))

    event.listen(db_session, "do_orm_execute", capture)
    try:
        facts.current_actor(db_session, surgery_case["super"], locking=True)
        facts.pool_scope(db_session, surgery_case["super"], pool_id, locking=True)
    finally:
        event.remove(db_session, "do_orm_execute", capture)
    assert statements and all("FOR UPDATE" in statement for statement in statements)


def test_no_surgery_execution_or_resource_maintenance_side_effects(db_session, surgery_case):
    case = surgery_case
    old_count = db_session.query(SurgerySchedule).count()
    old_state = case["application"].status, case["admission"].status, case["equipment"].status
    row = publish(db_session, case, create(db_session, case))
    facts.review_source(db_session, case["doctor_user"], row.source_kind, row.source_record_id, {"expected_revision": 2, "expected_content_hash": row.content_hash, "basis_note": NOTE}, revoke=True)
    db_session.commit()
    assert db_session.query(SurgerySchedule).count() == old_count
    assert old_state == (case["application"].status, case["admission"].status, case["equipment"].status)
    assert db_session.query(AISurgerySource).filter_by(source_record_id=row.source_record_id).one().revision == 3
    assert db_session.query(AISurgeryPool).filter_by(pool_id=case["pool"].pool_id).one().status == "published"
    assert json.loads(row.parent_binding_json)["professional_signature"]["basis_note"] == NOTE


def protected_request(db, case, *, foreign_pool=False, status=2, end=True):
    person = db.query(Doctor).filter_by(user_id=case["foreign_user"].user_id).one()
    admission = Admission(
        admission_id=str(uuid.uuid4()), patient_id=case["seed"]["patient2"].patient_id, doctor_id=person.doctor_id, department_id=case["foreign"].department_id, status=1, admission_time=NOW
    )
    application = SurgeryApplication(
        application_id=str(uuid.uuid4()),
        patient_id=admission.patient_id,
        admission_id=admission.admission_id,
        doctor_id=person.doctor_id,
        surgery_name="禁止进入跨科胶囊的患者临床术名",
        preop_diagnosis="禁止进入跨科胶囊的临床诊断",
        status=1,
        create_time=NOW,
    )
    schedule = SurgerySchedule(
        schedule_id=str(uuid.uuid4()),
        application_id=application.application_id,
        patient_id=admission.patient_id,
        operating_room="原外科自由房间名",
        surgeon_id=case["doctor"].doctor_id,
        surgery_date=datetime.date(2026, 10, 19),
        start_time=datetime.datetime(2026, 10, 19, 9),
        end_time=datetime.datetime(2026, 10, 19, 10) if end else None,
        status=status,
        create_time=NOW,
    )
    db.add_all([admission, application, schedule])
    db.commit()
    pool = case["pool"]
    if foreign_pool:
        pool = registry(db, case["super"], {"kind": "pool", "department_id": case["foreign"].department_id, "name": "合成域外手术资源池", "basis_note": NOTE})
        registry(db, case["super"], {"kind": "pool_membership", "pool_id": pool.pool_id, "resource_id": case["resources"]["person"].resource_id, "basis_note": NOTE})
    req = {
        "pool_id": pool.pool_id,
        "resource_id": case["resources"]["person"].resource_id,
        "legacy_schedule_id": schedule.schedule_id,
        "participant_kind": "surgeon",
        "assistant_doctor_id": None,
        "room_alias_id": None,
        "start_at": "2026-10-19T09:00:00.000000Z",
        "end_at": "2026-10-19T10:00:00.000000Z" if end else None,
        "end_absent_reason": None if end else "ongoing_unknown_end",
        "verified_until_at": "2026-10-19T10:00:00.000000Z",
        "continuity_status": "unknown",
        "transition_class_key": None,
        "transition_class_absent_reason": "unknown",
        "accounting": accounting(),
        "clock_basis_note": NOTE,
    }
    return req, schedule


def test_actual_foreign_raw_capsule_has_own_safe_hash_and_no_foreign_clinical_identity(db_session, surgery_case):
    case = surgery_case
    req, schedule = protected_request(db_session, case, foreign_pool=True)
    with pytest.raises(HTTPException) as error:
        facts.create_protected_capsule(db_session, case["director"], req)
    assert error.value.status_code == 403
    db_session.rollback()
    row = facts.create_protected_capsule(db_session, case["super"], req)
    db_session.commit()
    publish(db_session, case, row)
    # The ordinary original-source endpoint keeps its original-pool boundary.
    with pytest.raises(HTTPException) as error:
        facts.source_current(db_session, case["director"], row.source_kind, row.source_record_id)
    assert error.value.status_code == 403
    safe = facts.safe_resource_busy_current(db_session, case["director"], req["resource_id"], row.source_record_id, case["pool"].pool_id)
    assert safe["eligible_for_new_use"] and facts.hash_content({key: value for key, value in safe.items() if key != "capsule_hash"}) == safe["capsule_hash"]
    assert not any(
        word in facts.canonical_json(safe)
        for word in ("patient_id", "admission_id", "application_id", "department_id", "pool_id", "basis_note", "clock_basis_note", schedule.schedule_id, "临床诊断", "临床术名", "原外科自由房间名")
    )
    assert safe["payload"]["continuity_status"] == "unknown"
    witness = db_session.query(AISurgeryProtectedWitness).filter_by(source_record_id=row.source_record_id).one()
    assert schedule.schedule_id in witness.witness_json and witness.content_hash == safe["payload"]["protected_witness_hash"]
    schedule.end_time = datetime.datetime(2026, 10, 19, 11)
    db_session.commit()
    changed = facts.safe_resource_busy_current(db_session, case["director"], req["resource_id"], row.source_record_id, case["pool"].pool_id)
    assert not changed["eligible_for_new_use"] and "protected_original_changed" in changed["exclusion_reasons"]


def test_cancelled_running_raw_record_cannot_release_resource_without_actual_end(db_session, surgery_case):
    case = surgery_case
    req, _ = protected_request(db_session, case, status=3, end=False)
    bad = copy.deepcopy(req)
    bad.update(end_at="2026-10-19T10:00:00.000000Z", end_absent_reason=None)
    with pytest.raises(HTTPException) as error:
        facts.create_protected_capsule(db_session, case["super"], bad)
    assert error.value.status_code == 409
    db_session.rollback()
    row = facts.create_protected_capsule(db_session, case["super"], req)
    db_session.commit()
    assert json.loads(row.payload_json)["end_at"] is None and json.loads(row.payload_json)["busy_status"] == "unknown"


def test_caller_cannot_forge_raw_witness_or_add_phi_to_safe_capsule(db_session, surgery_case):
    case = surgery_case
    req, _ = protected_request(db_session, case)
    row = facts.create_protected_capsule(db_session, case["super"], req)
    db_session.commit()
    values = request(case, "resource_availability_busy")
    values["payload"] = json.loads(row.payload_json)
    with pytest.raises(HTTPException) as error:
        facts.create_source(db_session, case["director"], "resource_availability_busy", values)
    assert error.value.status_code == 422
    db_session.rollback()
    values["payload"]["patient_id"] = 123
    with pytest.raises(ValidationError):
        facts.SourceCreate.model_validate(values)
    witness = db_session.query(AISurgeryProtectedWitness).filter_by(source_record_id=row.source_record_id).one()
    witness.witness_json = witness.witness_json.replace("2026-10-19T09:00:00.000000Z", "2026-10-19T08:00:00.000000Z")
    db_session.commit()
    with pytest.raises(HTTPException) as error:
        facts.source_current(db_session, case["super"], row.source_kind, row.source_record_id, audit_only=True)
    assert error.value.status_code == 409


def test_legacy_room_requires_own_explicit_alias_and_does_not_guess_namespace(db_session, surgery_case):
    case = surgery_case
    req, schedule = protected_request(db_session, case)
    req.update(resource_id=case["resources"]["room"].resource_id, participant_kind="room")
    alias = registry(
        db_session,
        case["super"],
        {
            "kind": "room_alias",
            "resource_id": req["resource_id"],
            "alias_scope": "namespace",
            "alias_namespace": "synthetic-campus",
            "legacy_schedule_id": None,
            "raw_original_text": schedule.operating_room,
            "basis_note": NOTE,
        },
    )
    req["room_alias_id"] = alias.alias_id
    with pytest.raises(HTTPException) as error:
        facts.create_protected_capsule(db_session, case["super"], req)
    assert error.value.status_code == 409
    db_session.rollback()
    alias = registry(
        db_session,
        case["super"],
        {
            "kind": "room_alias",
            "resource_id": req["resource_id"],
            "alias_scope": "legacy_schedule",
            "alias_namespace": None,
            "legacy_schedule_id": schedule.schedule_id,
            "raw_original_text": schedule.operating_room,
            "basis_note": NOTE,
        },
    )
    req["room_alias_id"] = alias.alias_id
    row = facts.create_protected_capsule(db_session, case["super"], req)
    db_session.commit()
    assert row.resource_id == req["resource_id"]


def test_protected_capsule_keeps_actual_user_natural_person_across_doctor_aliases(db_session, surgery_case):
    case = surgery_case
    req, schedule = protected_request(db_session, case)
    alias = Doctor(name="同账户另一个医师别名", department_id=case["foreign"].department_id, user_id=case["doctor_user"].user_id)
    db_session.add(alias)
    db_session.flush()
    schedule.surgeon_id = alias.doctor_id
    db_session.commit()
    row = facts.create_protected_capsule(db_session, case["super"], req)
    db_session.commit()
    assert row.resource_id == case["resources"]["person"].resource_id


@pytest.mark.parametrize("start,end", [("0", "0"), ("2", "1")])
def test_zero_and_reversed_declared_stage_originals_are_preserved_for_math_not_repaired(db_session, surgery_case, start, end):
    case = surgery_case
    values = request(case)
    values["payload"]["segments"][0].update(start_offset_us=amount(start), end_offset_us=amount(end))
    row = facts.create_source(db_session, case["doctor_user"], "case_duration_estimate", values)
    db_session.commit()
    publish(db_session, case, row)
    original = facts.source_current(db_session, case["doctor_user"], row.source_kind, row.source_record_id)["payload"]["segments"][0]
    assert original["start_offset_us"] == amount(start) and original["end_offset_us"] == amount(end)


def test_changed_patient_scope_does_not_grant_old_original_through_new_patient_care(db_session, surgery_case):
    case = surgery_case
    row = publish(db_session, case, create(db_session, case))
    new_admission = Admission(
        admission_id=str(uuid.uuid4()), patient_id=case["seed"]["patient2"].patient_id, doctor_id=case["doctor"].doctor_id, department_id=case["department"].department_id, status=1, admission_time=NOW
    )
    db_session.add(new_admission)
    db_session.flush()
    case["application"].patient_id, case["application"].admission_id = new_admission.patient_id, new_admission.admission_id
    db_session.commit()
    with pytest.raises(HTTPException) as error:
        facts.source_current(db_session, case["doctor_user"], row.source_kind, row.source_record_id)
    assert error.value.status_code == 403
    audit = facts.source_current(db_session, case["super"], row.source_kind, row.source_record_id, audit_only=True)
    assert audit["patient_id"] == case["patient"].patient_id and not audit["eligible_for_new_use"] and audit["payload"] is not None


def test_publication_after_asof_is_not_historical_available_evidence(db_session, surgery_case, monkeypatch):
    case = surgery_case
    row = create(db_session, case)
    monkeypatch.setattr(facts, "utcnow", lambda: NOW + datetime.timedelta(seconds=1))
    publish(db_session, case, row)
    unavailable = facts.source_current(db_session, case["doctor_user"], row.source_kind, row.source_record_id, as_of=facts.utc_text(NOW))
    assert not unavailable["eligible_for_new_use"] and "original_not_available_at_as_of" in unavailable["exclusion_reasons"]
    assert facts.source_current(db_session, case["doctor_user"], row.source_kind, row.source_record_id, as_of=facts.utc_text(NOW + datetime.timedelta(seconds=1)))["eligible_for_new_use"]


def test_utf8_review_cap_is_bytes_and_not_character_count():
    with pytest.raises(ValidationError):
        facts.SourceReview(expected_revision=1, expected_content_hash="a" * 64, decision="publish", basis_note="合" * 1400)
    assert facts.SourceReview(expected_revision=1, expected_content_hash="a" * 64, decision="publish", basis_note="x" * 4000).basis_note == "x" * 4000
