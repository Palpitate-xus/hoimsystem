"""Actual synthetic project registry governance; no clinical collection claim."""

import datetime as dt
import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import event, text

from app.ai.models import AIAuditEvent, AIPatientGrant
from app.ai.research_cohort_models import AIResearchStudyScope
from app.ai.research_cohort_sources import create_scope, review_scope, review_scope_authorization, scope_current, utc_text, utcnow
from app.models import User
from tests.test_ai_research_cohort_contract import BASIS


@pytest.fixture
def research_case(db_session, seed_data):
    db = db_session
    reviewer = User(username="research_" + uuid.uuid4().hex[:10], user_role="super_admin")
    db.add(reviewer)
    db.commit()
    now = utcnow()
    request = dict(
        protocol_key="synthetic-bounded-protocol",
        title="仅合成项目登记与独立授权记录",
        purpose=BASIS,
        patient_ids=[seed_data["patient"].patient_id],
        proposed_user_ids=sorted([seed_data["admin_user"].user_id, seed_data["super_admin_user"].user_id, reviewer.user_id]),
        data_families=["medical_records", "patient_demographics"],
        permitted_uses=["cohort_criteria_review"],
        record_window={"date_from": "2026-10-01", "date_to": "2026-10-21", "time_basis": "legacy_naive_calendar_dates_timezone_unknown"},
        valid_from=utc_text(now - dt.timedelta(days=1)),
        valid_until=utc_text(now + dt.timedelta(days=1)),
        external_model_use="unknown",
        external_model_use_basis=BASIS,
        authority_reference=None,
        authorization_basis=BASIS,
    )
    return {**seed_data, "reviewer": reviewer, "scope_request": request}


def manual_body(made, decision="recorded_reviewed"):
    return dict(expected_revision=1, expected_content_hash=made["content_hash"], decision=decision, review_scope="documentary_authorization_review_not_irb_certification", basis_note=BASIS)


def complete_scope(db, case):
    made = create_scope(db, case["super_admin_user"], case["scope_request"])
    reviewed = review_scope_authorization(db, case["reviewer"], made["scope_id"], manual_body(made))
    published = review_scope(db, case["super_admin_user"], made["scope_id"], dict(expected_revision=1, decision="publish", basis_note=BASIS))
    return made, reviewed, published


def test_actual_registry_manual_review_and_technical_publication_have_different_hash_lineage_without_reading_clinical_content(db_session, research_case):
    db, case = db_session, research_case
    statements = []

    def seen(conn, cursor, sql, params, context, many):
        statements.append(sql)

    event.listen(db.bind, "before_cursor_execute", seen)
    try:
        made, reviewed, published = complete_scope(db, case)
    finally:
        event.remove(db.bind, "before_cursor_execute", seen)
    assert made["status"] == reviewed["status"] == "draft" and published["status"] == "published"
    assert made["content_hash"] == reviewed["content_hash"] == published["content_hash"]
    assert len({made["governance_hash"], reviewed["governance_hash"], published["governance_hash"]}) == 3
    assert made["authorization_review_status"] == "unknown" and reviewed["authorization_reviewed_by"] == case["reviewer"].user_id
    assert published["eligible"] is True and published["eligibility_basis"] == "project_registry_only_not_patient_collection_permission"
    assert not any("hoimsystem_patient.name" in sql or "hoimsystem_medical_record.symptom" in sql or "hoimsystem_admission.chief_complaint" in sql for sql in statements)


def test_admin_role_alone_does_not_supply_access_basis_or_patient_research_permission(db_session, research_case):
    db, case = db_session, research_case
    before = db.query(AIResearchStudyScope).count()
    with pytest.raises(HTTPException) as error:
        create_scope(db, case["admin_user"], case["scope_request"])
    assert error.value.status_code == 403 and db.query(AIResearchStudyScope).count() == before
    # A real expiring category grant permits registry input, not research use.
    db.add(
        AIPatientGrant(
            user_id=case["admin_user"].user_id,
            patient_id=case["patient"].patient_id,
            category="knowledge",
            reason="仅合成当前访问依据，不代表项目研究授权。",
            expires_at=utcnow() + dt.timedelta(days=1),
            revoked=0,
            created_by=case["super_admin_user"].user_id,
        )
    )
    db.commit()
    made = create_scope(db, case["admin_user"], case["scope_request"])
    assert not made["eligible"] and made["authorization_review_status"] == "unknown"


def test_technical_publish_does_not_fill_independent_review_or_grant_dataset_access(db_session, research_case):
    db, case = db_session, research_case
    made = create_scope(db, case["super_admin_user"], case["scope_request"])
    value = review_scope(db, case["reviewer"], made["scope_id"], dict(expected_revision=1, decision="publish", basis_note=BASIS))
    assert value["status"] == "published" and not value["eligible"]
    assert value["authorization_reviewed_by"] is None and value["authorization_review_status"] == "unknown"
    with pytest.raises(HTTPException) as error:
        review_scope_authorization(db, case["reviewer"], made["scope_id"], manual_body(made))
    assert error.value.status_code == 409


