"""Main/JWT/SQLite with the new registry router explicitly mounted for tests.

This does not claim the Source catalog/runtime has been integrated in product
main. Routes are restored after every test; no original route matrix is edited.
"""

import datetime as dt

import pytest

from app.ai import research_cohort_sources as sources
from app.ai.models import AIAuditEvent
from app.ai.research_cohort_models import AIResearchStudyScope
from app.models import MedicalRecord, Patient, Registration
from tests.test_ai_research_cohort_contract import BASIS
from tests.test_ai_research_cohort_sources import manual_body
from tests.test_ai_research_cohort_sources import research_case as research_case  # noqa: F401


@pytest.fixture
def mounted_research_router():
    from app.main import app
    from app.routers.ai_research_cohort_sources import router

    previous = list(app.router.routes)
    app.include_router(router, prefix="/api")
    try:
        yield
    finally:
        app.router.routes[:] = previous
        app.openapi_schema = None


@pytest.mark.asyncio
@pytest.mark.parametrize("microsecond", [0, 123456])
async def test_actual_main_jwt_five_registry_routes_keep_utc6_and_literal_original_without_clinical_writes(
    db_session, research_case, async_client, auth_headers, mounted_research_router, monkeypatch, microsecond
):
    db, case = db_session, research_case
    monkeypatch.setattr(sources, "utcnow", lambda: dt.datetime(2026, 10, 21, 12, 0, 0, microsecond))
    headers = auth_headers(case["super_admin_user"].username)
    reviewer = auth_headers(case["reviewer"].username)
    counts = {model: db.query(model).count() for model in (Patient, MedicalRecord, Registration)}
    body = {**case["scope_request"], "authorization_basis": BASIS + "\ufeff\r\n🧪原字面量"}
    made = await async_client.post("/api/ai/research-cohort/scopes", headers=headers, json=body)
    assert made.status_code == 200, made.text
    original = made.json()["data"]
    identifier = original["scope_id"]
    assert original["created_at"].endswith(f".{microsecond:06}Z")
    assert original["original"]["payload"]["authorization_basis"] == body["authorization_basis"]
    assert original["authorization_reviewed_by"] is None
    response = await async_client.get("/api/ai/research-cohort/scopes/" + identifier, headers=headers)
    assert response.status_code == 200 and response.json()["data"] == original
    response = await async_client.post("/api/ai/research-cohort/scopes/" + identifier + "/authorization-review", headers=reviewer, json=manual_body(original))
    assert response.status_code == 200, response.text
    assert response.json()["data"]["status"] == "draft"
    response = await async_client.post("/api/ai/research-cohort/scopes/" + identifier + "/review", headers=headers, json={"expected_revision": 1, "decision": "publish", "basis_note": BASIS})
    assert response.status_code == 200, response.text
    assert response.json()["data"]["eligible"] and response.json()["data"]["authorization_reviewer_current"] is True
    response = await async_client.post("/api/ai/research-cohort/scopes/" + identifier + "/revoke", headers=reviewer, json={"expected_revision": 2, "basis_note": BASIS})
    assert response.status_code == 200, response.text
    assert response.json()["data"]["status"] == "revoked" and response.json()["data"]["original"] is not None
    assert {model: db.query(model).count() for model in counts} == counts


@pytest.mark.asyncio
async def test_actual_main_rejects_patient_and_ordinary_foreign_original_and_boolean_cas_without_audit_write(db_session, research_case, async_client, auth_headers, mounted_research_router):
    db, case = db_session, research_case
    sup = auth_headers(case["super_admin_user"].username)
    response = await async_client.post("/api/ai/research-cohort/scopes", headers=auth_headers(case["patient_user"].username), json=case["scope_request"])
    assert response.status_code == 403
    response = await async_client.post("/api/ai/research-cohort/scopes", headers=sup, json=case["scope_request"])
    assert response.status_code == 200, response.text
    identifier = response.json()["data"]["scope_id"]
    before = db.query(AIAuditEvent).count()
    response = await async_client.get("/api/ai/research-cohort/scopes/" + identifier, headers=auth_headers(case["admin_user"].username))
    assert response.status_code == 403
    response = await async_client.post("/api/ai/research-cohort/scopes/" + identifier + "/review", headers=sup, json={"expected_revision": True, "decision": "publish", "basis_note": BASIS})
    assert response.status_code == 422
    assert db.query(AIAuditEvent).count() == before
    assert db.get(AIResearchStudyScope, identifier).status == "draft"
