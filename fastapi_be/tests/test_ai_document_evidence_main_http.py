"""Actual mounted main JWT APIs must preserve original UTF8 and UTC6 contracts."""

import base64

import pytest

from app.ai import document_evidence_contract as c
from tests.test_ai_document_evidence_contract import NOTE, NOW, request
from tests.test_ai_document_evidence_sources import candidate_request, cas, publish, review
from tests.test_ai_document_evidence_sources import document_case as _document_case

document_case = _document_case
ROOT = "/api/ai/admin/document-evidence"
RAW = "\ufeff合成原文🧪\r\n原文时间字面量2026-10-21T12:34:56.654321Z；2026-10-21T12:34:56.000001+08:00。\ne\u0301"


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["direct_text", "utf8_file"])
async def test_actual_main_complete_source_chain_preserves_utf8_and_microseconds(async_client, auth_headers, document_case, kind):
    db, actor, _ = document_case
    headers = auth_headers(actor.username)
    body = request(RAW)
    if kind == "utf8_file":
        body["content"] = {"kind": kind, "filename": "synthetic.md", "bytes_base64": base64.b64encode(RAW.encode()).decode(), "expected_bytes_hash": c.bytes_hash(RAW)}
    response = await async_client.post(ROOT + "/originals", headers=headers, json=body)
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["snapshot"]["recorded_at"] == NOW
    assert data["snapshot"]["text"] == RAW
    original = c.OriginalRecord.model_validate(data)
    assert original.content_hash == c.digest(original.snapshot)
    assert original.snapshot.raw_bytes_hash == c.bytes_hash(RAW)
    oid = original.snapshot.original_id
    response = await async_client.post(f"{ROOT}/originals/{oid}/review", headers=headers, json=review(original))
    assert response.status_code == 200, response.text
    original = c.OriginalRecord.model_validate(response.json()["data"])
    assert original.governance.reviewed_at == NOW
    response = await async_client.post(ROOT + "/candidates", headers=headers, json=candidate_request(original))
    assert response.status_code == 200, response.text
    candidate = c.CandidateRecord.model_validate(response.json()["data"])
    assert candidate.snapshot.recorded_at == NOW and candidate.snapshot.proposal.quote == RAW
    cid = candidate.snapshot.candidate_id
    response = await async_client.post(f"{ROOT}/candidates/{cid}/review", headers=headers, json=review(candidate))
    assert response.status_code == 200, response.text
    candidate = c.CandidateRecord.model_validate(response.json()["data"])
    assert candidate.governance.reviewed_at == NOW
    response = await async_client.post(f"{ROOT}/candidates/{cid}/publish", headers=headers, json=publish(candidate))
    assert response.status_code == 200, response.text
    publication = c.PublicationRecord.model_validate(response.json()["data"])
    pid = publication.snapshot.publication_id
    assert publication.snapshot.published_at == NOW and publication.snapshot.quote == RAW
    assert publication.snapshot.knowledge_recorded_at == "2026-10-21T12:00:00.000000Z"
    assert publication.knowledge_current.content == RAW
    for category, identity, record in [("originals", oid, original), ("candidates", cid, candidate), ("publications", pid, publication)]:
        response = await async_client.get(f"{ROOT}/{category}/{identity}", headers=headers)
        assert response.status_code == 200, response.text
        assert response.json()["data"] == record.model_dump(mode="json")
        listing = await async_client.get(f"{ROOT}/{category}", headers=headers)
        assert listing.status_code == 200, listing.text
        row = next(value for value in listing.json()["data"]["items"] if value[{"originals": "original_id", "candidates": "candidate_id", "publications": "publication_id"}[category]] == identity)
        assert row["published_at" if category == "publications" else "recorded_at"] == NOW
    response = await async_client.post(f"{ROOT}/originals/{oid}/revoke", headers=headers, json={**cas(original), "basis_note": NOTE})
    assert response.status_code == 200, response.text
    revoked = c.OriginalRecord.model_validate(response.json()["data"])
    assert revoked.snapshot.text == RAW and revoked.governance.revoked_at == NOW
    frozen = await async_client.get(f"{ROOT}/publications/{pid}", headers=headers)
    assert frozen.status_code == 200 and frozen.json()["data"]["snapshot"]["quote"] == RAW
