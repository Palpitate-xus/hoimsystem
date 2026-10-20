"""Real JWT/HTTP clinical SOFA governance and SQL audit transaction boundaries."""

import datetime
import json

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI

from app.ai import governance
from app.ai.models import AIAuditEvent
from app.ai.sofa_models import AISofaAssessment
from app.database import get_db
from app.models import NursingRecord
from app.routers import ai_sofa as routes
from tests.test_ai_sofa_sources import assessment_case as assessment_case
from tests.test_ai_sofa_sources import observation_case as observation_case
from tests.test_ai_sofa_sources import period
from tests.test_ai_sofa_sources import sofa_case as sofa_case
from tests.test_ai_sofa_sources import source_case as source_case
from tests.test_inpatient_respiratory_contract import NOTE


@pytest_asyncio.fixture
async def sofa_client(db_session):
    app = FastAPI()
    app.include_router(routes.router, prefix="/api")

    def override():
        yield db_session

    app.dependency_overrides[get_db] = override
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://synthetic-sofa") as client:
        yield client


def scope(case):
    return {"patient_id": case["patient_id"], "admission_id": case["admission"].admission_id}


async def register(client, case, headers):
    response = await client.post("/api/ai/sofa-assessments", headers=headers, json=case["request"])
    assert response.status_code == 200, response.text
    return response.json()["data"]


@pytest.mark.asyncio
async def test_actual_http_candidates_doctor_sign_current_detail_and_metadata_list(sofa_client, assessment_case, auth_headers, db_session):
    case = assessment_case
    headers = auth_headers(case["doctor"].username)
    candidate = await sofa_client.post("/api/ai/sofa-assessments/candidates", headers=headers, json=period(case))
    assert candidate.status_code == 200 and candidate.json()["data"]["can_sign"] is True
    assert len(candidate.json()["data"]["manifest"]["members"]) == 6
    data = await register(sofa_client, case, headers)
    assert data["eligible"] is data["can_revoke"] is True
    detail = await sofa_client.get(f"/api/ai/sofa-assessments/{data['assessment_id']}", headers=headers, params=scope(case))
    assert detail.status_code == 200 and detail.json()["data"] == data
    listing = await sofa_client.get("/api/ai/sofa-assessments", headers=headers, params=scope(case))
    assert listing.status_code == 200
    item = next(item for item in listing.json()["data"]["items"] if item["assessment_id"] == data["assessment_id"])
    assert item["content_hash"] == data["content_hash"]
    assert item.get("snapshot") is item.get("specialist_source") is None
    audit = db_session.query(AIAuditEvent).filter_by(target=data["assessment_id"], action="sofa_assessment.create").one()
    assert json.loads(audit.detail_json)["manifest_digest"] == data["manifest_digest"]


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["nurse_user", "admin_user", "super_admin_user"])
async def test_creation_requires_real_doctor_even_with_super_or_clinical_access(sofa_client, assessment_case, auth_headers, db_session, role):
    case = assessment_case
    db_session.add(NursingRecord(patient_id=case["patient_id"], admission_id=case["admission"].admission_id, nurse_id=case["seed"]["nurse_user"].user_id, note="合成实际照护"))
    db_session.commit()
    headers = auth_headers(case["seed"][role].username)
    candidate = await sofa_client.post("/api/ai/sofa-assessments/candidates", headers=headers, json=period(case))
    if candidate.status_code == 200:
        assert candidate.json()["data"]["can_sign"] is False
    response = await sofa_client.post("/api/ai/sofa-assessments", headers=headers, json=case["request"])
    assert response.status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["patient_id", "page", "page_size"])
@pytest.mark.parametrize("value", ["1.0", "true", "1e0"])
async def test_query_positive_integers_do_not_coerce_decimal_boolean_or_exponent(sofa_client, assessment_case, auth_headers, field, value):
    response = await sofa_client.get("/api/ai/sofa-assessments", headers=auth_headers(assessment_case["doctor"].username), params={**scope(assessment_case), field: value})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_cross_patient_and_other_original_admission_never_reuse_assessment(sofa_client, assessment_case, auth_headers):
    case = assessment_case
    headers = auth_headers(case["doctor"].username)
    data = await register(sofa_client, case, headers)
    url = f"/api/ai/sofa-assessments/{data['assessment_id']}"
    for changes in ({"patient_id": case["seed"]["patient2"].patient_id}, {"admission_id": case["other"].admission_id}):
        response = await sofa_client.get(url, headers=headers, params={**scope(case), **changes})
        assert response.status_code in (403, 404, 409)
        assert "snapshot" not in response.json()


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["doctor", "nurse_user", "admin_user"])
async def test_only_current_super_can_list_and_audit_all_frozen_assessments(sofa_client, assessment_case, auth_headers, role):
    case = assessment_case
    data = await register(sofa_client, case, auth_headers(case["doctor"].username))
    actor = case["doctor"] if role == "doctor" else case["seed"][role]
    for url in ("/api/ai/admin/sofa-assessments", f"/api/ai/admin/sofa-assessments/{data['assessment_id']}"):
        response = await sofa_client.get(url, headers=auth_headers(actor.username))
        assert response.status_code == 403


