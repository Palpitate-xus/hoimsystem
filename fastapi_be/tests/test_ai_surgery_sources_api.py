"""Real JWT/isolated ASGI/SQL API; source operations do not mount native execution."""

import json

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, text
from sqlalchemy.exc import IntegrityError

from app.ai import governance
from app.ai.models import AIAuditEvent
from app.ai.surgery_models import AISurgeryPool, AISurgerySource
from app.database import get_db
from app.routers import ai_surgery_sources as routes
from tests.conftest import override_get_db
from tests.test_ai_surgery_facts import NOTE, create, publish, request
from tests.test_ai_surgery_facts import surgery_case as surgery_case


@pytest_asyncio.fixture
async def surgery_http():
    app = FastAPI()
    app.include_router(routes.router, prefix="/api")
    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://isolated-surgery.test") as client:
        yield client


def source_url(row):
    return f"/api/ai/surgery-sources/{row.source_kind}/{row.source_record_id}"


@pytest.mark.asyncio
async def test_actual_clinical_doctor_creates_and_super_publishes_then_author_cas_revokes(surgery_http, surgery_case, auth_headers, db_session):
    case = surgery_case
    response = await surgery_http.post("/api/ai/surgery-sources/case_duration_estimate", headers=auth_headers(case["doctor_user"].username), json=request(case))
    assert response.status_code == 200, response.text
    draft = response.json()["data"]
    assert draft["can_revoke"] and not draft["can_review"] and not draft["eligible_for_new_use"]
    assert draft["signed_by_user_id"] == case["doctor_user"].user_id and draft["signed_at"] == draft["recorded_at"]
    url = "/api/ai/surgery-sources/case_duration_estimate/" + draft["source_record_id"]
    review = {"expected_revision": 1, "expected_content_hash": draft["content_hash"], "decision": "publish", "basis_note": NOTE}
    denied = await surgery_http.post(url + "/review", headers=auth_headers(case["director"].username), json=review)
    assert denied.status_code == 403
    published = await surgery_http.post(url + "/review", headers=auth_headers(case["super"].username), json=review)
    assert published.status_code == 200, published.text
    current = published.json()["data"]
    assert current["eligible_for_new_use"] and current["revision"] == 2
    assert current["reviewed_by"] == case["super"].user_id and current["signed_by_user_id"] == case["doctor_user"].user_id
    listing = await surgery_http.get("/api/ai/surgery-sources/case_duration_estimate", headers=auth_headers(case["doctor_user"].username), params={"pool_id": case["pool"].pool_id})
    assert listing.status_code == 200 and listing.json()["data"]["total"] == 1
    assert all(key not in listing.json()["data"]["items"][0] for key in ("payload", "parent_binding", "review_basis_note", "revoke_reason"))
    revoked = await surgery_http.post(
        url + "/revoke", headers=auth_headers(case["doctor_user"].username), json={"expected_revision": 2, "expected_content_hash": draft["content_hash"], "basis_note": NOTE}
    )
    assert revoked.status_code == 200, revoked.text
    assert revoked.json()["data"]["revision"] == 3
    assert all(revoked.json()["data"][key] is None for key in ("payload", "parent_binding", "review_basis_note", "revoke_reason"))
    replay = await surgery_http.post(url + "/review", headers=auth_headers(case["super"].username), json=review)
    assert replay.status_code == 409
    assert db_session.query(AIAuditEvent).filter_by(action="surgery.source.review", target=draft["source_record_id"]).count() == 1


@pytest.mark.asyncio
async def test_options_separates_clinical_doctor_from_operational_and_super_management(surgery_http, surgery_case, auth_headers):
    case = surgery_case
    result = await surgery_http.get("/api/ai/surgery-sources/options", headers=auth_headers(case["doctor_user"].username))
    assert result.status_code == 200, result.text
    data = result.json()["data"]
    assert data["has_actual_doctor"] and not data["can_record_operational"] and not data["can_review"] and not data["provider_required"]
    assert {item["pool_id"] for item in data["pools"]} == {case["pool"].pool_id}
    denied = await surgery_http.post(
        "/api/ai/surgery-registry/pool",
        headers=auth_headers(case["doctor_user"].username),
        json={"payload": {"kind": "pool", "department_id": case["department"].department_id, "name": "不应创建", "basis_note": NOTE}},
    )
    assert denied.status_code == 403


