"""Actual JWT/ASGI management API without mounting unfinished feature64 in main."""

import json

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.exc import IntegrityError

from app.ai import bed_facts as facts
from app.ai import governance
from app.ai.bed_models import AIBedSource
from app.ai.models import AIAuditEvent
from app.database import get_db
from app.routers import ai_bed_sources as routes
from tests.conftest import override_get_db
from tests.test_ai_bed_facts import NOTE, create, publish, request
from tests.test_ai_bed_facts import bed_case as bed_case


@pytest_asyncio.fixture
async def bed_http_client():
    app = FastAPI()
    app.include_router(routes.router, prefix="/api")
    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://isolated-bed.test") as client:
        yield client


async def register(client, case, auth_headers, kind="census", actor=None):
    response = await client.post("/api/ai/bed-sources/" + kind, headers=auth_headers((actor or case["director"]).username), json=request(case, kind))
    assert response.status_code == 200, response.text
    return response.json()["data"]


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", facts.KINDS)
async def test_real_three_types_draft_publish_list_and_cas_revoke(bed_http_client, bed_case, auth_headers, db_session, kind):
    case = bed_case
    data = await register(bed_http_client, case, auth_headers, kind)
    assert data["status"] == "draft" and data["eligible"] is False and data["can_record"] is data["can_revoke"] is True
    assert data["can_review"] is data["audit_only"] is False
    url = f"/api/ai/bed-sources/{kind}/{data['source_record_id']}"
    headers = auth_headers(case["super"].username)
    body = {"expected_revision": 1, "expected_content_hash": data["content_hash"], "decision": "publish", "review_basis_note": NOTE}
    response = await bed_http_client.post(url + "/review", headers=headers, json=body)
    assert response.status_code == 200, response.text
    published = response.json()["data"]
    assert published["eligible"] is True and published["revision"] == 2 and published["audit_only"] is True
    assert published["payload"] == data["payload"] and published["content_hash"] == data["content_hash"]
    ordinary = auth_headers(case["director"].username)
    read = await bed_http_client.get(url, headers=ordinary)
    assert read.status_code == 200 and read.json()["data"]["payload"] == data["payload"]
    listing = await bed_http_client.get("/api/ai/bed-sources/" + kind, headers=ordinary, params={"department_id": case["department"].department_id, "ward_id": case["ward"].ward_id})
    assert listing.status_code == 200, listing.text
    item = listing.json()["data"]["items"][0]
    assert item["source_record_id"] == data["source_record_id"]
    assert not any(key in item for key in ("payload", "parent_binding", "review_basis_note", "revoke_reason"))
    revoked = await bed_http_client.post(url + "/revoke", headers=ordinary, json={"expected_revision": 2, "reason": "本人原资料停止用于新预测输入"})
    assert revoked.status_code == 200, revoked.text
    assert revoked.json()["data"]["status"] == "revoked" and revoked.json()["data"]["revision"] == 3
    assert all(revoked.json()["data"][key] is None for key in ("payload", "parent_binding", "review_basis_note", "revoke_reason"))
    stale = await bed_http_client.post(url + "/revoke", headers=ordinary, json={"expected_revision": 2, "reason": "旧版本重放必须失败"})
    assert stale.status_code == 409
    audit = await bed_http_client.get("/api/ai/admin/bed-sources/" + data["source_record_id"], headers=headers)
    assert audit.status_code == 200 and audit.json()["data"]["payload"] == data["payload"] and audit.json()["data"]["eligible"] is False
    assert db_session.query(AIAuditEvent).filter_by(action="bed_source.revoke", target=data["source_record_id"]).count() == 1


