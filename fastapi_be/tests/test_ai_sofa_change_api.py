"""Separate SOFA change HTTP/JWT authorization, frozen audit and real SQL rollback."""

import datetime

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI

from app.ai import governance
from app.ai.models import AIAuditEvent
from app.ai.sofa_models import AISofaChangeAssessment
from app.database import get_db
from app.routers import ai_sofa_change as routes
from tests.test_ai_sofa_change_sources import assessment_case as assessment_case
from tests.test_ai_sofa_change_sources import body
from tests.test_ai_sofa_change_sources import change_case as change_case
from tests.test_ai_sofa_change_sources import observation_case as observation_case
from tests.test_ai_sofa_change_sources import sofa_case as sofa_case
from tests.test_ai_sofa_change_sources import source_case as source_case
from tests.test_inpatient_respiratory_contract import NOTE


@pytest_asyncio.fixture
async def change_client(db_session):
    app = FastAPI()
    app.include_router(routes.router, prefix="/api")

    def override():
        yield db_session

    app.dependency_overrides[get_db] = override
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://synthetic-sofa-change") as client:
        yield client


def scope(case):
    return {"patient_id": case["patient_id"], "admission_id": case["admission"].admission_id}


async def register(client, case, headers):
    response = await client.post("/api/ai/sofa-change-assessments", headers=headers, json=body(case))
    assert response.status_code == 200, response.text
    return response.json()["data"]


@pytest.mark.asyncio
async def test_real_change_candidates_create_detail_list_and_super_audit(change_client, change_case, auth_headers, db_session):
    case = change_case
    headers = auth_headers(case["doctor"].username)
    values = {key: value for key, value in body(case).items() if key in routes.sources.ChangeCandidatesRequest.model_fields}
    candidates = await change_client.post("/api/ai/sofa-change-assessments/candidates", headers=headers, json=values)
    assert candidates.status_code == 200 and candidates.json()["data"]["can_sign"] is True
    assert candidates.json()["data"]["infection_sources"][0]["support_source_id"] == case["infection"].support_source_id
    data = await register(change_client, case, headers)
    assert data["eligible"] is data["can_revoke"] is True
    detail = await change_client.get(f"/api/ai/sofa-change-assessments/{data['change_assessment_id']}", headers=headers, params=scope(case))
    assert detail.status_code == 200 and detail.json()["data"] == data
    listing = await change_client.get("/api/ai/sofa-change-assessments", headers=headers, params=scope(case))
    assert listing.status_code == 200
    item = next(item for item in listing.json()["data"]["items"] if item["change_assessment_id"] == data["change_assessment_id"])
    assert "snapshot" not in item and "specialist_source" not in item
    audited = await change_client.get(f"/api/ai/admin/sofa-change-assessments/{data['change_assessment_id']}", headers=auth_headers(case["seed"]["super_admin_user"].username))
    assert audited.status_code == 200 and audited.json()["data"] == data
    assert db_session.query(AIAuditEvent).filter_by(action="sofa_change_assessment.create", target=data["change_assessment_id"]).count() == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["nurse_user", "admin_user", "super_admin_user"])
async def test_pure_management_or_nurse_cannot_sign_infection_related_sofa_change(change_client, change_case, auth_headers, role):
    case = change_case
    response = await change_client.post("/api/ai/sofa-change-assessments", headers=auth_headers(case["seed"][role].username), json=body(case))
    assert response.status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["patient_id", "page", "page_size"])
@pytest.mark.parametrize("value", ["1.0", "true", "1e0"])
async def test_change_query_scalars_reject_noninteger_lexemes(change_client, change_case, auth_headers, field, value):
    response = await change_client.get("/api/ai/sofa-change-assessments", headers=auth_headers(change_case["doctor"].username), params={**scope(change_case), field: value})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_cross_patient_or_original_admission_cannot_read_change(change_client, change_case, auth_headers):
    case = change_case
    headers = auth_headers(case["doctor"].username)
    data = await register(change_client, case, headers)
    for changes in ({"patient_id": case["seed"]["patient2"].patient_id}, {"admission_id": case["other"].admission_id}):
        response = await change_client.get(f"/api/ai/sofa-change-assessments/{data['change_assessment_id']}", headers=headers, params={**scope(case), **changes})
        assert response.status_code in (403, 404, 409)


