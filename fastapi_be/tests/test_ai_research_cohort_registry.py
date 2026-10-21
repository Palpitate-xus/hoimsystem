"""Actual explicit project/member/patient authorization, no clinical extraction."""

import pytest
from fastapi import HTTPException
from sqlalchemy import event

from app.ai.research_cohort_registry import authorize_patient_research, authorize_project_acl, create_registry_original, registry_current, review_registry_original
from app.ai.research_cohort_sources import review_scope
from tests.test_ai_research_cohort_contract import BASIS
from tests.test_ai_research_cohort_sources import complete_scope
from tests.test_ai_research_cohort_sources import research_case as research_case  # noqa: F401


def anchors(published):
    return {"scope_id": published["scope_id"], "scope_content_hash": published["content_hash"], "scope_governance_hash": published["governance_hash"]}


def acl_request(case, published, permission="read_capture"):
    return {**anchors(published), "user_id": case["admin_user"].user_id, "permission": permission, "valid_from": published["valid_from"], "valid_until": published["valid_until"], "basis_note": BASIS}


def auth_request(case, published, kind="permission_recorded", basis="explicit_project_acl"):
    return {
        **anchors(published),
        "patient_id": case["patient"].patient_id,
        "authorization_kind": kind,
        "access_basis": basis,
        "valid_from": published["valid_from"],
        "valid_until": published["valid_until"],
        "authority_reference": "隔离合成手工记录，无真实伦理审批材料",
        "original_authority_text": "\ufeff隔离合成授权原文\r\n🧪保留原否定和未知",
        "basis_note": BASIS,
    }


def publish(db, case, kind, value, manual=False):
    if manual:
        review_registry_original(
            db,
            case["reviewer"],
            kind,
            value["source_record_id"],
            dict(
                expected_revision=1, expected_content_hash=value["content_hash"], decision="recorded_reviewed", review_scope="documentary_authorization_review_not_irb_certification", basis_note=BASIS
            ),
            manual=True,
        )
    return review_registry_original(db, case["super_admin_user"], kind, value["source_record_id"], dict(expected_revision=1, decision="publish", basis_note=BASIS))


def permitted(db, case, *, authorization_kind="permission_recorded", permission="read_capture", basis="explicit_project_acl"):
    _, _, scope = complete_scope(db, case)
    acl = publish(db, case, "acl", create_registry_original(db, case["super_admin_user"], "acl", acl_request(case, scope, permission)))
    authorization = publish(db, case, "authorization", create_registry_original(db, case["super_admin_user"], "authorization", auth_request(case, scope, authorization_kind, basis)), manual=True)
    return scope, acl, authorization


def test_real_project_acl_and_patient_permission_are_both_required_even_for_super(db_session, research_case):
    db, case = db_session, research_case
    _, _, scope = complete_scope(db, case)
    for actor in (case["admin_user"], case["super_admin_user"]):
        with pytest.raises(HTTPException) as error:
            authorize_patient_research(db, actor, scope["scope_id"], case["patient"].patient_id, capture=True)
        assert error.value.status_code == 403
    acl = publish(db, case, "acl", create_registry_original(db, case["super_admin_user"], "acl", acl_request(case, scope)))
    assert authorize_project_acl(db, case["admin_user"], scope["scope_id"], capture=True)[1]["content_hash"] == acl["content_hash"]
    with pytest.raises(HTTPException):
        authorize_patient_research(db, case["admin_user"], scope["scope_id"], case["patient"].patient_id, capture=True)
    authorization = publish(db, case, "authorization", create_registry_original(db, case["super_admin_user"], "authorization", auth_request(case, scope)), manual=True)
    assert authorize_patient_research(db, case["admin_user"], scope["scope_id"], case["patient"].patient_id, capture=True)[2]["content_hash"] == authorization["content_hash"]
    with pytest.raises(HTTPException):
        authorize_patient_research(db, case["super_admin_user"], scope["scope_id"], case["patient"].patient_id, capture=True)


