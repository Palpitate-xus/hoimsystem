from tests.routing import api_routes

"""Product Main/JWT routes and exact independent canonical Source parts."""

import json
import re

import pytest
from fastapi import HTTPException
from sqlalchemy import event

from app.ai import operations_support_registry as r
from app.ai.models import AIAuditEvent
from app.ai.operations_support_models import AIOperationsOriginal
from app.models import MedicalRecord, Patient, Registration
from tests.test_ai_operations_support_registry import request  # noqa: F401
from tests.test_ai_operations_support_registry import source as source
from tests.test_ai_operations_support_releases import actors as actors
from tests.test_ai_operations_support_releases import proposal, review

BASE = "/api/ai/operations-support"


@pytest.fixture
def mounted():

    from app.main import app

    routes = [row for row in api_routes(app.routes) if row.endpoint.__module__ == "app.routers.ai_operations_support_sources"]
    assert len(routes) == 17
    assert len({(method, row.path) for row in routes for method in row.methods}) == 17
    return routes


@pytest.mark.asyncio
async def test_actual_main_jwt_independent_registry_case_parts_and_all_revocations(actors, async_client, auth_headers, mounted, tmp_path):
    db, registrar, creator, reviewer, admin = actors
    names = [person.username for person in (registrar, creator, reviewer, admin)]
    db.commit()
    headers = [auth_headers(name) for name in names]
    clinical_before = {model: db.query(model).count() for model in (Patient, MedicalRecord, Registration)}
    packets = []

    async def call(method, path, which, body=None, bare=False):
        response = await async_client.request(method, BASE + path, headers=headers[which], **({"json": body} if body is not None else {}))
        assert response.status_code == 200, response.text
        packets.append({"method": method, "path": path, "status": response.status_code, "body": response.text, "parts_wire": response.headers.get("X-AI-Parts-Wire")})
        value = response.json()
        if bare:
            assert response.headers["X-AI-Parts-Wire"] == "canonical_json_body_no_envelope"
            assert "code" not in value and "data" not in value
            return value
        return value["data"]

    original = await call("POST", "/originals", 0, request())
    assert await call("GET", "/originals/" + original["original_id"], 0) == original
    full = await call("GET", "/originals/" + original["original_id"] + "/body", 0, bare=True)
    assert full["content_text"] == request()["content_text"] and full["captured_at"].endswith("Z") and len(full["captured_at"]) == 27
    release = await call("POST", "/releases", 1, proposal(original, request()["content_text"]))
    await call("GET", "/releases/" + release["release_id"], 0)
    await call("GET", "/releases/" + release["release_id"] + "/draft", 0, bare=True)
    published = await call("POST", "/releases/" + release["release_id"] + "/review", 2, review(model_processing_allowed=True))
    assert published["status"] == "published" and published["model_processing_allowed"] == 1
    public_document = await call("GET", "/releases/" + release["release_id"] + "/source", 3, bare=True)
    assert "secret=合成令牌" not in json.dumps(public_document, ensure_ascii=False)
    created = await call("POST", "/cases", 3, {"release_ids": [release["release_id"]]})
    assert created["source_accessible"]
    await call("GET", "/cases/" + created["case_id"], 3)
    public = await call("GET", "/cases/" + created["case_id"] + "/parts/source", 3, bare=True)
    private = await call("GET", "/cases/" + created["case_id"] + "/parts/private", 0, bare=True)
    assert private["members"][0]["original"]["content_text"] == request()["content_text"]
    assert public["documents"][0]["text"] == public_document["text"]
    for kind in ("originals", "releases", "cases"):
        assert (await call("GET", "/" + kind, 0))["items"]
    ordinary_directory = await call("GET", "/releases", 3)
    assert set(ordinary_directory["items"][0]) == {"release_id", "status", "revision", "published_review_hash", "model_processing_allowed", "source_accessible"}
    await call("POST", "/cases/" + created["case_id"] + "/revoke", 0, {"revision": 1, "reason": "合成快照撤回"})
    await call("POST", "/releases/" + release["release_id"] + "/revoke", 0, {"revision": 2, "reason": "合成版本撤回"})
    await call("POST", "/originals/" + original["original_id"] + "/revoke", 0, {"revision": 1, "reason": "合成原件撤回"})
    assert {model: db.query(model).count() for model in clinical_before} == clinical_before
    (tmp_path / "actual-main-operations-source-packets.json").write_text(json.dumps(packets, ensure_ascii=False, indent=2))


