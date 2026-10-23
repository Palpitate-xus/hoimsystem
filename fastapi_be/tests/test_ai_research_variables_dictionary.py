"""Actual dictionary lifecycle, exact receipts and SQL rollback; synthetic only."""

import copy

import pytest
from fastapi import HTTPException
from sqlalchemy import event, text

from app.ai.models import AIAuditEvent
from app.ai.research_cohort_registry import create_registry_original, review_registry_original
from app.ai.research_variables_dictionary import create_dictionary, dictionary_current, review_dictionary, verify_dictionary_proof
from app.ai.research_variables_models import AIResearchVariableDictionary
from tests.test_ai_research_cohort_contract import BASIS
from tests.test_ai_research_cohort_registry import acl_request, anchors, permitted, publish
from tests.test_ai_research_cohort_sources import research_case as research_case  # noqa: F401
from tests.test_ai_research_variables_contract import definition


@pytest.fixture
def variable_dictionary_case(db_session, research_case):
    case = research_case
    case["scope_request"]["proposed_user_ids"] = sorted(set(case["scope_request"]["proposed_user_ids"] + [case["pharmacist_user"].user_id]))
    case["scope_request"]["permitted_uses"] = ["research_variable_extraction"]
    scope, _, permission = permitted(db_session, case)
    for actor in (case["super_admin_user"], case["reviewer"]):
        body = {**acl_request(case, scope), "user_id": actor.user_id}
        publish(db_session, case, "acl", create_registry_original(db_session, case["super_admin_user"], "acl", body))
    request = {**anchors(scope), "title": "隔离原字段变量字典", "purpose": BASIS, "basis_note": BASIS, "variables": [definition()]}
    return case, scope, permission, request


def definition_review(made):
    return dict(
        expected_revision=1, expected_content_hash=made["content_hash"], decision="recorded_reviewed", review_scope="recorded_variable_definition_review_not_scientific_validation", basis_note=BASIS
    )


def technical_review():
    return dict(expected_revision=1, decision="publish", basis_note=BASIS)


def test_whole_dictionary_independent_review_publication_and_revocation_have_distinct_exact_receipts(db_session, variable_dictionary_case):
    case, _, _, request = variable_dictionary_case
    made = create_dictionary(db_session, case["admin_user"], request)
    assert made["original"]["payload"] == request and made["original"]["definition_review"]["definition_review_status"] == "unknown"
    reviewed = review_dictionary(db_session, case["reviewer"], made["dictionary_id"], definition_review(made), definition=True)
    assert not reviewed["eligible"] and reviewed["status"] == "draft"
    published = review_dictionary(db_session, case["super_admin_user"], made["dictionary_id"], technical_review())
    assert published["eligible"] and published["definition_reviewer_current"] is True
    revoked = review_dictionary(db_session, case["super_admin_user"], made["dictionary_id"], dict(expected_revision=2, basis_note=BASIS), revoke=True)
    assert not revoked["eligible"] and revoked["revision"] == 3
    versions = [made, reviewed, published, revoked]
    assert len({v["content_hash"] for v in versions}) == 1
    assert len({v["governance_hash"] for v in versions}) == 4
    ids = [v["original"]["last_event_id"] for v in versions]
    assert len(set(ids)) == 4
    assert db_session.query(AIAuditEvent).filter(AIAuditEvent.event_id.in_(ids)).count() == 4
    assert dictionary_current(db_session, case["admin_user"], made["dictionary_id"]) == revoked


def test_technical_publish_cannot_invent_independent_definition_review(db_session, variable_dictionary_case):
    case, _, _, request = variable_dictionary_case
    made = create_dictionary(db_session, case["admin_user"], request)
    value = review_dictionary(db_session, case["super_admin_user"], made["dictionary_id"], technical_review())
    assert value["status"] == "published" and not value["eligible"]
    assert value["original"]["definition_review"]["definition_reviewed_by"] is None
    with pytest.raises(HTTPException) as error:
        review_dictionary(db_session, case["reviewer"], made["dictionary_id"], definition_review(made), definition=True)
    assert error.value.status_code == 409


