"""Actual76 purpose/finite membership authority with zero private body SQL."""

import copy

import pytest
from fastapi import HTTPException
from sqlalchemy import event

from app.ai.research_cohort_registry import create_registry_original, review_registry_original
from app.ai.research_variables_authority import authorize_variable_scope, validate_dictionary_scope
from tests.test_ai_research_cohort_contract import BASIS
from tests.test_ai_research_cohort_registry import acl_request, anchors, permitted, publish
from tests.test_ai_research_cohort_sources import research_case as research_case  # noqa: F401
from tests.test_ai_research_variables_contract import definition


@pytest.fixture
def authorized_variable_case(db_session, research_case):
    case = research_case
    case["scope_request"]["permitted_uses"] = ["research_variable_extraction"]
    scope, acl, permission = permitted(db_session, case)
    return case, scope, acl, permission


@pytest.fixture
def no_private_body_sql():
    def call(db, *args, **kwargs):
        statements = []

        def record(conn, cursor, statement, params, context, many):
            statements.append(statement)

        event.listen(db.bind, "before_cursor_execute", record)
        try:
            return authorize_variable_scope(db, *args, **kwargs)
        finally:
            event.remove(db.bind, "before_cursor_execute", record)
            forbidden = (
                "hoimsystem_medical_record.symptom",
                "hoimsystem_patient.sex",
                "hoimsystem_patient.name",
                "hoimsystem_ai_research_variable_dictionary.dictionary_json",
                "hoimsystem_ai_research_variable_batch.snapshot_json",
            )
            assert not any(column in sql for sql in statements for column in forbidden)

    return call


def test_current_explicit_variable_purpose_returns_complete_actual_permission_originals(db_session, authorized_variable_case, no_private_body_sql):
    case, scope, acl, permission = authorized_variable_case
    actor, actual_scope, actual_acl, permissions = no_private_body_sql(db_session, case["admin_user"], anchors(scope), capture=True)
    assert actor.user_id == case["admin_user"].user_id
    assert actual_scope == scope["original"] and actual_acl["content_hash"] == acl["content_hash"]
    assert [p["content_hash"] for p in permissions] == [permission["content_hash"]]


@pytest.mark.parametrize("other_use", ["cohort_criteria_review", "deidentification_review"])
def test_other_research_permission_cannot_implicitly_authorize76(db_session, research_case, other_use, no_private_body_sql):
    research_case["scope_request"]["permitted_uses"] = [other_use]
    scope, _, _ = permitted(db_session, research_case)
    with pytest.raises(HTTPException) as error:
        no_private_body_sql(db_session, research_case["admin_user"], anchors(scope), capture=True)
    assert error.value.status_code == 403


def test_model_processing_remains_independent_of_internal_variable_read(db_session, authorized_variable_case, no_private_body_sql):
    case, scope, _, _ = authorized_variable_case
    assert no_private_body_sql(db_session, case["admin_user"], anchors(scope))[1]["payload"]["external_model_use"] == "unknown"
    with pytest.raises(HTTPException) as error:
        no_private_body_sql(db_session, case["admin_user"], anchors(scope), external_model=True)
    assert error.value.status_code == 403


def test_super_needs_own_current_acl_and_loses_body_authority_on_patient_withdrawal(db_session, authorized_variable_case, no_private_body_sql):
    case, scope, _, permission = authorized_variable_case
    with pytest.raises(HTTPException) as error:
        no_private_body_sql(db_session, case["super_admin_user"], anchors(scope))
    assert error.value.status_code == 403
    body = {**acl_request(case, scope), "user_id": case["super_admin_user"].user_id}
    publish(db_session, case, "acl", create_registry_original(db_session, case["super_admin_user"], "acl", body))
    assert len(no_private_body_sql(db_session, case["super_admin_user"], anchors(scope))[3]) == 1
    review_registry_original(db_session, case["super_admin_user"], "authorization", permission["source_record_id"], {"expected_revision": 2, "basis_note": BASIS}, revoke=True)
    for actor in (case["admin_user"], case["super_admin_user"]):
        with pytest.raises(HTTPException) as error:
            no_private_body_sql(db_session, actor, anchors(scope))
        assert error.value.status_code == 403


@pytest.mark.parametrize("members,status", [([], 422), ([True], 422), ([1.0], 422), (["1"], 422), ((1,), 422), ([2147483647], 403)])
def test_batch_member_shape_and_scope_expansion_are_refused_before_body(db_session, authorized_variable_case, no_private_body_sql, members, status):
    case, scope, _, _ = authorized_variable_case
    with pytest.raises(HTTPException) as error:
        no_private_body_sql(db_session, case["admin_user"], anchors(scope), patient_ids=members)
    assert error.value.status_code == status


def test_duplicate_members_and_stale_scope_anchors_are_never_silently_replaced(db_session, authorized_variable_case, no_private_body_sql):
    case, scope, _, _ = authorized_variable_case
    pid = case["patient"].patient_id
    for request, members, status in [(anchors(scope), [pid, pid], 422), ({**anchors(scope), "scope_content_hash": "f" * 64}, [pid], 409)]:
        with pytest.raises(HTTPException) as error:
            no_private_body_sql(db_session, case["admin_user"], request, patient_ids=members)
        assert error.value.status_code == status


@pytest.mark.parametrize("change,status", [("family", 403), ("earlier_window", 403), ("later_window", 403), ("anchor", 409)])
def test_variable_dictionary_family_and_each_time_window_stay_inside_current_project(db_session, authorized_variable_case, no_private_body_sql, change, status):
    case, scope, _, _ = authorized_variable_case
    current = no_private_body_sql(db_session, case["admin_user"], anchors(scope))[1]
    body = {**anchors(scope), "title": "隔离变量定义", "purpose": BASIS, "basis_note": BASIS, "variables": [definition()]}
    assert validate_dictionary_scope(body, current).model_dump() == body
    damaged = copy.deepcopy(body)
    if change == "family":
        damaged["variables"][0].update(family="admissions", field="chief_complaint")
    elif change == "earlier_window":
        damaged["variables"][0]["record_window"]["date_from"] = "2026-09-30"
    elif change == "later_window":
        damaged["variables"][0]["record_window"]["date_to"] = "2026-10-22"
    else:
        damaged["scope_governance_hash"] = "f" * 64
    with pytest.raises(HTTPException) as error:
        validate_dictionary_scope(damaged, current)
    assert error.value.status_code == status