@pytest.mark.asyncio
async def test_non_super_governance_forbidden_and_stale_infection_redacted_only_for_ordinary_reader(change_client, change_case, auth_headers, db_session):
    case = change_case
    headers = auth_headers(case["doctor"].username)
    super_headers = auth_headers(case["seed"]["super_admin_user"].username)
    data = await register(change_client, case, headers)
    for url in ("/api/ai/admin/sofa-change-assessments", f"/api/ai/admin/sofa-change-assessments/{data['change_assessment_id']}"):
        denied = await change_client.get(url, headers=headers)
        assert denied.status_code == 403
    from app import inpatient_support_common as common

    common.revoke_source(db_session, case["doctor"], "infection_episode", case["infection"].support_source_id, {**scope(case), "expected_revision": 1, "reason": NOTE})
    db_session.commit()
    ordinary = await change_client.get(f"/api/ai/sofa-change-assessments/{data['change_assessment_id']}", headers=headers, params=scope(case))
    assert ordinary.status_code == 200 and ordinary.json()["data"]["snapshot"] is ordinary.json()["data"]["specialist_source"] is None
    audit = await change_client.get(f"/api/ai/admin/sofa-change-assessments/{data['change_assessment_id']}", headers=super_headers)
    assert audit.status_code == 200
    frozen = audit.json()["data"]
    assert frozen["eligible"] is False and frozen["can_revoke"] is True and frozen["specialist_source"] == data["specialist_source"]
    revoked = await change_client.post(f"/api/ai/sofa-change-assessments/{data['change_assessment_id']}/revoke", headers=super_headers, json={**scope(case), "expected_revision": 1, "reason": NOTE})
    assert revoked.status_code == 200 and revoked.json()["data"]["revision"] == 2
    assert revoked.json()["data"]["specialist_source"] == data["specialist_source"]


@pytest.mark.asyncio
async def test_change_author_cas_revoke_audits_exactly_once(change_client, change_case, auth_headers, db_session):
    case = change_case
    headers = auth_headers(case["doctor"].username)
    data = await register(change_client, case, headers)
    url = f"/api/ai/sofa-change-assessments/{data['change_assessment_id']}/revoke"
    values = {**scope(case), "expected_revision": 1, "reason": NOTE}
    first = await change_client.post(url, headers=headers, json=values)
    second = await change_client.post(url, headers=headers, json=values)
    assert first.status_code == 200 and first.json()["data"]["revision"] == 2 and second.status_code == 409
    assert db_session.query(AIAuditEvent).filter_by(action="sofa_change_assessment.revoke", target=data["change_assessment_id"]).count() == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["create", "revoke"])
async def test_actual_sql_audit_not_null_failure_rolls_back_change_and_audit(change_client, change_case, auth_headers, db_session, monkeypatch, action):
    case = change_case
    headers = auth_headers(case["doctor"].username)
    data = await register(change_client, case, headers) if action == "revoke" else None
    before, audits = db_session.query(AISofaChangeAssessment).count(), db_session.query(AIAuditEvent).count()

    def invalid_audit(db, *args, **kwargs):
        db.add(AIAuditEvent(actor_id=args[0], action=None, target="synthetic-sofa-change-sql-failure", detail_json="{}", create_time=datetime.datetime.now(datetime.UTC).replace(tzinfo=None)))

    monkeypatch.setattr(governance, "audit", invalid_audit)
    url = f"/api/ai/sofa-change-assessments/{data['change_assessment_id']}/revoke" if data else "/api/ai/sofa-change-assessments"
    values = {**scope(case), "expected_revision": 1, "reason": NOTE} if data else body(case)
    response = await change_client.post(url, headers=headers, json=values)
    assert response.status_code == 409, response.text
    assert db_session.query(AISofaChangeAssessment).count() == before and db_session.query(AIAuditEvent).count() == audits
    if data:
        row = db_session.get(AISofaChangeAssessment, data["change_assessment_id"])
        assert row.status == "active" and row.revision == 1 and row.revoked_by is row.revoked_at is None


@pytest.mark.asyncio
async def test_change_own_body_corruption_rejects_even_super_frozen_audit(change_client, change_case, auth_headers, db_session):
    case = change_case
    data = await register(change_client, case, auth_headers(case["doctor"].username))
    db_session.get(AISofaChangeAssessment, data["change_assessment_id"]).projection_hash = "0" * 64
    db_session.commit()
    headers = auth_headers(case["seed"]["super_admin_user"].username)
    audited = await change_client.get(f"/api/ai/admin/sofa-change-assessments/{data['change_assessment_id']}", headers=headers)
    assert audited.status_code == 409
