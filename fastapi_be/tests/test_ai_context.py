"""Patient ownership, care grants and reviewed evidence boundaries."""

import datetime

import pytest
from fastapi import HTTPException

from app.ai.catalog import FEATURE_BY_KEY
from app.ai.context import authorize_patient, minimize_identifiers, patient_snapshot
from app.ai.governance import digest, encode_json
from app.ai.knowledge import evidence_is_current, retrieve_evidence
from app.ai.models import AIKnowledgeDocument, AIPatientGrant, utcnow
from app.models import Patient, Registration, User


def test_patient_cannot_read_another_patient_even_with_an_encounter_id(seed_data, db_session):
    with pytest.raises(HTTPException) as exc:
        authorize_patient(db_session, seed_data["patient_user"], seed_data["patient2"].patient_id, "patient")
    assert exc.value.status_code == 403
    snapshot = patient_snapshot(db_session, seed_data["patient_user"], FEATURE_BY_KEY["patient_report_explanation"], seed_data["patient"].patient_id)
    serialized = encode_json(snapshot.data)
    assert seed_data["patient"].identity not in serialized
    assert seed_data["patient"].name not in serialized
    assert snapshot.data["current_confirmed_diagnoses"] == []


def test_unrelated_doctor_requires_current_explicit_access(seed_data, db_session):
    user = User(username="ai_unrelated_doctor", password="test-only", user_role="doctor")
    patient = Patient(name="授权测试患者", identity="ai-grant-test", phone="13911112222")
    db_session.add_all([user, patient])
    db_session.flush()
    with pytest.raises(HTTPException):
        authorize_patient(db_session, user, patient.patient_id, "cdss")
    grant = AIPatientGrant(
        user_id=user.user_id,
        patient_id=patient.patient_id,
        category="cdss",
        reason="测试限定用途授权",
        expires_at=utcnow() + datetime.timedelta(hours=1),
        created_by=seed_data["super_admin_user"].user_id,
    )
    db_session.add(grant)
    db_session.commit()
    assert authorize_patient(db_session, user, patient.patient_id, "cdss").patient_id == patient.patient_id
    with pytest.raises(HTTPException):
        authorize_patient(db_session, user, patient.patient_id, "pharmacy")
    grant.revoked = 1
    db_session.commit()
    with pytest.raises(HTTPException):
        authorize_patient(db_session, user, patient.patient_id, "cdss")


def test_snapshot_keeps_missing_data_distinct_and_scrubs_adjacent_chinese_identifiers(seed_data, db_session):
    snapshot = patient_snapshot(db_session, seed_data["doctor_user"], FEATURE_BY_KEY["patient_summary"], seed_data["patient"].patient_id)
    assert any("本次就诊" in item for item in snapshot.data["missing_data"])
    assert all("source_id" in item for item in snapshot.evidence)
    assert minimize_identifiers("联系电话13911112222，证件370101199001011234。") == "联系电话[手机号已隐藏]，证件[证件号已隐藏]。"


def test_only_signed_diagnosis_from_selected_encounter_is_current(seed_data, db_session):
    encounter = Registration(patient_id=seed_data["patient"].patient_id, doctor_id=seed_data["doctor"].doctor_id, department_id=seed_data["department"].department_id, time=utcnow(), status=0)
    db_session.add(encounter)
    db_session.flush()
    record = seed_data["medical_record"]
    record.registration_uuid = encounter.registration_uuid
    record.status = 0
    db_session.commit()
    before = patient_snapshot(db_session, seed_data["doctor_user"], FEATURE_BY_KEY["treatment_pathway"], seed_data["patient"].patient_id, encounter.registration_uuid)
    assert before.data["current_confirmed_diagnoses"] == []
    record.status = 1
    db_session.commit()
    after = patient_snapshot(db_session, seed_data["doctor_user"], FEATURE_BY_KEY["treatment_pathway"], seed_data["patient"].patient_id, encounter.registration_uuid)
    assert record.result in after.data["current_confirmed_diagnoses"]


def test_retrieval_excludes_drafts_expired_wrong_feature_and_wrong_department(seed_data, db_session):
    user_id = seed_data["super_admin_user"].user_id
    created = []
    for suffix, kwargs in [
        ("current", {"status": "published"}),
        ("draft", {"status": "draft"}),
        ("expired", {"status": "published", "effective_to": utcnow() - datetime.timedelta(days=1)}),
        ("other-feature", {"status": "published", "feature_keys_json": '["patient_summary"]'}),
        ("other-department", {"status": "published", "department_id": 99999}),
    ]:
        content = "测试规范：问诊资料缺失时先核对临床记录，本文仅用于检索边界测试。"
        row = AIKnowledgeDocument(
            title="边界规范-" + suffix,
            version="test",
            source_uri="hospital://test/knowledge",
            content=content,
            content_hash=digest(content),
            feature_keys_json='["guideline_qa"]',
            reviewed_by=user_id,
            reviewed_at=utcnow(),
            created_by=user_id,
        )
        for name, value in kwargs.items():
            setattr(row, name, value)
        db_session.add(row)
        created.append(row)
    db_session.commit()
    evidence = retrieve_evidence(db_session, FEATURE_BY_KEY["guideline_qa"], "问诊资料缺失如何核对临床记录", set())
    assert {item["document_id"] for item in evidence} == {created[0].document_id}
    assert evidence_is_current(db_session, evidence)
    created[0].status = "retired"
    db_session.commit()
    assert not evidence_is_current(db_session, evidence)
