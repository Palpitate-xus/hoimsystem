"""Patient scope tests exercise SQL execution, flushes and HTTP boundaries."""

import uuid

import pytest
from fastapi import Depends, FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy import insert, select, text, update
from sqlalchemy.orm import Session, aliased, joinedload

from app.access_scope import apply_patient_scope
from app.ai.models import AIFeedback, AIRun
from app.models import Admission, Appointment, Doctor, FamilyMember, MedicalRecord, Patient, PrePha, Prescription, Registration, User


@pytest.fixture
def care(db_session):
    suffix = uuid.uuid4().hex[:10]
    owner = User(username=f"scope{suffix}", user_role="doctor")
    other_user = User(username=f"other{suffix}", user_role="doctor")
    db_session.add_all([owner, other_user])
    db_session.flush()
    doctor = Doctor(name="本医生", user_id=owner.user_id)
    other_doctor = Doctor(name="其他医生", user_id=other_user.user_id)
    own = Patient(name="负责患者", identity=f"own{suffix}")
    other = Patient(name="范围外患者", identity=f"other{suffix}")
    db_session.add_all([doctor, other_doctor, own, other])
    db_session.flush()
    rx = Prescription(patient_id=own.patient_id, doctor_id=doctor.doctor_id)
    other_rx = Prescription(patient_id=other.patient_id, doctor_id=other_doctor.doctor_id)
    own_record = MedicalRecord(patient_id=own.patient_id, doctor_id=doctor.doctor_id, symptom="本病例")
    other_record = MedicalRecord(patient_id=other.patient_id, doctor_id=other_doctor.doctor_id, symptom="范围外病例")
    db_session.add_all([rx, other_rx, own_record, other_record])
    db_session.flush()
    line = PrePha(prescription_id=rx.prescription_id, number=1)
    other_line = PrePha(prescription_id=other_rx.prescription_id, number=2)
    db_session.add_all([line, other_line])
    db_session.commit()
    # Freeze identifiers before scope binding expires previously loaded PHI.
    values = dict(
        user_id=owner.user_id, doctor_id=doctor.doctor_id, other_doctor_id=other_doctor.doctor_id,
        patient_id=own.patient_id, other_id=other.patient_id, rx_id=rx.prescription_id, other_rx_id=other_rx.prescription_id,
        record_id=own_record.medical_record_id, other_record_id=other_record.medical_record_id,
        line_id=line.pre_pha_id, other_line_id=other_line.pre_pha_id,
    )
    yield db_session, owner, values
    db_session.rollback()


def _bind(care):
    db, user, ids = care
    apply_patient_scope(db, user, "assigned")
    return db, user, ids


def test_patient_list_projection_alias_detail_and_identity_map_are_scoped(care):
    db, _, ids = _bind(care)
    assert [row.patient_id for row in db.query(Patient).all()] == [ids["patient_id"]]
    assert db.execute(select(Patient.patient_id)).scalars().all() == [ids["patient_id"]]
    patient_alias = aliased(Patient)
    assert db.scalars(select(patient_alias)).one().patient_id == ids["patient_id"]
    assert db.get(Patient, ids["other_id"]) is None
    assert db.get(MedicalRecord, ids["other_record_id"]) is None


def test_child_without_database_fk_and_eager_relationship_are_scoped(care):
    db, _, ids = _bind(care)
    assert [row.pre_pha_id for row in db.query(PrePha).all()] == [ids["line_id"]]
    prescription = db.query(Prescription).options(joinedload(Prescription.pre_phas)).one()
    assert prescription.prescription_id == ids["rx_id"]
    assert [row.pre_pha_id for row in prescription.pre_phas] == [ids["line_id"]]


@pytest.mark.parametrize("model", [Appointment, Registration, MedicalRecord, Prescription, Admission])
def test_each_real_doctor_care_relation_grants_patient_visibility(care, model):
    db, user, ids = care
    third = Patient(name="新增诊疗患者", identity=uuid.uuid4().hex[:20])
    db.add(third)
    db.flush()
    third_id = third.patient_id
    db.add(model(patient_id=third_id, doctor_id=ids["doctor_id"]))
    db.commit()
    apply_patient_scope(db, user, "assigned")
    assert db.get(Patient, third_id) is not None


