"""Authorized pharmacists reach76 without broadening the original74 registry."""

import json
import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import event

from app.ai.research_cohort_registry import create_registry_original, review_registry_original
from app.models import User
from tests.test_ai_admin_write_authority import change_subject, restore_subject, subject
from tests.test_ai_research_cohort_collection import clinical_case
from tests.test_ai_research_cohort_contract import BASIS
from tests.test_ai_research_cohort_registry import acl_request, auth_request, permitted, publish
from tests.test_ai_research_cohort_sources import research_case as research_case
from tests.test_ai_research_variables_contract import definition
from tests.test_ai_research_variables_dictionary import definition_review, technical_review

BASE = "/api/ai/research-variables"


@pytest.fixture
def pharmacist_scope_case(db_session, research_case, request):
    case = research_case
    case["scope_request"]["patient_ids"] = sorted([case["patient"].patient_id, case["patient2"].patient_id])
    case["scope_request"]["proposed_user_ids"] = sorted(set(case["scope_request"]["proposed_user_ids"] + [case["pharmacist_user"].user_id]))
    case["scope_request"]["permitted_uses"] = [getattr(request, "param", "research_variable_extraction")]
    scope, _, first = permitted(db_session, case)
    second = publish(
        db_session,
        case,
        "authorization",
        create_registry_original(db_session, case["super_admin_user"], "authorization", {**auth_request(case, scope), "patient_id": case["patient2"].patient_id}),
        manual=True,
    )
    for actor in (case["pharmacist_user"], case["super_admin_user"], case["reviewer"]):
        publish(db_session, case, "acl", create_registry_original(db_session, case["super_admin_user"], "acl", {**acl_request(case, scope), "user_id": actor.user_id}))
    return case, scope, (first, second)


def observe_no_clinical_body(db):
    columns = []

    def observe(conn, cursor, sql, parameters, context, many):
        if sql.lstrip().lower().startswith("select"):
            columns.extend(column[0] for column in cursor.description or [])

    event.listen(db.bind, "after_cursor_execute", observe)
    return columns, observe


def assert_no_clinical_body(columns):
    private = ("symptom", "result", "source_json", "snapshot_json", "projection_json", "dictionary_json", "sex", "phone", "address", "identity")
    assert not any(name == key or name.endswith("_" + key) for name in columns for key in private), columns


@pytest.mark.asyncio
async def test_registered_pharmacist_can_resolve76_context_then_author_dictionary_and_batch_with_real_independent_reviews(async_client, db_session, pharmacist_scope_case, auth_headers):
    case, scope, _ = pharmacist_scope_case
    pharmacist = auth_headers(case["pharmacist_user"].username)
    # The existing74 public registry and its four-role contract stay closed.
    for path in ("/api/ai/research-cohort/scopes", "/api/ai/research-cohort/scopes/" + scope["scope_id"]):
        assert (await async_client.get(path, headers=pharmacist)).status_code == 403
    columns, observe = observe_no_clinical_body(db_session)
    try:
        response = await async_client.get(BASE + "/scopes/" + scope["scope_id"], headers=pharmacist)
    finally:
        event.remove(db_session.bind, "after_cursor_execute", observe)
    assert response.status_code == 200, response.text
    value = response.json()["data"]
    assert value["scope_id"] == scope["scope_id"] and value["eligible"] is True and value["audit_only"] is False
    assert value["original"] == scope["original"]
    assert value["original"]["payload"]["patient_ids"] == sorted([case["patient"].patient_id, case["patient2"].patient_id])
    assert_no_clinical_body(columns)
    reference = {"scope_id": value["scope_id"], "scope_content_hash": value["content_hash"], "scope_governance_hash": value["governance_hash"]}
    made = await async_client.post(BASE + "/dictionaries", headers=pharmacist, json={**reference, "title": "药师明确变量字典", "purpose": BASIS, "basis_note": BASIS, "variables": [definition()]})
    assert made.status_code == 200, made.text
    metadata = made.json()["data"]["metadata"]
    assert metadata["created_by"] == case["pharmacist_user"].user_id
    identifier = metadata["dictionary_id"]
    reviewed = await async_client.post(BASE + f"/dictionaries/{identifier}/definition-review", headers=auth_headers(case["reviewer"].username), json=definition_review(metadata))
    assert reviewed.status_code == 200, reviewed.text
    published = await async_client.post(BASE + f"/dictionaries/{identifier}/review", headers=auth_headers(case["super_admin_user"].username), json=technical_review())
    assert published.status_code == 200, published.text
    dictionary = published.json()["data"]["metadata"]
    definition_part = await async_client.get(BASE + f"/dictionaries/{identifier}/parts/definition", headers=pharmacist)
    assert definition_part.status_code == 200, definition_part.text
    dictionary_proof = definition_part.json()["data"]["value"]
    assert dictionary_proof["content_hash"] == dictionary["content_hash"]
    clinical_case(db_session, case)
    body = {
        **reference,
        "variable_dictionary_id": identifier,
        "dictionary_content_hash": dictionary["content_hash"],
        "dictionary_governance_hash": dictionary_proof["governance_hash"],
        "patient_ids": [case["patient"].patient_id],
    }
    preview = await async_client.post(BASE + "/batches/preview", headers=pharmacist, json=body)
    assert preview.status_code == 200, preview.text
    captured = await async_client.post(BASE + "/batches", headers=pharmacist, json={**body, "basis_note": BASIS})
    assert captured.status_code == 200, captured.text
    batch_id = captured.json()["data"]["metadata"]["batch_id"]
    published = await async_client.post(BASE + f"/batches/{batch_id}/review", headers=auth_headers(case["super_admin_user"].username), json=technical_review())
    assert published.status_code == 200, published.text
    assert (await async_client.get(BASE + f"/batches/{batch_id}/parts/source", headers=pharmacist)).status_code == 200