@pytest.mark.asyncio
async def test_stale_parent_ordinary_detail_redacts_full_facts_but_super_preserves_original(sofa_client, assessment_case, auth_headers, db_session):
    case = assessment_case
    headers = auth_headers(case["doctor"].username)
    data = await register(sofa_client, case, headers)
    case["lab_report"].audit_status = 0
    db_session.commit()
    ordinary = await sofa_client.get(f"/api/ai/sofa-assessments/{data['assessment_id']}", headers=headers, params=scope(case))
    assert ordinary.status_code == 200
    redacted = ordinary.json()["data"]
    assert redacted["eligible"] is False and redacted["snapshot"] is redacted["specialist_source"] is None
    audit = await sofa_client.get(f"/api/ai/admin/sofa-assessments/{data['assessment_id']}", headers=auth_headers(case["seed"]["super_admin_user"].username))
    assert audit.status_code == 200
    frozen = audit.json()["data"]
    assert frozen["eligible"] is False and frozen["can_revoke"] is True
    assert frozen["snapshot"] == data["snapshot"] and frozen["specialist_source"] == data["specialist_source"]


@pytest.mark.asyncio
async def test_original_author_cas_revoke_is_atomic_and_not_replayed(sofa_client, assessment_case, auth_headers, db_session):
    case = assessment_case
    headers = auth_headers(case["doctor"].username)
    data = await register(sofa_client, case, headers)
    url = f"/api/ai/sofa-assessments/{data['assessment_id']}/revoke"
    values = {**scope(case), "expected_revision": 1, "reason": NOTE}
    response = await sofa_client.post(url, headers=headers, json=values)
    assert response.status_code == 200 and response.json()["data"]["revision"] == 2
    duplicate = await sofa_client.post(url, headers=headers, json=values)
    assert duplicate.status_code == 409
    assert db_session.query(AIAuditEvent).filter_by(target=data["assessment_id"], action="sofa_assessment.revoke").count() == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["create", "revoke"])
async def test_actual_invalid_sql_audit_rolls_back_both_source_and_audit(sofa_client, assessment_case, auth_headers, db_session, monkeypatch, action):
    case = assessment_case
    headers = auth_headers(case["doctor"].username)
    data = await register(sofa_client, case, headers) if action == "revoke" else None
    before, audit_before = db_session.query(AISofaAssessment).count(), db_session.query(AIAuditEvent).count()

    def invalid_audit(db, *args, **kwargs):
        db.add(AIAuditEvent(actor_id=args[0], action=None, target="synthetic-sofa-audit-failure", detail_json="{}", create_time=datetime.datetime.now(datetime.UTC).replace(tzinfo=None)))

    monkeypatch.setattr(governance, "audit", invalid_audit)
    url = f"/api/ai/sofa-assessments/{data['assessment_id']}/revoke" if data else "/api/ai/sofa-assessments"
    values = {**scope(case), "expected_revision": 1, "reason": NOTE} if data else case["request"]
    response = await sofa_client.post(url, headers=headers, json=values)
    assert response.status_code == 409, response.text
    assert db_session.query(AISofaAssessment).count() == before and db_session.query(AIAuditEvent).count() == audit_before
    if data:
        row = db_session.get(AISofaAssessment, data["assessment_id"])
        assert row.status == "active" and row.revision == 1 and row.revoked_at is row.revoked_by is None


@pytest.mark.asyncio
async def test_corrupted_own_full_hash_is_never_returned_to_super_as_intact_frozen_evidence(sofa_client, assessment_case, auth_headers, db_session):
    case = assessment_case
    data = await register(sofa_client, case, auth_headers(case["doctor"].username))
    db_session.get(AISofaAssessment, data["assessment_id"]).content_hash = "0" * 64
    db_session.commit()
    headers = auth_headers(case["seed"]["super_admin_user"].username)
    audited = await sofa_client.get(f"/api/ai/admin/sofa-assessments/{data['assessment_id']}", headers=headers)
    assert audited.status_code == 409
    revoked = await sofa_client.post(f"/api/ai/sofa-assessments/{data['assessment_id']}/revoke", headers=headers, json={**scope(case), "expected_revision": 1, "reason": NOTE})
    assert revoked.status_code == 409