@pytest.mark.asyncio
async def test_options_actual_department_scope_no_provider_or_current_bed_count_inference(bed_http_client, bed_case, auth_headers):
    case = bed_case
    headers = auth_headers(case["director"].username)
    catalog = await bed_http_client.get("/api/ai/bed-sources/options", headers=headers)
    assert catalog.status_code == 200
    assert {item["department_id"] for item in catalog.json()["data"]["departments"]} == {case["department"].department_id}
    result = await bed_http_client.get("/api/ai/bed-sources/options", headers=headers, params={"department_id": case["department"].department_id})
    assert result.status_code == 200
    data = result.json()["data"]
    assert data["provider_required"] is False and data["wards"] == [{"ward_id": case["ward"].ward_id, "department_id": case["department"].department_id, "name": "合成病区", "status": 0}]
    assert "bed_count" not in json.dumps(data)
    result = await bed_http_client.get("/api/ai/bed-sources/options", headers=headers, params={"department_id": case["foreign"].department_id})
    assert result.status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize("key", ["department_id", "ward_id", "page", "page_size"])
@pytest.mark.parametrize("value", ["1.0", "true", "1e0"])
async def test_http_query_scalars_are_canonical_positive_integer_lexemes(bed_http_client, bed_case, auth_headers, key, value):
    response = await bed_http_client.get("/api/ai/bed-sources/census", headers=auth_headers(bed_case["director"].username), params={"department_id": bed_case["department"].department_id, key: value})
    assert response.status_code == 422


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", [True, 1.0, "1"])
async def test_http_body_scope_identity_is_strict(bed_http_client, bed_case, auth_headers, bad):
    data = request(bed_case)
    data["ward_id"] = bad
    response = await bed_http_client.post("/api/ai/bed-sources/census", headers=auth_headers(bed_case["director"].username), json=data)
    assert response.status_code == 422


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/ai/admin/bed-sources", "/ai/admin/bed-sources/{id}", "/ai/bed-sources/census/{id}/review"])
async def test_only_current_super_can_review_or_global_audit(bed_http_client, bed_case, auth_headers, path):
    data = await register(bed_http_client, bed_case, auth_headers)
    url = "/api" + path.format(id=data["source_record_id"])
    headers = auth_headers(bed_case["admin"].username)
    if url.endswith("/review"):
        response = await bed_http_client.post(url, headers=headers, json={"expected_revision": 1, "expected_content_hash": data["content_hash"], "decision": "publish", "review_basis_note": NOTE})
    else:
        response = await bed_http_client.get(url, headers=headers)
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_actual_foreign_and_non_author_access_and_bad_kind_or_uuid(bed_http_client, bed_case, auth_headers):
    data = await register(bed_http_client, bed_case, auth_headers, actor=bed_case["admin"])
    ordinary = auth_headers(bed_case["director"].username)
    url = "/api/ai/bed-sources/census/" + data["source_record_id"]
    detail = await bed_http_client.get(url, headers=ordinary)
    assert detail.status_code == 200 and detail.json()["data"]["can_revoke"] is False
    denied = await bed_http_client.post(url + "/revoke", headers=ordinary, json={"expected_revision": 1, "reason": "非作者不得撤销他人原件"})
    assert denied.status_code == 403
    values = request(bed_case)
    values["ward_id"] = bed_case["foreign_ward"].ward_id
    assert (await bed_http_client.post("/api/ai/bed-sources/census", headers=ordinary, json=values)).status_code == 403
    assert (await bed_http_client.get("/api/ai/bed-sources/flow_day/" + data["source_record_id"], headers=ordinary)).status_code == 404
    assert (await bed_http_client.get("/api/ai/bed-sources/census/INVALID", headers=ordinary)).status_code == 422
    assert (await bed_http_client.get("/api/ai/bed-sources/not_a_kind", headers=ordinary, params={"department_id": bed_case["department"].department_id})).status_code == 422