@pytest.mark.parametrize("kind", ["unknown", "withdrawn", "denied"])
def test_reviewed_negative_or_unknown_permission_never_becomes_eligible_by_technical_publication(db_session, research_case, kind):
    db, case = db_session, research_case
    scope, _, authorization = permitted(db, case, authorization_kind=kind)
    assert authorization["status"] == "published" and not authorization["eligible"]
    with pytest.raises(HTTPException) as error:
        authorize_patient_research(db, case["admin_user"], scope["scope_id"], case["patient"].patient_id, capture=True)
    assert error.value.status_code == 403
    assert authorization["original"]["payload"]["authorization_kind"] == kind
    assert authorization["original"]["payload"]["original_authority_text"] == auth_request(case, scope)["original_authority_text"]


def test_unreviewed_or_null_period_positive_record_is_not_invented_current_permission(db_session, research_case):
    db, case = db_session, research_case
    _, _, scope = complete_scope(db, case)
    publish(db, case, "acl", create_registry_original(db, case["super_admin_user"], "acl", acl_request(case, scope)))
    body = {**auth_request(case, scope), "valid_from": None, "valid_until": None}
    authorization = publish(db, case, "authorization", create_registry_original(db, case["super_admin_user"], "authorization", body))
    assert not authorization["eligible"]
    with pytest.raises(HTTPException):
        authorize_patient_research(db, case["admin_user"], scope["scope_id"], case["patient"].patient_id)


def test_explicit_read_only_and_care_grant_basis_remain_independent_from_research_permission(db_session, research_case):
    db, case = db_session, research_case
    scope, _, _ = permitted(db, case, permission="read_only", basis="current_care_or_grant")
    assert authorize_project_acl(db, case["admin_user"], scope["scope_id"])[0].user_role == "admin"
    with pytest.raises(HTTPException):
        authorize_project_acl(db, case["admin_user"], scope["scope_id"], capture=True)
    # Existing admin clinical bypass does not satisfy the explicit care basis.
    with pytest.raises(HTTPException):
        authorize_patient_research(db, case["admin_user"], scope["scope_id"], case["patient"].patient_id)


def test_same_patient_conflicting_published_root_is_not_filtered_or_latest_selected(db_session, research_case):
    db, case = db_session, research_case
    scope, _, _ = permitted(db, case)
    publish(db, case, "authorization", create_registry_original(db, case["super_admin_user"], "authorization", auth_request(case, scope, "withdrawn")), manual=True)
    with pytest.raises(HTTPException) as error:
        authorize_patient_research(db, case["admin_user"], scope["scope_id"], case["patient"].patient_id, capture=True)
    assert error.value.status_code == 403


@pytest.mark.parametrize("which", ["acl", "authorization", "scope"])
def test_revocation_clears_current_permission_without_super_technical_role_restoring_it(db_session, research_case, which):
    db, case = db_session, research_case
    scope, acl, authorization = permitted(db, case)
    assert authorize_patient_research(db, case["admin_user"], scope["scope_id"], case["patient"].patient_id, capture=True)
    if which == "scope":
        review_scope(db, case["super_admin_user"], scope["scope_id"], dict(expected_revision=2, basis_note=BASIS), revoke=True)
    else:
        original = acl if which == "acl" else authorization
        review_registry_original(db, case["super_admin_user"], which, original["source_record_id"], dict(expected_revision=2, basis_note=BASIS), revoke=True)
    for actor in (case["admin_user"], case["super_admin_user"]):
        with pytest.raises(HTTPException):
            authorize_patient_research(db, actor, scope["scope_id"], case["patient"].patient_id, capture=True)