def test_missing_doctor_profile_and_director_without_care_are_empty(care):
    db, _, _ = care
    user = User(username=uuid.uuid4().hex[:20], user_role="director")
    db.add(user)
    db.commit()
    apply_patient_scope(db, user, "assigned")
    assert db.query(Patient).count() == 0
    assert db.query(MedicalRecord).count() == 0


def test_patient_and_admin_existing_scope_preserves_current_endpoint_checks(care):
    db, _, ids = care
    for role in ("patient", "admin", "super_admin"):
        user = User(user_id=-1, user_role=role)
        apply_patient_scope(db, user, "existing")
        assert db.get(Patient, ids["other_id"]) is not None
        with pytest.raises(HTTPException):
            apply_patient_scope(db, user, "assigned")


def test_scoped_session_cannot_be_widened_or_rebound_and_does_not_leak(care):
    db, user, ids = _bind(care)
    apply_patient_scope(db, user, "existing")
    assert db.get(Patient, ids["other_id"]) is None
    with pytest.raises(HTTPException):
        apply_patient_scope(db, User(user_id=user.user_id + 1, user_role="doctor"), "assigned")
    with Session(db.bind) as independent:
        assert independent.get(Patient, ids["other_id"]) is not None
        other_user = independent.get(User, independent.get(Doctor, ids["other_doctor_id"]).user_id)
        apply_patient_scope(independent, other_user, "assigned")
        assert independent.get(Patient, ids["other_id"]) is not None
        assert independent.get(Patient, ids["patient_id"]) is None


def _run(user_id, patient_id=None):
    return AIRun(feature_key="clinical_training", requested_by=user_id, patient_id=patient_id, prompt_hash="a" * 64, context_digest="b" * 64)


def test_unbound_ai_runs_and_their_children_remain_available(care):
    db, user, ids = _bind(care)
    unbound = _run(user.user_id)
    own = _run(user.user_id, ids["patient_id"])
    db.add_all([unbound, own])
    db.flush()
    feedback = AIFeedback(run_id=unbound.run_id, reviewer_id=user.user_id, outcome="accepted")
    db.add(feedback)
    db.flush()
    run_id, feedback_id = unbound.run_id, feedback.feedback_id
    db.expire_all()
    assert db.get(AIRun, run_id).patient_id is None
    assert db.get(AIFeedback, feedback_id).run_id == run_id
    assert db.query(AIRun).count() == 2


def test_patient_bound_ai_run_cannot_be_unbound(care):
    db, user, ids = _bind(care)
    run = _run(user.user_id, ids["patient_id"])
    db.add(run)
    db.flush()
    run.patient_id = None
    with pytest.raises(HTTPException):
        db.flush()


def test_preloaded_worker_run_stays_attached_and_persists_after_scope_binding(care):
    db, user, ids = care
    run = _run(user.user_id, ids["patient_id"])
    db.add(run)
    db.commit()
    run_id = run.run_id
    apply_patient_scope(db, user, "assigned")
    run.status = "completed"
    db.commit()
    with Session(db.bind) as independent:
        assert independent.get(AIRun, run_id).status == "completed"


def test_expired_identity_cannot_reload_after_care_relation_is_revoked(care):
    db, _, ids = _bind(care)
    patient = db.get(Patient, ids["patient_id"])
    with Session(db.bind) as independent:
        independent.query(MedicalRecord).filter(MedicalRecord.patient_id == ids["patient_id"]).delete()
        independent.query(Prescription).filter(Prescription.patient_id == ids["patient_id"]).delete()
        independent.commit()
    db.expire(patient)
    assert db.get(Patient, ids["patient_id"]) is None