@pytest.mark.asyncio
async def test_registry_creation_is_super_only_and_anchor_cannot_be_revoked(surgery_http, surgery_case, auth_headers):
    case = surgery_case
    payload = {"payload": {"kind": "resource", "resource_kind": "room", "equipment_id": None, "cssd_instrument_id": None, "label": "合成新固定房间", "basis_note": NOTE}}
    denied = await surgery_http.post("/api/ai/surgery-registry/resource", headers=auth_headers(case["director"].username), json=payload)
    assert denied.status_code == 403
    response = await surgery_http.post("/api/ai/surgery-registry/resource", headers=auth_headers(case["super"].username), json=payload)
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["governance"] is None and not data["can_revoke"] and not data["can_review"]
    response = await surgery_http.post(
        "/api/ai/surgery-registry/resource/" + data["resource_id"] + "/revoke",
        headers=auth_headers(case["super"].username),
        json={"expected_revision": 1, "expected_content_hash": data["content_hash"], "basis_note": NOTE},
    )
    assert response.status_code == 409


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["page", "page_size"])
@pytest.mark.parametrize("value", ["true", "1.0", "1e0"])
async def test_actual_http_pagination_rejects_coercion(surgery_http, surgery_case, auth_headers, name, value):
    response = await surgery_http.get(
        "/api/ai/surgery-sources/case_duration_estimate", headers=auth_headers(surgery_case["doctor_user"].username), params={"pool_id": surgery_case["pool"].pool_id, name: value}
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_foreign_pool_care_and_canonical_ids_do_not_fall_back_to_global_raw_reads(surgery_http, surgery_case, auth_headers, db_session):
    case = surgery_case
    row = create(db_session, case)
    result = await surgery_http.get(source_url(row), headers=auth_headers(case["foreign_user"].username))
    assert result.status_code == 403
    result = await surgery_http.get("/api/ai/surgery-sources/case_duration_estimate/not-a-uuid", headers=auth_headers(case["super"].username))
    assert result.status_code == 422
    result = await surgery_http.get("/api/ai/surgery-sources/duration_observation/" + row.source_record_id, headers=auth_headers(case["super"].username))
    assert result.status_code == 404


@pytest.mark.asyncio
async def test_sql_audit_failure_rolls_back_source_governance(surgery_http, surgery_case, auth_headers, db_session, monkeypatch):
    case = surgery_case
    row = create(db_session, case)
    before = row.content_hash, row.payload_json, row.parent_binding_json

    def fail(db, *args, **kwargs):
        db.add(AIAuditEvent(actor_id=case["super"].user_id, action=None, target="synthetic-failure", detail_json="{}"))

    monkeypatch.setattr(governance, "audit", fail)
    result = await surgery_http.post(
        source_url(row) + "/review", headers=auth_headers(case["super"].username), json={"expected_revision": 1, "expected_content_hash": row.content_hash, "decision": "publish", "basis_note": NOTE}
    )
    assert result.status_code == 409
    db_session.expire_all()
    assert row.status == "draft" and row.revision == 1 and row.reviewed_at is None
    assert before == (row.content_hash, row.payload_json, row.parent_binding_json)
    assert db_session.query(AIAuditEvent).filter_by(target="synthetic-failure").count() == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["demote_super", "change_case"])
async def test_after_real_sql_audit_current_authority_and_parent_are_rechecked_atomically(surgery_http, surgery_case, auth_headers, db_session, mutation):
    case = surgery_case
    row = create(db_session, case)
    source_id, original_hash, super_id, application_id = row.source_record_id, row.content_hash, case["super"].user_id, case["application"].application_id
    fired = []

    def change(connection, cursor, statement, parameters, context, executemany):
        if not fired and statement.lstrip().upper().startswith("INSERT INTO HOIMSYSTEM_AI_AUDIT_EVENT"):
            fired.append(True)
            if mutation == "demote_super":
                connection.execute(text("UPDATE hoimsystem_users SET user_role='admin' WHERE user_id=:id"), {"id": super_id})
            else:
                connection.execute(text("UPDATE hoimsystem_surgery_application SET surgery_name='合成并发父件变更' WHERE application_id=:id"), {"id": application_id})

    event.listen(db_session.bind, "after_cursor_execute", change)
    try:
        result = await surgery_http.post(
            source_url(row) + "/review", headers=auth_headers(case["super"].username), json={"expected_revision": 1, "expected_content_hash": original_hash, "decision": "publish", "basis_note": NOTE}
        )
    finally:
        event.remove(db_session.bind, "after_cursor_execute", change)
    assert fired and result.status_code == (403 if mutation == "demote_super" else 409), result.text
    db_session.expire_all()
    assert row.status == "draft" and row.revision == 1 and case["super"].user_role == "super_admin"
    assert db_session.query(AIAuditEvent).filter_by(action="surgery.source.review", target=source_id).count() == 0


@pytest.mark.asyncio
async def test_invalid_original_parent_is_redacted_but_super_keeps_full_hash_audit(surgery_http, surgery_case, auth_headers, db_session):
    case = surgery_case
    row = publish(db_session, case, create(db_session, case))
    case["application"].surgery_name = "合成新方案原件"
    db_session.commit()
    ordinary = await surgery_http.get(source_url(row), headers=auth_headers(case["doctor_user"].username))
    assert ordinary.status_code == 200
    assert all(ordinary.json()["data"][key] is None for key in ("payload", "parent_binding", "review_basis_note", "revoke_reason"))
    audit = await surgery_http.get(source_url(row), headers=auth_headers(case["super"].username))
    assert audit.status_code == 200 and audit.json()["data"]["payload"] is not None and audit.json()["data"]["can_revoke"]
    assert "patient" not in json.dumps(audit.json()["data"]["payload"])
    assert db_session.query(AISurgerySource).filter_by(source_record_id=row.source_record_id).count() == 1
    assert db_session.query(AISurgeryPool).filter_by(pool_id=case["pool"].pool_id).count() == 1


@pytest.mark.asyncio
async def test_registry_audit_failure_rolls_back_new_anchor_and_gate_bootstrap(surgery_http, surgery_case, auth_headers, db_session, monkeypatch):
    case = surgery_case
    before = db_session.query(AISurgeryPool).count()

    def fail(*args, **kwargs):
        raise IntegrityError("synthetic-audit", {}, RuntimeError("synthetic"))

    monkeypatch.setattr(governance, "audit", fail)
    result = await surgery_http.post(
        "/api/ai/surgery-registry/pool",
        headers=auth_headers(case["super"].username),
        json={"payload": {"kind": "pool", "department_id": case["department"].department_id, "name": "合成事务失败池", "basis_note": NOTE}},
    )
    assert result.status_code == 409 and db_session.query(AISurgeryPool).count() == before
