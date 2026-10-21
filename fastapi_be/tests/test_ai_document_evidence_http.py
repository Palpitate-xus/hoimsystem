"""Real router/JWT/ASGI against memory SQL; no main registration is claimed."""

# ruff: noqa: F811 -- importing the real fixture is pytest registration.

import asyncio
import base64
import json

import pytest
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event

from app.ai import document_evidence_contract as c
from app.ai import document_evidence_sources as s
from app.ai.document_evidence_models import AIDocumentOriginal
from app.ai.models import AIAuditEvent, AIKnowledgeDocument
from app.database import get_db
from app.routers.ai_document_evidence import router
from tests.test_ai_document_evidence_contract import NOTE, NOW, request
from tests.test_ai_document_evidence_sources import candidate_request, cas, document_case, publish, review  # noqa: F401

ROOT = "/api/ai/admin/document-evidence"


@pytest.fixture
def document_app(document_case):
    db, _, _ = document_case
    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.dependency_overrides[get_db] = lambda: db
    return app


@pytest.mark.asyncio
async def test_actual_jwt_original_span_publish_evidence_and_revocation_http(document_app, document_case, auth_headers):
    db, actor, _ = document_case
    headers = auth_headers(actor.username)
    async with AsyncClient(transport=ASGITransport(app=document_app), base_url="http://synthetic") as client:
        options = await client.get(ROOT + "/options", headers=headers)
        assert options.status_code == 200 and options.json()["data"]["automatic_extraction"] is False
        created = await client.post(ROOT + "/originals", headers=headers, json=request())
        assert created.status_code == 200, created.text
        original = c.OriginalRecord.model_validate(created.json()["data"])
        assert original.snapshot.recorded_at == NOW and not original.eligible
        oid = original.snapshot.original_id
        confirmed = await client.post(f"{ROOT}/originals/{oid}/review", headers=headers, json=review(original))
        assert confirmed.status_code == 200, confirmed.text
        original = c.OriginalRecord.model_validate(confirmed.json()["data"])
        proposed = await client.post(ROOT + "/candidates", headers=headers, json=candidate_request(original))
        assert proposed.status_code == 200, proposed.text
        candidate = c.CandidateRecord.model_validate(proposed.json()["data"])
        cid = candidate.snapshot.candidate_id
        assert db.query(AIKnowledgeDocument).count() == 0
        approved = await client.post(f"{ROOT}/candidates/{cid}/review", headers=headers, json=review(candidate))
        assert approved.status_code == 200, approved.text
        candidate = c.CandidateRecord.model_validate(approved.json()["data"])
        result = await client.post(f"{ROOT}/candidates/{cid}/publish", headers=headers, json=publish(candidate))
        assert result.status_code == 200, result.text
        publication = c.PublicationRecord.model_validate(result.json()["data"])
        assert publication.eligible
        knowledge = db.get(AIKnowledgeDocument, publication.snapshot.knowledge_document_id)
        assert s.published_bound_source_is_current(db, knowledge)
        for path in (f"/originals/{oid}", f"/candidates/{cid}", f"/publications/{publication.snapshot.publication_id}"):
            assert (await client.get(ROOT + path, headers=headers)).status_code == 200
        for path, forbidden_column in (("/originals", "original_text"), ("/candidates", "candidate_json"), ("/publications", "publication_json")):
            statements = []
            connection = db.connection()

            def sql(conn, cursor, statement, parameters, context, many):
                statements.append(statement)

            event.listen(connection, "before_cursor_execute", sql)
            try:
                listing = await client.get(ROOT + path, headers=headers)
            finally:
                event.remove(connection, "before_cursor_execute", sql)
            assert listing.status_code == 200, listing.text
            directory = listing.json()["data"]
            assert directory["total"] == 1 and directory["items"][0]["detail_required"]
            assert not any(forbidden_column in value for value in statements)
        revoked = await client.post(f"{ROOT}/originals/{oid}/revoke", headers=headers, json={**cas(original), "basis_note": NOTE})
        assert revoked.status_code == 200 and revoked.json()["data"]["governance"]["revision"] == 3
        assert not s.published_bound_source_is_current(db, knowledge)
        frozen = await client.get(f"{ROOT}/publications/{publication.snapshot.publication_id}", headers=headers)
        assert frozen.status_code == 200 and not frozen.json()["data"]["eligible"] and frozen.json()["data"]["snapshot"]["quote"] == original.snapshot.text


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["admin_user", "doctor_user", "pharmacist_user", "nurse_user"])
async def test_super_only_real_roles_not_technical_or_clinical_admin(document_app, document_case, auth_headers, role):
    _, _, seed = document_case
    async with AsyncClient(transport=ASGITransport(app=document_app), base_url="http://synthetic") as client:
        assert (await client.get(ROOT + "/options")).status_code == 401
        headers = auth_headers(seed[role].username)
        assert (await client.get(ROOT + "/originals", headers=headers)).status_code == 403
        assert (await client.post(ROOT + "/originals", headers=headers, json=request())).status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [b'{"x":1,"x":2}', b'{"x":{"y":1,"y":2}}', b'{"x":NaN}', b'{"x":Infinity}', b'{"x":"\\ud800"}', b'{"x":"\xff"}'])