def test_ai_child_cannot_use_an_out_of_scope_parent(care):
    db, user, ids = care
    foreign = _run(user.user_id, ids["other_id"])
    db.add(foreign)
    db.commit()
    run_id = foreign.run_id
    apply_patient_scope(db, user, "assigned")
    assert db.get(AIRun, run_id) is None
    db.add(AIFeedback(run_id=run_id, reviewer_id=user.user_id, outcome="accepted"))
    with pytest.raises(HTTPException):
        db.flush()


def test_other_nullable_patient_models_still_reject_unbound_rows(care):
    db, user, _ = care
    record = MedicalRecord(patient_id=None, symptom="无患者关联内容")
    db.add(record)
    db.commit()
    record_id = record.medical_record_id
    apply_patient_scope(db, user, "assigned")
    assert db.get(MedicalRecord, record_id) is None
    db.add(MedicalRecord(patient_id=None, symptom="无患者关联内容"))
    with pytest.raises(HTTPException):
        db.flush()


def test_nonpatient_models_remain_available_for_queries_and_writes(care):
    db, user, _ = _bind(care)
    assert db.get(User, user.user_id) is not None
    username = uuid.uuid4().hex[:20]
    db.execute(insert(User).values(username=username, user_role="doctor"))
    db.bulk_insert_mappings(User, [{"username": uuid.uuid4().hex[:20], "user_role": "doctor"}])
    assert db.query(User).filter(User.username == username).one().user_role == "doctor"


@pytest.mark.parametrize("mode", ["text", "core_read", "core_update", "mixed_core_read", "orm_from_text", "orm_insert", "bulk_insert", "bulk_update", "bulk_save"])
def test_unguarded_statement_and_bulk_helpers_are_rejected(care, mode):
    db, _, ids = _bind(care)
    operations = {
        "text": lambda: db.execute(text("SELECT * FROM hoimsystem_patient")),
        "core_read": lambda: db.execute(select(Patient.__table__)),
        "core_update": lambda: db.execute(update(Patient.__table__).values(name="越权")),
        "mixed_core_read": lambda: db.execute(select(User, Patient.__table__.c.name)),
        "orm_from_text": lambda: db.execute(select(Patient).from_statement(text("SELECT * FROM hoimsystem_patient"))),
        "orm_insert": lambda: db.execute(insert(MedicalRecord).values(patient_id=ids["other_id"])),
        "bulk_insert": lambda: db.bulk_insert_mappings(MedicalRecord, [{"patient_id": ids["other_id"]}]),
        "bulk_update": lambda: db.bulk_update_mappings(MedicalRecord, [{"medical_record_id": ids["other_record_id"], "symptom": "越权"}]),
        "bulk_save": lambda: db.bulk_save_objects([MedicalRecord(patient_id=ids["other_id"])]),
    }
    with pytest.raises(HTTPException) as denied:
        operations[mode]()
    assert denied.value.status_code == 403


def test_orm_bulk_update_and_delete_only_affect_assigned_rows(care):
    db, _, ids = _bind(care)
    assert db.query(MedicalRecord).update({MedicalRecord.symptom: "已更新"}, synchronize_session=False) == 1
    assert db.get(MedicalRecord, ids["record_id"]).symptom == "已更新"
    assert db.query(PrePha).delete(synchronize_session=False) == 1
    db.commit()
    with Session(db.bind) as independent:
        assert independent.get(MedicalRecord, ids["other_record_id"]).symptom == "范围外病例"
        assert independent.get(PrePha, ids["other_line_id"]) is not None


@pytest.mark.parametrize("column", ["patient_id", "medical_record_id", "ordered_patient_id"])
def test_bulk_update_cannot_move_ownership(care, column):
    db, _, ids = _bind(care)
    with pytest.raises(HTTPException):
        if column == "ordered_patient_id":
            db.execute(update(MedicalRecord).ordered_values((MedicalRecord.patient_id, ids["other_id"])))
        else:
            db.execute(update(MedicalRecord).values({column: ids["other_id"] if column == "patient_id" else "replacement"}))