@pytest.mark.asyncio
async def test_actual_stale_parent_redaction_super_own_frozen_and_cas_revoke(bed_http_client, bed_case, auth_headers, db_session):
    case = bed_case
    row = publish(db_session, case, create(db_session, case))
    original = row.payload_json, row.parent_binding_json, row.content_hash
    case["ward"].department_id = case["foreign"].department_id
    db_session.commit()
    url = "/api/ai/bed-sources/census/" + row.source_record_id
    ordinary = await bed_http_client.get(url, headers=auth_headers(case["director"].username))
    assert ordinary.status_code == 200
    data = ordinary.json()["data"]
    assert data["eligible"] is data["can_revoke"] is False and data["exclusion_reasons"] == ["ward_department_binding_changed"]
    assert all(data[key] is None for key in ("payload", "parent_binding", "review_basis_note", "revoke_reason"))
    audit = await bed_http_client.get("/api/ai/admin/bed-sources/" + row.source_record_id, headers=auth_headers(case["super"].username))
    assert audit.status_code == 200 and audit.json()["data"]["payload"] is not None and audit.json()["data"]["can_revoke"] is True
    response = await bed_http_client.post(url + "/revoke", headers=auth_headers(case["super"].username), json={"expected_revision": 2, "reason": "治理失效原件保留完整审计"})
    assert response.status_code == 200 and response.json()["data"]["revision"] == 3
    db_session.expire_all()
    assert original == (row.payload_json, row.parent_binding_json, row.content_hash)


@pytest.mark.asyncio
async def test_super_bad_own_hash_cannot_be_audited_as_intact(bed_http_client, bed_case, auth_headers, db_session):
    row = create(db_session, bed_case)
    row.content_hash = "a" * 64
    db_session.commit()
    response = await bed_http_client.get("/api/ai/admin/bed-sources/" + row.source_record_id, headers=auth_headers(bed_case["super"].username))
    assert response.status_code == 409


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["create", "publish", "revoke"])
async def test_real_http_audit_failure_rolls_back_all_mutation(bed_http_client, bed_case, auth_headers, db_session, monkeypatch, action):
    data = None if action == "create" else await register(bed_http_client, bed_case, auth_headers)
    before = db_session.query(AIBedSource).count()

    def fail(*args, **kwargs):
        raise IntegrityError("synthetic audit SQL failed", {}, RuntimeError("audit"))

    monkeypatch.setattr(governance, "audit", fail)
    with pytest.raises(IntegrityError, match="audit"):
        if action == "create":
            await register(bed_http_client, bed_case, auth_headers)
        else:
            url = "/api/ai/bed-sources/census/" + data["source_record_id"]
            body = (
                {"expected_revision": 1, "expected_content_hash": data["content_hash"], "decision": "publish", "review_basis_note": NOTE}
                if action == "publish"
                else {"expected_revision": 1, "reason": "审计失败必须整体回滚"}
            )
            await bed_http_client.post(url + ("/review" if action == "publish" else "/revoke"), headers=auth_headers(bed_case["super"].username), json=body)
    db_session.expire_all()
    assert db_session.query(AIBedSource).count() == before
    if data:
        assert facts.source_row(db_session, data["source_record_id"]).status == "draft"


@pytest.mark.asyncio
async def test_rejected_original_is_redacted_in_detail_and_metadata_only_list(bed_http_client, bed_case, auth_headers, db_session):
    row = publish(db_session, bed_case, create(db_session, bed_case), decision="reject")
    headers = auth_headers(bed_case["director"].username)
    result = await bed_http_client.get("/api/ai/bed-sources/census/" + row.source_record_id, headers=headers)
    assert result.status_code == 200
    data = result.json()["data"]
    assert data["status"] == "rejected" and data["revision"] == 2 and data["eligible"] is False
    assert all(data[key] is None for key in ("payload", "parent_binding", "review_basis_note", "revoke_reason"))
    result = await bed_http_client.get("/api/ai/bed-sources/census", headers=headers, params={"department_id": row.department_id, "status": "rejected", "page_size": 1})
    assert result.status_code == 200 and result.json()["data"]["total"] == 1
    assert "review_basis_note" not in result.json()["data"]["items"][0]
