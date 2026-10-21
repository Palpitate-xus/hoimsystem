"""Actual main+JWT router mount, whole Case proof and withdrawn research body."""

import pytest
from sqlalchemy import event

from app.ai.research_cohort_models import AIResearchCohortCase
from app.ai.research_cohort_registry import review_registry_original
from app.models import MedicalRecord, Patient, Registration
from tests.test_ai_research_cohort_cases import case_request
from tests.test_ai_research_cohort_collection import clinical_case
from tests.test_ai_research_cohort_contract import BASIS
from tests.test_ai_research_cohort_registry import permitted
from tests.test_ai_research_cohort_sources import research_case as research_case  # noqa: F401
from tests.test_ai_research_cohort_sources_http import mounted_research_router as mounted_research_router  # noqa: F401


@pytest.mark.asyncio
async def test_actual_jwt_preview_create_list_publish_get_revoke_preserve_full_proof_and_never_write_clinical_records(db_session, research_case, async_client, auth_headers, mounted_research_router):
    db, case = db_session, research_case
    case["scope_request"]["data_families"] = ["medical_records", "patient_demographics", "registrations"]
    scope, _, permission = permitted(db, case)
    clinical_case(db, case)
    before = {m: db.query(m).count() for m in (Patient, Registration, MedicalRecord)}
    admin = auth_headers(case["admin_user"].username)
    sup = auth_headers(case["super_admin_user"].username)
    base = "/api/ai/research-cohort/cases"
    preview = await async_client.post(base + "/preview", headers=admin, json=case_request(scope))
    assert preview.status_code == 200, preview.text
    data = preview.json()["data"]
    response = await async_client.post(base, headers=admin, json={"request": data["request"], "expected_collection_digest": data["expected_collection_digest"], "basis_note": BASIS + "\ufeff\r\n🧪"})
    assert response.status_code == 200, response.text
    draft = response.json()["data"]
    identifier = draft["case_id"]
    assert draft["snapshot"]["creation_basis_note"].endswith("\ufeff\r\n🧪")
    assert draft["created_at"].endswith("Z") and len(draft["created_at"]) == 27
    response = await async_client.get(base, headers=admin, params={"scope_id": scope["scope_id"]})
    assert response.status_code == 200 and response.json()["data"]["total"] == 1
    row = response.json()["data"]["items"][0]
    assert row["case_id"] == identifier and row["detail_required"] and "snapshot" not in row and "review_basis_note" not in row
    response = await async_client.post(base + "/" + identifier + "/review", headers=sup, json={"expected_revision": 1, "decision": "publish", "basis_note": BASIS})
    assert response.status_code == 200, response.text
    # Technical governance is not a clinical grant even in a current Super.
    assert response.json()["data"]["snapshot"] is None
    response = await async_client.get(base + "/" + identifier, headers=admin)
    assert response.status_code == 200 and response.json()["data"]["eligible"], response.text
    published = response.json()["data"]
    assert published["public_source"]["counts"]["recorded_true"] == 1
    # A real authorization withdrawal hides quotations/originals for everyone.
    review_registry_original(db, case["super_admin_user"], "authorization", permission["source_record_id"], {"expected_revision": 2, "basis_note": BASIS}, revoke=True)
    for headers, query in ((admin, ""), (sup, "?audit_only=true")):
        response = await async_client.get(base + "/" + identifier + query, headers=headers)
        assert response.status_code == 200, response.text
        actual = response.json()["data"]
        assert actual["snapshot"] is None and actual["public_source"] is None and actual["local_resolution"] is None
        assert "否认胸痛" not in response.text
    response = await async_client.post(base + "/" + identifier + "/revoke", headers=sup, json={"expected_revision": 2, "basis_note": BASIS})
    assert response.status_code == 200 and response.json()["data"]["status"] == "revoked", response.text
    assert {m: db.query(m).count() for m in before} == before


@pytest.mark.asyncio
async def test_actual_body_permission_denial_precedes_task_snapshot_sql_while_super_audit_only_verifies_bytes(db_session, research_case, async_client, auth_headers, mounted_research_router):
    from tests.test_ai_research_cohort_cases import published

    db, case = db_session, research_case
    _, _, permission, _, made = published(db, case)
    review_registry_original(db, case["super_admin_user"], "authorization", permission["source_record_id"], {"expected_revision": 2, "basis_note": BASIS}, revoke=True)
    statements = []

    def seen(conn, cursor, statement, params, context, many):
        statements.append(statement)

    event.listen(db.bind, "before_cursor_execute", seen)
    try:
        response = await async_client.get("/api/ai/research-cohort/cases/" + made["case_id"], headers=auth_headers(case["admin_user"].username))
        assert response.status_code == 200 and response.json()["data"]["snapshot"] is None
    finally:
        event.remove(db.bind, "before_cursor_execute", seen)
    assert not any(s.lstrip().upper().startswith("SELECT") and "hoimsystem_ai_research_cohort_case.snapshot_json" in s for s in statements)


@pytest.mark.asyncio
async def test_actual_case_http_invalid_scope_family_cas_and_foreign_inputs_never_create_partial_case(db_session, research_case, async_client, auth_headers, mounted_research_router):
    db, case = db_session, research_case
    case["scope_request"]["data_families"] = ["patient_demographics"]
    scope, _, _ = permitted(db, case)
    before = db.query(AIResearchCohortCase).count()
    admin = auth_headers(case["admin_user"].username)
    base = "/api/ai/research-cohort/cases"
    response = await async_client.post(base + "/preview", headers=admin, json=case_request(scope))
    assert response.status_code == 422
    response = await async_client.post(base + "/preview", headers=admin, json={**case_request(scope), "patient_ids": [999999]})
    assert response.status_code == 422
    response = await async_client.get(base + "/NOT-A-UUID", headers=admin)
    assert response.status_code == 422
    assert db.query(AIResearchCohortCase).count() == before


@pytest.mark.asyncio
async def test_technical_directory_never_selects_large_snapshot_projection_or_returns_free_text(db_session, research_case, async_client, auth_headers, mounted_research_router):
    from tests.test_ai_research_cohort_cases import published

    db, case = db_session, research_case
    scope, _, _, _, made = published(db, case)
    statements = []

    def seen(conn, cursor, statement, params, context, many):
        statements.append(statement)

    event.listen(db.bind, "before_cursor_execute", seen)
    try:
        response = await async_client.get("/api/ai/research-cohort/cases", headers=auth_headers(case["admin_user"].username), params={"scope_id": scope["scope_id"], "size": 1})
        assert response.status_code == 200, response.text
    finally:
        event.remove(db.bind, "before_cursor_execute", seen)
    assert not any("hoimsystem_ai_research_cohort_case.snapshot_json" in s or "hoimsystem_ai_research_cohort_case.projection_json" in s for s in statements)
    assert response.json()["data"]["items"][0]["case_id"] == made["case_id"]
    assert "creation_basis_note" not in response.text and "否认胸痛" not in response.text