@pytest.mark.parametrize("target", ["record", "child"])
def test_flush_cannot_insert_outside_scope_or_self_assign_foreign_patient(care, target):
    db, _, ids = _bind(care)
    instance = (MedicalRecord(patient_id=ids["other_id"], doctor_id=ids["doctor_id"]) if target == "record"
                else PrePha(prescription_id=ids["other_rx_id"], number=9))
    db.add(instance)
    with pytest.raises(HTTPException) as denied:
        db.flush()
    assert denied.value.status_code == 403


def test_flush_cannot_reassign_existing_patient_reference(care):
    db, _, ids = _bind(care)
    record = db.get(MedicalRecord, ids["record_id"])
    assert record.patient.patient_id == ids["patient_id"]
    record.patient_id = ids["other_id"]
    with pytest.raises(HTTPException):
        db.flush()


def test_new_parent_and_child_relationships_are_validated_before_fk_sync(care):
    db, _, ids = _bind(care)
    patient = db.get(Patient, ids["patient_id"])
    prescription = Prescription(patient=patient, doctor_id=ids["doctor_id"])
    line = PrePha(prescription=prescription, number=3)
    db.add_all([prescription, line])
    db.flush()
    assert prescription.patient_id == ids["patient_id"]
    assert line.prescription_id == prescription.prescription_id


def test_family_links_cannot_expose_outside_patient(care):
    import datetime

    db, _, ids = care
    db.add(FamilyMember(owner_patient_id=ids["patient_id"], member_patient_id=ids["other_id"], relation="配偶", create_time=datetime.datetime.now(), update_time=datetime.datetime.now()))
    db.commit()
    db, _, _ = _bind(care)
    assert db.query(FamilyMember).count() == 0


def test_binding_clears_cascading_identity_map_without_reusing_loaded_phi(care):
    import datetime

    db, user, ids = care
    family = FamilyMember(owner_patient_id=ids["patient_id"], member_patient_id=ids["other_id"], relation="配偶", create_time=datetime.datetime.now(), update_time=datetime.datetime.now())
    db.add(family)
    db.commit()
    owner = db.get(Patient, ids["patient_id"])
    assert owner.family_members == [family]
    family_id = family.family_member_id
    apply_patient_scope(db, user, "assigned")
    assert db.get(FamilyMember, family_id) is None
    assert db.get(Patient, ids["other_id"]) is None


@pytest.mark.asyncio
async def test_http_lists_details_exports_and_writes_share_enforced_scope(care):
    db, owner, ids = care
    web = FastAPI()

    def scoped_session():
        apply_patient_scope(db, owner, "assigned")
        return db

    @web.get("/patients")
    def patients(session=Depends(scoped_session)):
        return session.execute(select(Patient.patient_id)).scalars().all()

    @web.get("/patients/{patient_id}")
    def detail(patient_id: int, session=Depends(scoped_session)):
        patient = session.get(Patient, patient_id)
        if patient is None:
            raise HTTPException(404, "患者不存在")
        return {"patient_id": patient.patient_id}

    @web.get("/export")
    def export(session=Depends(scoped_session)):
        return [row.symptom for row in session.query(MedicalRecord).all()]

    @web.post("/patients/{patient_id}")
    def write(patient_id: int, session=Depends(scoped_session)):
        session.add(MedicalRecord(patient_id=patient_id, doctor_id=ids["doctor_id"]))
        session.flush()
        return {"saved": True}

    async with AsyncClient(transport=ASGITransport(app=web), base_url="http://test") as client:
        assert (await client.get("/patients")).json() == [ids["patient_id"]]
        assert (await client.get(f"/patients/{ids['other_id']}")).status_code == 404
        assert (await client.get("/export")).json() == ["本病例"]
        assert (await client.post(f"/patients/{ids['other_id']}")).status_code == 403
        db.rollback()
        assert (await client.post(f"/patients/{ids['patient_id']}")).status_code == 200
