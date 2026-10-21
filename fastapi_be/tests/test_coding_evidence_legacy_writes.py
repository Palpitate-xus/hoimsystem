"""Actual legacy writes share the coding Gate without changing grouping rules."""

import datetime
import uuid
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import event, inspect, update
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Session

from app.models import (
    Admission,
    DrgGrouping,
    DrgRule,
    HomeIcdBinding,
    Icd10Diagnosis,
    Icd10Operation,
    MedicalRecordArchive,
    MedicalRecordHome,
    User,
)
from app.routers import home_icd, icd10, insurance, medical_record_archive, medical_record_home
from app.schemas import (
    Icd10CreateRequest,
    Icd10UpdateRequest,
    MedicalRecordArchiveActionRequest,
    MedicalRecordHomeCreateRequest,
    MedicalRecordHomeUpdateRequest,
)


@pytest.fixture
def coding_case(db_session, seed_data):
    db = db_session
    now = datetime.datetime(2026, 10, 21, 12, 0)
    admission = Admission(
        patient_id=seed_data["patient"].patient_id,
        doctor_id=seed_data["doctor"].doctor_id,
        department_id=seed_data["department"].department_id,
        status=2,
        admission_time=now,
        create_time=now,
    )
    db.add(admission)
    db.flush()
    home = MedicalRecordHome(
        admission_id=admission.admission_id,
        patient_id=admission.patient_id,
        doctor_id=admission.doctor_id,
        admission_diagnosis="合成入院原诊断",
        discharge_diagnosis="合成出院原诊断",
        total_fee=Decimal("80"),
        status=0,
        creator_id=seed_data["doctor_user"].user_id,
        create_time=now,
        update_time=now,
    )
    db.add(home)
    db.flush()
    code = "S" + uuid.uuid4().hex[:12].upper()
    diagnosis = Icd10Diagnosis(code=code, name="合成字典原名称", status=1, create_time=now, update_time=now)
    operation = Icd10Operation(code=code, name="合成操作原名称", status=1, create_time=now, update_time=now)
    rule = DrgRule(
        payment_method="DRG",
        group_code=code,
        group_name="合成本地前缀规则",
        diagnosis_prefix=code,
        procedure_prefix="",
        expected_amount=Decimal("120"),
        priority=1,
        version="synthetic-v1",
        status=1,
        creator_id=seed_data["admin_user"].user_id,
        create_time=now,
        update_time=now,
    )
    archive = MedicalRecordArchive(
        home_id=home.home_id,
        archive_no="SYN" + uuid.uuid4().hex,
        location="合成位置",
        status=0,
        create_time=now,
        update_time=now,
    )
    db.add_all([diagnosis, operation, rule, archive])
    db.commit()
    return {**seed_data, "home": home, "admission": admission, "diagnosis": diagnosis, "operation": operation, "rule": rule, "archive": archive}


def writers(case):
    h = case["home"].home_id
    return {
        "home_create": (medical_record_home.create_medical_record_home, MedicalRecordHomeCreateRequest(admission_id=case["admission"].admission_id, admission_diagnosis="合成")),
        "home_update": (medical_record_home.update_medical_record_home, MedicalRecordHomeUpdateRequest(home_id=h, complication="不应写入")),
        "home_submit": (medical_record_home.submit_medical_record_home, MedicalRecordHomeUpdateRequest(home_id=h)),
        "home_archive": (medical_record_archive.archive_record, MedicalRecordArchiveActionRequest(archive_id=case["archive"].archive_id)),
        "bind": (home_icd.bind_icd, {"home_id": h, "kind": "diagnosis", "icd_code": case["diagnosis"].code}),
        "unbind": (home_icd.unbind_icd, {"binding_id": -1}),
        "primary": (home_icd.set_primary, {"binding_id": -1}),
        "diagnosis_create": (icd10.create_diagnosis, Icd10CreateRequest(code="NEVER", name="不应写入")),
        "diagnosis_update": (icd10.update_diagnosis, Icd10UpdateRequest(id=case["diagnosis"].diagnosis_id, name="不应写入")),
        "operation_create": (icd10.create_operation, Icd10CreateRequest(code="NEVER", name="不应写入")),
        "operation_update": (icd10.update_operation, Icd10UpdateRequest(id=case["operation"].operation_id, name="不应写入")),
        "manual_group": (insurance.create_drg_group, {"patient_id": case["patient"].patient_id, "group_code": "NEVER", "diagnosis": "不应写入"}),
        "rule": (insurance.save_drg_rule, {"rule_id": case["rule"].rule_id}),
        "auto_group": (insurance.automatic_drg_group, {"home_id": h}),
    }