@pytest.mark.asyncio
async def test_scope_locator_or_super_role_without_own_project_acl_cannot_resolve_context(async_client, db_session, pharmacist_scope_case, auth_headers):
    _, scope, _ = pharmacist_scope_case
    actor = User(username="scope_" + uuid.uuid4().hex[:12], password="synthetic-only", user_role="super_admin")
    db_session.add(actor)
    db_session.commit()
    response = await async_client.get(BASE + "/scopes/" + scope["scope_id"], headers=auth_headers(actor.username))
    assert response.status_code == 403 and "original" not in response.json()


@pytest.mark.asyncio
async def test_scope_resolution_requires_every_declared_patient_even_when_a_batch_would_select_only_the_first(async_client, db_session, pharmacist_scope_case, auth_headers):
    case, scope, permissions = pharmacist_scope_case
    review_registry_original(db_session, case["super_admin_user"], "authorization", permissions[1]["source_record_id"], {"expected_revision": 2, "basis_note": BASIS}, revoke=True)
    response = await async_client.get(BASE + "/scopes/" + scope["scope_id"], headers=auth_headers(case["pharmacist_user"].username))
    assert response.status_code == 403 and "original" not in response.json()


@pytest.mark.asyncio
@pytest.mark.parametrize("pharmacist_scope_case", ["cohort_criteria_review"], indirect=True)
async def test_other_research_use_does_not_grant_variable_scope_resolution(async_client, pharmacist_scope_case, auth_headers):
    case, scope, _ = pharmacist_scope_case
    response = await async_client.get(BASE + "/scopes/" + scope["scope_id"], headers=auth_headers(case["pharmacist_user"].username))
    assert response.status_code == 403


@pytest.mark.parametrize("axis", ("role", "epoch", "username"))
def test_stale_original_subject_is_denied_before_scope_projection(db_session, pharmacist_scope_case, axis):
    from app.ai.research_variables_scope_context import scope_context

    case, scope, _ = pharmacist_scope_case
    actor = case["super_admin_user"]
    original = subject(actor)
    change_subject(db_session, original, axis)
    columns, observe = observe_no_clinical_body(db_session)
    try:
        with pytest.raises(HTTPException) as caught:
            scope_context(db_session, actor, scope["scope_id"])
        assert caught.value.status_code == 403
        assert "scope_json" not in columns
    finally:
        event.remove(db_session.bind, "after_cursor_execute", observe)
        restore_subject(db_session, original)


@pytest.mark.asyncio
async def test_scope_context_rejects_foreign_query_and_ineligible_roles_without_echo(async_client, pharmacist_scope_case, auth_headers):
    case, scope, _ = pharmacist_scope_case
    response = await async_client.get(BASE + "/scopes/" + scope["scope_id"], params={"patient_id": "private-unaccepted-filter"}, headers=auth_headers(case["pharmacist_user"].username))
    assert response.status_code == 422 and "private-unaccepted-filter" not in response.text
    for role in ("nurse_user", "patient_user", "cashier_user"):
        response = await async_client.get(BASE + "/scopes/" + scope["scope_id"], headers=auth_headers(case[role].username))
        assert response.status_code == 403
    missing = await async_client.get(BASE + "/scopes/" + str(uuid.uuid4()), headers=auth_headers("super01"))
    assert missing.status_code == 404 and "original" not in json.loads(missing.text)
