"""Synthetic additive research foundation, not an authorization or IRB claim."""

import datetime as dt
import json
import uuid

import pytest
from sqlalchemy import CheckConstraint, ForeignKeyConstraint, inspect, text
from sqlalchemy.dialects import mysql
from sqlalchemy.exc import IntegrityError
from sqlalchemy.schema import CreateTable

from app.ai.research_cohort_models import RESEARCH_COHORT_MODELS, SOURCE_BYTES, AIResearchPatientAuthorization, AIResearchProjectACL, AIResearchStudyScope, AIResearchWriteGate

NOW = dt.datetime(2026, 10, 21, 12, 0, 0, 123456)


@pytest.fixture(autouse=True)
def research_foreign_keys(db_session):
    # The shared legacy fixture does not enable SQLite FK enforcement. Keep
    # this module's actual FK test local and restore its previous connection.
    previous = db_session.execute(text("PRAGMA foreign_keys")).scalar_one()
    db_session.execute(text("PRAGMA foreign_keys=ON"))
    assert db_session.execute(text("PRAGMA foreign_keys")).scalar_one() == 1
    try:
        yield
    finally:
        db_session.rollback()
        db_session.execute(text("PRAGMA foreign_keys=" + str(previous)))
        db_session.commit()


def draft(user_id):
    return dict(status="draft", revision=1, created_by=user_id, created_at=NOW, reviewed_by=None, reviewed_at=None, review_basis_note="", revoked_by=None, revoked_at=None, revoke_reason="")


def scope_row(user_id, **values):
    return AIResearchStudyScope(
        scope_id=str(uuid.uuid4()),
        schema_version="research_study_scope_v1",
        scope_json="{}",
        parent_binding_json="{}",
        content_hash="a" * 64,
        valid_from=NOW,
        valid_until=NOW + dt.timedelta(days=1),
        authorization_review_status="unknown",
        authorization_reviewed_by=None,
        authorization_reviewed_at=None,
        authorization_review_basis="",
        **draft(user_id),
        **values,
    )


def test_real_five_tables_have_distinct_project_patient_and_manual_review_foreign_keys():
    tables = [model.__table__ for model in RESEARCH_COHORT_MODELS]
    assert len(tables) == 5
    assert sum(len([c for c in t.constraints if isinstance(c, ForeignKeyConstraint)]) for t in tables) == 19
    ddls = [str(CreateTable(t).compile(dialect=mysql.dialect())) for t in tables]
    assert sum(ddl.count("DATETIME(6)") for ddl in ddls) == 20
    assert sum(ddl.count("MEDIUMTEXT") for ddl in ddls) == 8
    assert "AUTO_INCREMENT" not in ddls[0]
    assert AIResearchWriteGate.__table__.c.gate_id.autoincrement is False
    assert any(f.target_fullname == "hoimsystem_patient.patient_id" for f in AIResearchPatientAuthorization.__table__.foreign_keys)
    assert any(f.target_fullname == "hoimsystem_users.user_id" for f in AIResearchProjectACL.__table__.c.user_id.foreign_keys)
    assert all(max(len(c.name or "") for c in t.constraints) <= 64 for t in tables)
    assert all(isinstance(c, CheckConstraint) or c.__class__.__name__ in {"PrimaryKeyConstraint", "ForeignKeyConstraint"} for t in tables for c in t.constraints)


def test_actual_technical_publication_cannot_synthesize_independent_research_review(db_session, seed_data):
    db = db_session
    row = scope_row(seed_data["super_admin_user"].user_id)
    row.status, row.revision = "published", 2
    row.reviewed_by, row.reviewed_at = seed_data["super_admin_user"].user_id, NOW
    row.review_basis_note = "隔离合成技术发布，未声称取得IRB或患者研究授权。"
    db.add(row)
    db.commit()
    db.refresh(row)
    assert row.authorization_review_status == "unknown"
    assert row.authorization_reviewed_by is None and row.authorization_reviewed_at is None and row.authorization_review_basis == ""
    # Runtime eligibility is deliberately not claimed merely from SQL status.


