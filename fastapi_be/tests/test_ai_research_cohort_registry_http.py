"""Real main app with explicit new-router mount, JWT and actual SQL registry."""

import pytest

from app.ai.models import AIAuditEvent
from app.ai.research_cohort_models import AIResearchPatientAuthorization, AIResearchProjectACL
from tests.test_ai_research_cohort_contract import BASIS
from tests.test_ai_research_cohort_registry import acl_request, auth_request
from tests.test_ai_research_cohort_sources import complete_scope, manual_body
from tests.test_ai_research_cohort_sources import research_case as research_case  # noqa: F401
from tests.test_ai_research_cohort_sources_http import mounted_research_router as mounted_research_router  # noqa: F401


@pytest.mark.asyncio
async def test_actual_jwt_all_acl_and_patient_authorization_routes_separate_three_authorities(db_session, research_case, async_client, auth_headers, mounted_research_router):
    db, case = db_session, research_case
    _, _, scope = complete_scope(db, case)
    sup, admin, reviewer = (auth_headers(case[key].username) for key in ("super_admin_user", "admin_user", "reviewer"))
    base = "/api/ai/research-cohort"
    made = await async_client.post(base + "/project-acls", headers=sup, json=acl_request(case, scope))
    assert made.status_code == 200, made.text
    acl = made.json()["data"]
    aid = acl["source_record_id"]
    response = await async_client.get(base + "/project-acls/" + aid, headers=sup)
    assert response.status_code == 200 and response.json()["data"]["original"] == acl["original"]
    response = await async_client.post(base + "/project-acls/" + aid + "/review", headers=sup, json={"expected_revision": 1, "decision": "publish", "basis_note": BASIS})
    assert response.status_code == 200, response.text
    # An explicit project member can register permission documents, but this
    # is neither actual patient permission nor an IRB/professional certificate.
    made = await async_client.post(base + "/patient-authorizations", headers=admin, json=auth_request(case, scope))
    assert made.status_code == 200, made.text
    authorization = made.json()["data"]
    identifier = authorization["source_record_id"]
    path = base + "/patient-authorizations/" + identifier
    response = await async_client.get(path, headers=admin)
    assert response.status_code == 200 and not response.json()["data"]["eligible"]
    response = await async_client.post(path + "/authorization-review", headers=admin, json=manual_body(authorization))
    assert response.status_code == 409
    response = await async_client.post(path + "/authorization-review", headers=reviewer, json=manual_body(authorization))
    assert response.status_code == 200, response.text
    assert response.json()["data"]["status"] == "draft"
    response = await async_client.post(path + "/review", headers=admin, json={"expected_revision": 1, "decision": "publish", "basis_note": BASIS})
    assert response.status_code == 403
    response = await async_client.post(path + "/review", headers=sup, json={"expected_revision": 1, "decision": "publish", "basis_note": BASIS})
    assert response.status_code == 200 and response.json()["data"]["eligible"], response.text
    response = await async_client.post(path + "/revoke", headers=admin, json={"expected_revision": 2, "basis_note": BASIS})
    assert response.status_code == 200, response.text
    assert response.json()["data"]["original"] is None
    response = await async_client.get(path + "?audit_only=true", headers=sup)
    assert response.status_code == 200 and response.json()["data"]["original"]["governance"]["status"] == "revoked"
    response = await async_client.post(base + "/project-acls/" + aid + "/revoke", headers=sup, json={"expected_revision": 2, "basis_note": BASIS})
    assert response.status_code == 200 and response.json()["data"]["status"] == "revoked"


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["scopes/NOT-A-UUID", "project-acls/00000000000000000000000000000000", "patient-authorizations/1"])
async def test_actual_registry_http_invalid_technical_ids_and_patient_role_do_not_read_or_write_originals(db_session, research_case, async_client, auth_headers, mounted_research_router, path):
    db, case = db_session, research_case
    before = {model: db.query(model).count() for model in (AIResearchPatientAuthorization, AIResearchProjectACL, AIAuditEvent)}
    response = await async_client.get("/api/ai/research-cohort/" + path, headers=auth_headers(case["super_admin_user"].username))
    assert response.status_code == 422
    response = await async_client.post("/api/ai/research-cohort/project-acls", headers=auth_headers(case["patient_user"].username), json={})
    assert response.status_code == 422
    assert {model: db.query(model).count() for model in before} == before