@pytest.mark.parametrize("damage", [None, "extra", "literal", "identity", "utc", "review_self", "parent", "event_bool"])
def test_actual_frozen_dictionary_independently_reconstructs_and_never_invents_current_authority(db_session, variable_dictionary_case, damage):
    case, _, _, request = variable_dictionary_case
    made = create_dictionary(db_session, case["admin_user"], request)
    reviewed = review_dictionary(db_session, case["reviewer"], made["dictionary_id"], definition_review(made), definition=True)
    value = copy.deepcopy(reviewed["original"])
    if damage is None:
        assert verify_dictionary_proof(value) == value
        return
    if damage == "extra":
        value["eligible"] = True
    elif damage == "literal":
        value["payload"]["variables"][0]["extraction_instruction"] += "错误追加"
    elif damage == "identity":
        value["identity"]["dictionary_id"] = "00000000-0000-4000-8000-000000000001"
    elif damage == "utc":
        value["identity"]["created_at"] = value["identity"]["created_at"].replace("Z", "+00:00")
    elif damage == "review_self":
        value["definition_review"]["definition_reviewed_by"] = value["identity"]["created_by"]
    elif damage == "parent":
        value["parent_binding"]["scope"]["payload"]["permitted_uses"] = ["cohort_criteria_review"]
    else:
        value["last_event_id"] = True
    with pytest.raises(HTTPException) as error:
        verify_dictionary_proof(value)
    assert error.value.status_code == 409


@pytest.mark.parametrize("change,status", [("self", 409), ("hash", 409), ("bool_revision", 422), ("duplicate", 409)])
def test_independent_review_cannot_self_sign_rebind_or_overwrite(db_session, variable_dictionary_case, change, status):
    case, _, _, request = variable_dictionary_case
    made = create_dictionary(db_session, case["admin_user"], request)
    body, actor = definition_review(made), case["reviewer"]
    if change == "self":
        actor = case["admin_user"]
    elif change == "hash":
        body["expected_content_hash"] = "f" * 64
    elif change == "bool_revision":
        body["expected_revision"] = True
    else:
        review_dictionary(db_session, actor, made["dictionary_id"], body, definition=True)
    before = db_session.query(AIAuditEvent).count()
    with pytest.raises(HTTPException) as error:
        review_dictionary(db_session, actor, made["dictionary_id"], body, definition=True)
    assert error.value.status_code == status and db_session.query(AIAuditEvent).count() == before


def test_regular_admin_cannot_technically_publish_or_read_super_archive(db_session, variable_dictionary_case):
    case, _, _, request = variable_dictionary_case
    made = create_dictionary(db_session, case["admin_user"], request)
    for call in (
        lambda: review_dictionary(db_session, case["admin_user"], made["dictionary_id"], technical_review()),
        lambda: dictionary_current(db_session, case["admin_user"], made["dictionary_id"], audit_only=True),
    ):
        with pytest.raises(HTTPException) as error:
            call()
        assert error.value.status_code == 403


def test_pharmacist_needs_explicit_project_patient_and_variable_purpose_before_authoring_dictionary(db_session, variable_dictionary_case):
    case, scope, _, request = variable_dictionary_case
    pharmacist = case["pharmacist_user"]
    with pytest.raises(HTTPException) as error:
        create_dictionary(db_session, pharmacist, request)
    assert error.value.status_code == 403
    body = {**acl_request(case, scope), "user_id": pharmacist.user_id}
    publish(db_session, case, "acl", create_registry_original(db_session, case["super_admin_user"], "acl", body))
    made = create_dictionary(db_session, pharmacist, request)
    assert made["original"]["identity"]["created_by"] == pharmacist.user_id
    assert made["status"] == "draft" and not made["eligible"]
    with pytest.raises(HTTPException) as error:
        review_dictionary(db_session, pharmacist, made["dictionary_id"], definition_review(made), definition=True)
    assert error.value.status_code == 409