def test_outside_project_patient_is_denied_before_any_clinical_body_query(db_session, research_case):
    db, case = db_session, research_case
    scope, _, _ = permitted(db, case)
    statements = []

    def seen(conn, cursor, sql, params, context, many):
        statements.append(sql)

    event.listen(db.bind, "before_cursor_execute", seen)
    try:
        with pytest.raises(HTTPException) as error:
            authorize_patient_research(db, case["admin_user"], scope["scope_id"], 2147483647, capture=True)
        assert error.value.status_code == 403
    finally:
        event.remove(db.bind, "before_cursor_execute", seen)
    assert not any("hoimsystem_patient.name" in sql or "hoimsystem_medical_record.symptom" in sql for sql in statements)


def test_registry_ordinary_redacted_opaque_governance_is_distinct_from_full_super_own_proof(db_session, research_case):
    db, case = db_session, research_case
    _, _, authorization = permitted(db, case)
    identifier = authorization["source_record_id"]
    full = review_registry_original(db, case["super_admin_user"], "authorization", identifier, dict(expected_revision=2, basis_note=BASIS), revoke=True)
    ordinary = registry_current(db, case["admin_user"], "authorization", identifier)
    assert ordinary["original"] is None and ordinary["review_basis_note"] is None and ordinary["revoke_reason"] is None and ordinary["authorization_review"]["authorization_review_basis"] is None
    assert full["original"] is not None and ordinary["governance_hash"] == full["governance_hash"]


@pytest.mark.parametrize("fault", ["scope", "actor", "audit"])
def test_actual_registry_audit_fault_rolls_back_parent_authority_source_and_specific_event(db_session, research_case, fault):
    from sqlalchemy import text

    from app.ai.models import AIAuditEvent
    from app.ai.research_cohort_models import AIResearchProjectACL

    db, case = db_session, research_case
    _, _, scope = complete_scope(db, case)
    before = (db.query(AIResearchProjectACL).count(), db.query(AIAuditEvent).count())
    uid = case["super_admin_user"].user_id
    bodies = {
        "scope": "UPDATE hoimsystem_ai_research_study_scope SET content_hash='" + "f" * 64 + "' WHERE scope_id='" + scope["scope_id"] + "';",
        "actor": f"UPDATE hoimsystem_users SET user_role='patient' WHERE user_id={uid};",
        "audit": "UPDATE hoimsystem_ai_audit_event SET detail_json='{}' WHERE event_id=NEW.event_id;",
    }
    db.execute(text("CREATE TRIGGER synthetic_registry_fault AFTER INSERT ON hoimsystem_ai_audit_event WHEN NEW.action='research.acl.create' BEGIN " + bodies[fault] + " END"))
    db.commit()
    try:
        with pytest.raises(HTTPException):
            create_registry_original(db, case["super_admin_user"], "acl", acl_request(case, scope))
        assert (db.query(AIResearchProjectACL).count(), db.query(AIAuditEvent).count()) == before
        assert case["super_admin_user"].user_role == "super_admin"
    finally:
        db.rollback()
        db.execute(text("DROP TRIGGER synthetic_registry_fault"))
        db.commit()


@pytest.mark.parametrize("kind", ["acl", "authorization"])
def test_pending_new_root_blocks_old_positive_grant_without_restoring_or_selecting_a_winner(db_session, research_case, kind):
    db, case = db_session, research_case
    scope, _, _ = permitted(db, case)
    request = acl_request(case, scope) if kind == "acl" else auth_request(case, scope, "withdrawn")
    create_registry_original(db, case["super_admin_user"], kind, request)
    with pytest.raises(HTTPException) as error:
        authorize_patient_research(db, case["admin_user"], scope["scope_id"], case["patient"].patient_id, capture=True)
    assert error.value.status_code == 403


def test_future_feature_or_model_processing_is_not_implicitly_authorized_by_a_project_acl(db_session, research_case):
    db, case = db_session, research_case
    scope, _, _ = permitted(db, case)
    for values in ({"use": "deidentification_review"}, {"use": "research_variable_extraction"}, {"external_model": True}):
        with pytest.raises(HTTPException) as error:
            authorize_patient_research(db, case["admin_user"], scope["scope_id"], case["patient"].patient_id, **values)
        assert error.value.status_code == 403