async def test_actual_bad_json_utf8_nonfinite_or_duplicates_are_rejected_without_echo(document_app, document_case, auth_headers, body):
    db, actor, _ = document_case
    async with AsyncClient(transport=ASGITransport(app=document_app), base_url="http://synthetic") as client:
        response = await client.post(ROOT + "/originals", headers={**auth_headers(actor.username), "content-type": "application/json"}, content=body)
    assert response.status_code == 422 and "重复" in response.json()["detail"]
    assert db.query(AIDocumentOriginal).count() == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["extra", "hash", "format", "privacy_is_not_implicit"])
async def test_strict_fields_and_submitted_hash_do_not_get_coerced(document_app, document_case, auth_headers, mutation):
    db, actor, _ = document_case
    body = request()
    if mutation == "extra":
        body["patient_data_free"] = True
    elif mutation == "hash":
        body["content"]["expected_bytes_hash"] = "a" * 64
    elif mutation == "format":
        body["content"]["kind"] = "pdf"
    else:
        body["metadata"]["privacy_review"] = "confirmed"
    async with AsyncClient(transport=ASGITransport(app=document_app), base_url="http://synthetic") as client:
        response = await client.post(ROOT + "/originals", headers=auth_headers(actor.username), json=body)
    assert response.status_code == 422 and db.query(AIDocumentOriginal).count() == 0


@pytest.mark.asyncio
async def test_actual_file_bom_crlf_and_four_mib_store_all_bytes(document_app, document_case, auth_headers):
    db, actor, _ = document_case
    text = "\ufeff行\r\n😀" + "x" * (c.MAX_ORIGINAL_BYTES - len("\ufeff行\r\n😀".encode()))
    body = request()
    body["content"] = {"kind": "utf8_file", "filename": "合成原文.md", "bytes_base64": base64.b64encode(text.encode()).decode(), "expected_bytes_hash": c.bytes_hash(text)}
    async with AsyncClient(transport=ASGITransport(app=document_app), base_url="http://synthetic") as client:
        response = await client.post(ROOT + "/originals", headers=auth_headers(actor.username), json=body)
    assert response.status_code == 200, response.text[:1000]
    record = c.OriginalRecord.model_validate(response.json()["data"])
    assert record.snapshot.text == text and record.snapshot.raw_bytes_length == c.MAX_ORIGINAL_BYTES
    assert db.get(AIDocumentOriginal, record.snapshot.original_id).original_text == text


@pytest.mark.asyncio
@pytest.mark.parametrize("known_length", [True, False])
async def test_complete_request_cap_without_truncating_or_writing(document_app, document_case, auth_headers, known_length):
    db, actor, _ = document_case
    headers = {**auth_headers(actor.username), "content-type": "application/json"}

    async def chunks():
        for _ in range(9):
            yield b"x" * (1024 * 1024)

    if known_length:
        headers["content-length"] = str(c.MAX_REQUEST_BYTES + 1)
    async with AsyncClient(transport=ASGITransport(app=document_app), base_url="http://synthetic") as client:
        response = await client.post(ROOT + "/originals", headers=headers, content=b"{}" if known_length else chunks())
    assert response.status_code == 413 and db.query(AIDocumentOriginal).count() == 0


@pytest.mark.asyncio
async def test_actual_slow_upload_deadline_then_next_request_can_succeed(document_app, document_case, auth_headers, monkeypatch):
    db, actor, _ = document_case
    monkeypatch.setattr(c, "UPLOAD_TIMEOUT_SECONDS", 0.01)
    body = json.dumps(request()).encode()

    async def slow():
        yield body[:1]
        await asyncio.sleep(0.05)
        yield body[1:]

    async with AsyncClient(transport=ASGITransport(app=document_app), base_url="http://synthetic") as client:
        headers = {**auth_headers(actor.username), "content-type": "application/json"}
        response = await client.post(ROOT + "/originals", headers=headers, content=slow())
        assert response.status_code == 408 and db.query(AIDocumentOriginal).count() == 0
        assert (await client.post(ROOT + "/originals", headers=headers, json=request())).status_code == 200


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["audit", "commit"])
async def test_actual_http_sql_audit_or_commit_failure_has_no_partial_original(document_app, document_case, auth_headers, monkeypatch, phase):
    db, actor, _ = document_case
    before = db.query(AIAuditEvent).count()
    if phase == "audit":
        actual = s.audit

        def fail(*args, **kwargs):
            actual(*args, **kwargs)
            args[0].flush()
            raise HTTPException(409, "synthetic audit failure")

        monkeypatch.setattr(s, "audit", fail)
    else:

        def fail(session):
            raise RuntimeError("synthetic before commit failure")

        event.listen(db, "before_commit", fail)
    try:
        async with AsyncClient(transport=ASGITransport(app=document_app), base_url="http://synthetic") as client:
            response = await client.post(ROOT + "/originals", headers=auth_headers(actor.username), json=request())
    finally:
        if phase == "commit":
            event.remove(db, "before_commit", fail)
    assert response.status_code == (409 if phase == "audit" else 500)
    assert db.query(AIDocumentOriginal).count() == 0 and db.query(AIAuditEvent).count() == before