@pytest.mark.parametrize("mutation", ["creator", "wrong_hash", "second_signature"])
def test_independent_review_cannot_self_sign_rebind_original_or_overwrite_existing_signature(db_session, research_case, mutation):
    db, case = db_session, research_case
    made = create_scope(db, case["super_admin_user"], case["scope_request"])
    body = manual_body(made)
    actor = case["reviewer"]
    if mutation == "creator":
        actor = case["super_admin_user"]
    elif mutation == "wrong_hash":
        body["expected_content_hash"] = "f" * 64
    else:
        review_scope_authorization(db, actor, made["scope_id"], body)
    before = db.query(AIAuditEvent).count()
    with pytest.raises(HTTPException) as error:
        review_scope_authorization(db, actor, made["scope_id"], body)
    assert error.value.status_code == 409 and db.query(AIAuditEvent).count() == before


def test_plain_registry_reader_cannot_read_a_foreign_scope_before_original_text(db_session, research_case):
    db, case = db_session, research_case
    made = create_scope(db, case["super_admin_user"], case["scope_request"])
    statements = []

    def seen(conn, cursor, sql, params, context, many):
        statements.append(sql)

    event.listen(db.bind, "before_cursor_execute", seen)
    try:
        with pytest.raises(HTTPException) as error:
            scope_current(db, case["admin_user"], made["scope_id"])
        assert error.value.status_code == 403
    finally:
        event.remove(db.bind, "before_cursor_execute", seen)
    assert not any("hoimsystem_ai_research_study_scope.scope_json" in sql for sql in statements)


def test_stale_technical_cas_does_not_overwrite_published_or_add_a_second_audit(db_session, research_case):
    db, case = db_session, research_case
    made, _, published = complete_scope(db, case)
    before = db.query(AIAuditEvent).count()
    with pytest.raises(HTTPException) as error:
        review_scope(db, case["reviewer"], made["scope_id"], dict(expected_revision=1, decision="reject", basis_note=BASIS))
    assert error.value.status_code == 409 and db.query(AIAuditEvent).count() == before
    assert scope_current(db, case["super_admin_user"], made["scope_id"], audit_only=True)["governance_hash"] == published["governance_hash"]


def test_revoke_redacts_ordinary_original_notes_but_super_retains_full_own_bytes(db_session, research_case):
    db, case = db_session, research_case
    db.add(
        AIPatientGrant(
            user_id=case["admin_user"].user_id,
            patient_id=case["patient"].patient_id,
            category="knowledge",
            reason="仅合成登记访问",
            expires_at=utcnow() + dt.timedelta(days=1),
            revoked=0,
            created_by=case["super_admin_user"].user_id,
        )
    )
    db.commit()
    made = create_scope(db, case["admin_user"], case["scope_request"])
    review_scope_authorization(db, case["reviewer"], made["scope_id"], manual_body(made))
    review_scope(db, case["reviewer"], made["scope_id"], dict(expected_revision=1, decision="publish", basis_note=BASIS))
    review_scope(db, case["admin_user"], made["scope_id"], dict(expected_revision=2, basis_note=BASIS), revoke=True)
    ordinary = scope_current(db, case["admin_user"], made["scope_id"])
    full = scope_current(db, case["super_admin_user"], made["scope_id"], audit_only=True)
    assert ordinary["original"] is None and ordinary["review_basis_note"] is None and ordinary["revoke_reason"] is None and ordinary["authorization_review_basis"] is None
    assert full["original"] is not None and full["review_basis_note"] == full["revoke_reason"] == BASIS
    assert ordinary["governance_hash"] == full["governance_hash"]


@pytest.mark.parametrize("fault", ["actor", "body", "audit"])
def test_actual_same_transaction_sql_fault_rolls_back_registry_governance_signature_and_specific_audit(db_session, research_case, fault):
    db, case = db_session, research_case
    made = create_scope(db, case["super_admin_user"], case["scope_request"])
    before = db.query(AIAuditEvent).count()
    uid = case["reviewer"].user_id
    body = {
        "actor": f"UPDATE hoimsystem_users SET user_role='patient' WHERE user_id={uid};",
        "body": "UPDATE hoimsystem_ai_research_study_scope SET content_hash='" + "f" * 64 + "' WHERE scope_id=NEW.target;",
        "audit": "UPDATE hoimsystem_ai_audit_event SET detail_json='{}' WHERE event_id=NEW.event_id;",
    }[fault]
    db.execute(text("CREATE TRIGGER synthetic_research_fault AFTER INSERT ON hoimsystem_ai_audit_event WHEN NEW.action='research.scope.authorization_review' BEGIN " + body + " END"))
    db.commit()
    try:
        with pytest.raises(HTTPException):
            review_scope_authorization(db, case["reviewer"], made["scope_id"], manual_body(made))
        assert db.query(AIAuditEvent).count() == before
        row = db.get(AIResearchStudyScope, made["scope_id"])
        assert row.authorization_review_status == "unknown" and row.content_hash == made["content_hash"]
        assert case["reviewer"].user_role == "super_admin"
    finally:
        db.rollback()
        db.execute(text("DROP TRIGGER synthetic_research_fault"))
        db.commit()


def test_own_original_corruption_is_not_bypassed_by_super_frozen_registry_audit(db_session, research_case):
    db, case = db_session, research_case
    made = create_scope(db, case["super_admin_user"], case["scope_request"])
    db.execute(text("UPDATE hoimsystem_ai_research_study_scope SET scope_json='{}' WHERE scope_id=:id"), {"id": made["scope_id"]})
    db.commit()
    with pytest.raises(HTTPException) as error:
        scope_current(db, case["super_admin_user"], made["scope_id"], audit_only=True)
    assert error.value.status_code == 409