@pytest.mark.asyncio
async def test_actual_routes_enforce_super_governance_and_current_source_after_withdrawal(actors, async_client, auth_headers, mounted):
    db, registrar, creator, reviewer, admin = actors
    names = [u.username for u in (registrar, creator, reviewer, admin)]
    db.commit()
    sup, draft_actor, auditor, ordinary = [auth_headers(name) for name in names]
    made = await async_client.post(BASE + "/originals", headers=sup, json=request())
    original = made.json()["data"]
    response = await async_client.post(BASE + "/originals", headers=ordinary, json=request())
    assert response.status_code == 403
    response = await async_client.post(BASE + "/releases", headers=draft_actor, json=proposal(original, request()["content_text"]))
    assert response.status_code == 200, response.text
    release = response.json()["data"]
    response = await async_client.post(BASE + "/releases/" + release["release_id"] + "/review", headers=sup, json=review())
    assert response.status_code == 403
    response = await async_client.post(BASE + "/releases/" + release["release_id"] + "/review", headers=auditor, json=review())
    assert response.status_code == 200, response.text
    response = await async_client.post(BASE + "/cases", headers=ordinary, json={"release_ids": [release["release_id"]]})
    case = response.json()["data"]
    assert (await async_client.get(BASE + "/cases/" + case["case_id"] + "/parts/private", headers=ordinary)).status_code == 403
    assert (await async_client.get(BASE + "/releases/" + release["release_id"] + "/draft", headers=ordinary)).status_code == 403
    response = await async_client.post(BASE + "/originals/" + original["original_id"] + "/revoke", headers=sup, json={"revision": 1, "reason": "明确撤回"})
    assert response.status_code == 200, response.text
    seen = []

    def observe(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().lower().startswith("select"):
            seen.append(re.split(r"\sfrom\s", statement.lower(), maxsplit=1)[0])

    event.listen(db.get_bind(), "before_cursor_execute", observe)
    try:
        for headers in (ordinary, sup):
            response = await async_client.get(BASE + "/cases/" + case["case_id"] + "/parts/source", headers=headers)
            assert response.status_code == 403
        response = await async_client.get(BASE + "/cases/" + case["case_id"], headers=sup)
        assert response.status_code == 200 and response.json()["data"]["source_accessible"] is False
        response = await async_client.get(BASE + "/releases", headers=sup)
        assert response.status_code == 200 and response.json()["data"]["items"][0]["source_accessible"] is False
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", observe)
    assert not any(any(column in statement for column in [".content_text", ".identity_json", ".draft_json", ".published_review_json", ".private_json", ".public_json"]) for statement in seen)


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [b'{"kind":"runbook","kind":"diagnostic_log"}', b'{"kind":NaN}', b'{"kind":1.0}', b'{"kind":"\xff"}'])
async def test_complete_raw_json_rejects_duplicate_nonfinite_fractional_or_invalid_utf8(actors, async_client, auth_headers, mounted, body):
    db, registrar, *_ = actors
    name = registrar.username
    db.commit()
    before = db.query(AIOperationsOriginal).count()
    response = await async_client.post(BASE + "/originals", headers={**auth_headers(name), "content-type": "application/json"}, content=body)
    assert response.status_code == 422, response.text
    assert db.query(AIOperationsOriginal).count() == before


@pytest.mark.asyncio
async def test_whole_request_and_complete_original_wire_expansion_reject_without_clipping(actors, async_client, auth_headers, mounted):
    db, registrar, *_ = actors
    name = registrar.username
    db.commit()
    before = (db.query(AIOperationsOriginal).count(), db.query(AIAuditEvent).count())
    response = await async_client.post(BASE + "/originals", headers={**auth_headers(name), "content-type": "application/json"}, content=b" " * (8 * 1024 * 1024 + 1))
    assert response.status_code == 413, response.text
    with pytest.raises(HTTPException) as exc:
        r.register_original(db, registrar, {**request(), "content_text": "\x00" * (2 * 1024 * 1024)})
    assert getattr(exc.value, "status_code", None) == 422
    assert (db.query(AIOperationsOriginal).count(), db.query(AIAuditEvent).count()) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("query", ["page=true", "page=1.0", "size=0", "size=51"])
async def test_actual_directory_query_is_strict_and_bounded(actors, async_client, auth_headers, mounted, query):
    db, registrar, *_ = actors
    name = registrar.username
    db.commit()
    response = await async_client.get(BASE + "/originals?" + query, headers=auth_headers(name))
    assert response.status_code == 422, response.text


@pytest.mark.asyncio
async def test_actual_http_source_and_receipt_rollback_when_complete_reply_is_too_large(actors, async_client, auth_headers, mounted, monkeypatch):
    db, registrar, *_ = actors
    name = registrar.username
    db.commit()
    before = (db.query(AIOperationsOriginal).count(), db.query(AIAuditEvent).count())
    register = r.register_original

    def excessive_reply(*args, **kwargs):
        made = register(*args, **kwargs)
        return {**made, "synthetic_oversized_reply": "x" * (8 * 1024 * 1024)}

    monkeypatch.setattr(r, "register_original", excessive_reply)
    response = await async_client.post(BASE + "/originals", headers=auth_headers(name), json=request())
    assert response.status_code == 422, response.text
    assert (db.query(AIOperationsOriginal).count(), db.query(AIAuditEvent).count()) == before