@pytest.mark.parametrize(
    "writer",
    [
        "home_create",
        "home_update",
        "home_submit",
        "home_archive",
        "bind",
        "unbind",
        "primary",
        "diagnosis_create",
        "diagnosis_update",
        "operation_create",
        "operation_update",
        "manual_group",
        "rule",
        "auto_group",
    ],
)
def test_every_legacy_writer_rechecks_demoted_actor_before_business_reads(db_session, coding_case, writer):
    db = db_session
    call, request = writers(coding_case)[writer]
    actor = coding_case["admin_user"]
    actor_id = actor.user_id
    assert actor.user_role == "admin"
    models = (MedicalRecordHome, HomeIcdBinding, Icd10Diagnosis, Icd10Operation, DrgRule, DrgGrouping, MedicalRecordArchive)
    counts = [db.query(model).count() for model in models]
    with Session(db.get_bind()) as other:
        other.execute(update(User).where(User.user_id == actor_id).values(user_role="patient"))
        other.commit()
    assert actor.user_role == "admin"  # Deliberately stale ORM/JWT-facing object.
    statements = []

    def capture(state):
        if state.is_select:
            statements.append(str(state.statement.compile(dialect=mysql.dialect())))

    event.listen(db, "do_orm_execute", capture)
    try:
        with pytest.raises(HTTPException) as denied:
            call(request, current_user=actor, db=db)
        assert denied.value.status_code == 403
    finally:
        event.remove(db, "do_orm_execute", capture)
        db.rollback()
    reads = [sql for sql in statements if sql.lstrip().startswith("SELECT")]
    assert "coding_write_gate" in reads[0] and "FOR UPDATE" in reads[0]
    assert "hoimsystem_users" in reads[1] and "LOCK IN SHARE MODE" in reads[1]
    assert len(reads) == 2  # No Home/dictionary/Patient/Group lookup after denial.
    assert counts == [db.query(model).count() for model in models]
    assert db.get(MedicalRecordHome, coding_case["home"].home_id).complication is None


@pytest.mark.parametrize("action", ["update", "submit"])
def test_locked_home_replaces_stale_draft_before_state_validation(db_session, coding_case, action):
    db = db_session
    home = coding_case["home"]
    home_id = home.home_id
    actor = coding_case["doctor_user"]
    assert home.status == 0
    with Session(db.get_bind()) as other:
        other.execute(update(MedicalRecordHome).where(MedicalRecordHome.home_id == home_id).values(status=2, complication="实际已归档原件"))
        other.commit()
    assert home.status == 0
    call = medical_record_home.update_medical_record_home if action == "update" else medical_record_home.submit_medical_record_home
    result = call(MedicalRecordHomeUpdateRequest(home_id=home_id, complication="不能覆盖"), current_user=actor, db=db)
    assert result["code"] in (403, 500)
    db.rollback()
    db.expire_all()
    assert db.get(MedicalRecordHome, home_id).status == 2
    assert db.get(MedicalRecordHome, home_id).complication == "实际已归档原件"