@pytest.mark.parametrize("change", ["self", "missing_clock", "unknown_signed", "unknown_status"])
def test_manual_authorization_review_requires_distinct_actual_identity_complete_signature_and_closed_status(db_session, seed_data, change):
    db = db_session
    creator, reviewer = seed_data["admin_user"].user_id, seed_data["director_user"].user_id
    row = scope_row(creator)
    row.authorization_review_status = "recorded_reviewed"
    row.authorization_reviewed_by = reviewer
    row.authorization_reviewed_at = NOW
    row.authorization_review_basis = "隔离合成人工核查声明，不自动证明真实伦理审批或同意法律效力。"
    if change == "self":
        row.authorization_reviewed_by = creator
    elif change == "missing_clock":
        row.authorization_reviewed_at = None
    elif change == "unknown_signed":
        row.authorization_review_status = "unknown"
    else:
        row.authorization_review_status = "irb_certified"
    db.add(row)
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


def test_actual_independent_manual_review_and_technical_review_remain_separate(db_session, seed_data):
    db = db_session
    row = scope_row(seed_data["admin_user"].user_id)
    row.authorization_review_status = "recorded_reviewed"
    row.authorization_reviewed_by = seed_data["director_user"].user_id
    row.authorization_reviewed_at = NOW
    row.authorization_review_basis = "人工逐件核对已记录项目授权依据，非服务器伦理资格认证。"
    db.add(row)
    db.commit()
    db.refresh(row)
    assert row.status == "draft" and row.revision == 1 and row.reviewed_by is None
    assert row.authorization_reviewed_by != row.created_by


@pytest.mark.parametrize("extra", [0, 1])
def test_source_storage_counts_complete_utf8_bytes_without_truncation(db_session, seed_data, extra):
    db = db_session
    row = scope_row(seed_data["admin_user"].user_id)
    # JSON framing is 11 bytes. Multibyte characters make character limits
    # insufficient to establish the physical storage boundary.
    payload = json.dumps({"text": "汉" * 87377 + "xx" + "x" * extra}, ensure_ascii=False, separators=(",", ":"))
    assert len(payload.encode("utf-8")) == SOURCE_BYTES + extra
    row.scope_json = payload
    db.add(row)
    if extra:
        with pytest.raises(IntegrityError):
            db.flush()
        db.rollback()
    else:
        db.commit()
        db.refresh(row)
        assert row.scope_json == payload


@pytest.mark.parametrize("change", ["wrong_scope_fk", "wrong_user_fk", "bad_permission", "inverted_expiry"])
def test_project_acl_is_a_real_bounded_user_scope_grant_not_a_role_label(db_session, seed_data, change):
    db = db_session
    scope = scope_row(seed_data["admin_user"].user_id)
    db.add(scope)
    db.flush()
    row = AIResearchProjectACL(
        acl_id=str(uuid.uuid4()),
        scope_id=scope.scope_id,
        user_id=seed_data["director_user"].user_id,
        schema_version="research_project_acl_v1",
        permission="read_capture",
        payload_json="{}",
        parent_binding_json="{}",
        content_hash="b" * 64,
        valid_from=NOW,
        valid_until=NOW + dt.timedelta(days=1),
        **draft(seed_data["super_admin_user"].user_id),
    )
    if change == "wrong_scope_fk":
        row.scope_id = str(uuid.uuid4())
    elif change == "wrong_user_fk":
        row.user_id = 2147483647
    elif change == "bad_permission":
        row.permission = "all_hospital"
    else:
        row.valid_until = NOW
    db.add(row)
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


def test_unknown_patient_permission_does_not_become_consent_or_a_missing_date_substitute(db_session, seed_data):
    db = db_session
    scope = scope_row(seed_data["admin_user"].user_id)
    db.add(scope)
    db.flush()
    row = AIResearchPatientAuthorization(
        authorization_id=str(uuid.uuid4()),
        scope_id=scope.scope_id,
        patient_id=seed_data["patient"].patient_id,
        schema_version="research_patient_auth_v1",
        authorization_kind="unknown",
        access_basis="explicit_project_acl",
        payload_json="{}",
        parent_binding_json="{}",
        content_hash="c" * 64,
        valid_from=None,
        valid_until=None,
        authorization_review_status="unknown",
        authorization_reviewed_by=None,
        authorization_reviewed_at=None,
        authorization_review_basis="",
        **draft(seed_data["admin_user"].user_id),
    )
    db.add(row)
    db.commit()
    row = db.get(AIResearchPatientAuthorization, inspect(row).identity[0])
    assert row.valid_from is row.valid_until is None and row.authorization_kind == "unknown"