def test_withdrawn_patient_permission_blocks_dictionary_body_even_super_but_keeps_safe_technical_metadata(db_session, variable_dictionary_case):
    case, _, permission, request = variable_dictionary_case
    made = create_dictionary(db_session, case["admin_user"], request)
    review_registry_original(db_session, case["super_admin_user"], "authorization", permission["source_record_id"], dict(expected_revision=2, basis_note=BASIS), revoke=True)
    statements = []

    def record(conn, cursor, statement, params, context, many):
        statements.append(statement)

    event.listen(db_session.bind, "before_cursor_execute", record)
    try:
        for actor in (case["admin_user"], case["super_admin_user"]):
            with pytest.raises(HTTPException) as error:
                dictionary_current(db_session, actor, made["dictionary_id"])
            assert error.value.status_code == 403
        technical = dictionary_current(db_session, case["super_admin_user"], made["dictionary_id"], audit_only=True)
        assert technical["original"] is None and technical["audit_only"] is True and not technical["eligible"]
    finally:
        event.remove(db_session.bind, "before_cursor_execute", record)
    assert not any("hoimsystem_ai_research_variable_dictionary.dictionary_json" in sql or "hoimsystem_ai_research_variable_dictionary.parent_binding_json" in sql for sql in statements)


@pytest.mark.parametrize("damage", ["literal", "created_clock", "created_event", "last_event"])
def test_corrupt_whole_dictionary_or_exact_receipt_cannot_fall_back_to_a_nearby_audit(db_session, variable_dictionary_case, damage):
    case, _, _, request = variable_dictionary_case
    made = create_dictionary(db_session, case["admin_user"], request)
    if damage == "literal":
        changed = copy.deepcopy(request)
        changed["variables"][0]["label"] = "不同原文字典"
        from app.ai.research_cohort_contract import canonical_json

        db_session.execute(
            text("UPDATE hoimsystem_ai_research_variable_dictionary SET dictionary_json=:value WHERE dictionary_id=:id"), {"value": canonical_json(changed), "id": made["dictionary_id"]}
        )
    elif damage == "created_clock":
        db_session.execute(text("UPDATE hoimsystem_ai_research_variable_dictionary SET created_at=datetime(created_at,'+1 second') WHERE dictionary_id=:id"), {"id": made["dictionary_id"]})
    else:
        field = "created_event_id" if damage == "created_event" else "last_event_id"
        old = db_session.query(AIAuditEvent.event_id).filter(AIAuditEvent.event_id != made["original"]["last_event_id"]).first()[0]
        db_session.execute(text("UPDATE hoimsystem_ai_research_variable_dictionary SET " + field + "=:value WHERE dictionary_id=:id"), {"value": old, "id": made["dictionary_id"]})
    db_session.commit()
    with pytest.raises(HTTPException) as error:
        dictionary_current(db_session, case["super_admin_user"], made["dictionary_id"])
    assert error.value.status_code == 409


@pytest.mark.parametrize("fault", ["body", "actor", "audit"])
def test_real_postwrite_sql_faults_roll_back_owned_dictionary_and_specific_audit(db_session, variable_dictionary_case, fault):
    case, _, _, request = variable_dictionary_case
    actor_id = case["admin_user"].user_id
    before = (db_session.query(AIResearchVariableDictionary).count(), db_session.query(AIAuditEvent).count())
    if fault == "body":
        trigger = "CREATE TRIGGER rv_owned_fault AFTER INSERT ON hoimsystem_ai_research_variable_dictionary BEGIN UPDATE hoimsystem_ai_research_variable_dictionary SET dictionary_json='{}' WHERE dictionary_id=NEW.dictionary_id; END"
    elif fault == "actor":
        trigger = f"CREATE TRIGGER rv_owned_fault AFTER INSERT ON hoimsystem_ai_research_variable_dictionary BEGIN UPDATE hoimsystem_users SET user_role='doctor' WHERE user_id={actor_id}; END"
    else:
        trigger = "CREATE TRIGGER rv_owned_fault AFTER INSERT ON hoimsystem_ai_research_variable_dictionary BEGIN UPDATE hoimsystem_ai_audit_event SET detail_json='{}' WHERE event_id=NEW.created_event_id; END"
    db_session.execute(text(trigger))
    db_session.commit()
    try:
        with pytest.raises(HTTPException) as error:
            create_dictionary(db_session, case["admin_user"], request)
        assert error.value.status_code in {403, 409}
        assert (db_session.query(AIResearchVariableDictionary).count(), db_session.query(AIAuditEvent).count()) == before
    finally:
        db_session.rollback()
        db_session.execute(text("DROP TRIGGER IF EXISTS rv_owned_fault"))
        db_session.commit()