def test_dictionary_update_keeps_concurrent_original_code_and_category(db_session, coding_case):
    db = db_session
    original = coding_case["diagnosis"]
    pk, old_code = original.diagnosis_id, original.code
    with Session(db.get_bind()) as other:
        other.execute(update(Icd10Diagnosis).where(Icd10Diagnosis.diagnosis_id == pk).values(code=old_code + "X", category="已改的原分类"))
        other.commit()
    assert original.code == old_code
    response = icd10.update_diagnosis(Icd10UpdateRequest(id=pk, name="仅变更名称"), current_user=coding_case["admin_user"], db=db)
    assert response["code"] == 200
    db.expire_all()
    actual = db.get(Icd10Diagnosis, pk)
    assert (actual.code, actual.category, actual.name) == (old_code + "X", "已改的原分类", "仅变更名称")


def test_archive_rechecks_stale_status_without_reopening_sealed_record(db_session, coding_case):
    db = db_session
    archive = coding_case["archive"]
    archive_id = archive.archive_id
    with Session(db.get_bind()) as other:
        other.execute(update(MedicalRecordArchive).where(MedicalRecordArchive.archive_id == archive_id).values(status=3, seal_reason="原封存依据"))
        other.commit()
    assert archive.status == 0
    result = medical_record_archive.archive_record(MedicalRecordArchiveActionRequest(archive_id=archive_id), current_user=coding_case["admin_user"], db=db)
    assert result["code"] == 500
    db.rollback()
    db.expire_all()
    assert db.get(MedicalRecordArchive, archive_id).status == 3
    assert db.get(MedicalRecordHome, coding_case["home"].home_id).status == 0


def test_bind_uses_current_dictionary_and_primary_transitions_share_real_parent(db_session, coding_case):
    db = db_session
    home_id = coding_case["home"].home_id
    dictionary = coding_case["diagnosis"]
    old_name = dictionary.name
    with Session(db.get_bind()) as other:
        other.execute(update(Icd10Diagnosis).where(Icd10Diagnosis.diagnosis_id == dictionary.diagnosis_id).values(name="当前字典名"))
        other.commit()
    assert dictionary.name == old_name
    result = home_icd.bind_icd({"home_id": home_id, "kind": "diagnosis", "icd_code": dictionary.code, "is_primary": True}, current_user=coding_case["admin_user"], db=db)
    assert result["code"] == 200
    binding = db.get(HomeIcdBinding, result["data"]["binding_id"])
    assert binding.icd_name == "当前字典名"
    binding_id = binding.binding_id
    statements = []

    def capture(state):
        if state.is_select:
            statements.append(str(state.statement.compile(dialect=mysql.dialect())))

    event.listen(db, "do_orm_execute", capture)
    try:
        assert home_icd.set_primary({"binding_id": binding_id}, current_user=coding_case["admin_user"], db=db)["code"] == 200
    finally:
        event.remove(db, "do_orm_execute", capture)
    home_read = next(i for i, sql in enumerate(statements) if "FROM hoimsystem_medical_record_home" in sql)
    full_child_read = next(i for i, sql in enumerate(statements) if "hoimsystem_home_icd_binding.kind" in sql and "FROM hoimsystem_home_icd_binding" in sql)
    assert home_read < full_child_read
    assert "FOR UPDATE" in statements[home_read] and "FOR UPDATE" in statements[full_child_read]
    assert home_icd.unbind_icd({"binding_id": binding.binding_id}, current_user=coding_case["admin_user"], db=db)["code"] == 200
    assert db.query(HomeIcdBinding).filter_by(home_id=home_id).count() == 0


@pytest.mark.asyncio
async def test_main_jwt_original_coding_and_local_prefix_workflow(async_client, auth_headers, coding_case, db_session):
    case = coding_case
    headers = auth_headers(case["admin_user"].username)
    home_id = case["home"].home_id
    update_response = await async_client.put("/api/medicalRecordHome/update", headers=headers, json={"home_id": home_id, "discharge_diagnosis": "真实原业务校验仍保留"})
    assert update_response.json()["code"] == 200
    submitted = await async_client.post("/api/medicalRecordHome/submit", headers=headers, json={"home_id": home_id})
    assert submitted.json()["data"]["status"] == 1
    bind = await async_client.post("/api/homeIcd/bind", headers=headers, json={"home_id": home_id, "kind": "diagnosis", "icd_code": case["diagnosis"].code, "is_primary": True})
    assert bind.json()["code"] == 200
    group = await async_client.post("/api/insurance/drg/autoGroup", headers=headers, json={"home_id": home_id, "actual_amount": 80})
    assert group.json()["data"]["group_code"] == case["rule"].group_code
    assert Decimal(str(group.json()["data"]["expected_amount"])) == 120
    existing = await async_client.post("/api/insurance/drg/autoGroup", headers=headers, json={"home_id": home_id})
    assert existing.json()["data"]["idempotent"] is True
    archive = await async_client.post("/api/medicalRecordArchive/archive", headers=headers, json={"archive_id": case["archive"].archive_id})
    assert archive.json()["code"] == 200
    db_session.expire_all()
    assert db_session.get(MedicalRecordHome, home_id).status == 2
    group_row = db_session.get(DrgGrouping, group.json()["data"]["grouping_id"])
    assert group_row.grouping_method == "automatic"  # Existing local prefix result; no national-grouper claim.
    assert group_row.rule_id == case["rule"].rule_id
    assert inspect(group_row).persistent


def test_current_doctor_identity_is_rechecked_before_owned_home_update(db_session, coding_case):
    from app.models import Doctor

    db = db_session
    doctor = coding_case["doctor"]
    doctor_id = doctor.doctor_id
    home_id = coding_case["home"].home_id
    assert doctor.user_id == coding_case["doctor_user"].user_id
    with Session(db.get_bind()) as other:
        other.execute(update(Doctor).where(Doctor.doctor_id == doctor_id).values(user_id=None))
        other.commit()
    result = medical_record_home.update_medical_record_home(
        MedicalRecordHomeUpdateRequest(home_id=home_id, complication="不可借旧Doctor关系写入"),
        current_user=coding_case["doctor_user"],
        db=db,
    )
    assert result["code"] == 403
    db.rollback()
    db.expire_all()
    assert db.get(MedicalRecordHome, home_id).complication is None


@pytest.mark.parametrize("force", [False, True])
def test_auto_group_rechecks_recorded_group_and_linked_rule_without_changing_match(db_session, coding_case, force):
    db = db_session
    case = coding_case
    home, rule = case["home"], case["rule"]
    home.status = 1
    binding = HomeIcdBinding(
        home_id=home.home_id,
        kind="diagnosis",
        icd_code=rule.diagnosis_prefix,
        icd_name="合成",
        is_primary=1,
        coder_id=case["admin_user"].user_id,
        code_time=datetime.datetime(2026, 10, 21, 12),
    )
    grouping = DrgGrouping(
        home_id=home.home_id,
        patient_id=home.patient_id,
        rule_id=rule.rule_id,
        group_code="STALE",
        diagnosis="合成原诊断",
        expected_amount=120,
        actual_amount=80,
        profit=40,
        create_time=datetime.datetime(2026, 10, 21, 12),
    )
    db.add_all([binding, grouping])
    db.commit()
    home_id, group_id, rule_id = home.home_id, grouping.grouping_id, rule.rule_id
    assert grouping.group_code == "STALE" and rule.expected_amount == 120
    with Session(db.get_bind()) as other:
        other.execute(update(DrgGrouping).where(DrgGrouping.grouping_id == group_id).values(group_code="CURRENT-RECORDED"))
        other.execute(update(DrgRule).where(DrgRule.rule_id == rule_id).values(expected_amount=Decimal("150")))
        other.commit()
    result = insurance.automatic_drg_group({"home_id": home_id, "force": force, "actual_amount": 80}, current_user=case["admin_user"], db=db)
    assert result["code"] == 200
    if force:
        assert result["data"]["idempotent"] is False
        assert result["data"]["group_code"] == rule.group_code
        assert result["data"]["expected_amount"] == Decimal("150")
        assert result["data"]["profit"] == Decimal("70")
    else:
        assert result["data"]["idempotent"] is True
        assert result["data"]["group_code"] == "CURRENT-RECORDED"
    db.rollback()
