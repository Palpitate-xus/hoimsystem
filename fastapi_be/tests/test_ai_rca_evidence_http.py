"""Actual dedicated router/JWT/ASGI and memory SQL, not Main registration."""

import asyncio
import json

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.ai import rca_evidence_case_contract as kc
from app.ai import rca_evidence_contract as c
from app.ai import rca_evidence_directory as directories
from app.ai import rca_evidence_input as i
from app.ai import rca_evidence_source_contract as sc
from app.ai.models import AIAuditEvent
from app.ai.rca_evidence_models import AIRcaEvidenceCase
from app.database import get_db
from app.routers import ai_rca_evidence as r
from tests.test_ai_rca_evidence_grants import body as grant_body
from tests.test_ai_rca_evidence_grants import both, cas
from tests.test_ai_rca_evidence_grants import grant_case as grant_case
from tests.test_ai_rca_evidence_sources import NOTE, TEXT, body, create

ROOT = "/api/ai/admin/rca-evidence"


@pytest.fixture
def rca_app(grant_case):
    app = FastAPI()
    app.include_router(r.router, prefix="/api")
    app.dependency_overrides[get_db] = lambda: grant_case["db"]
    return app


def published_review(record):
    return {**cas(record), "decision": "publish", "privacy_review": "confirmed", "faithfulness_review": "confirmed", "provenance_review": "confirmed"}


@pytest.mark.asyncio
async def test_actual_jwt_two_purposes_original_capture_case_publish_and_current_revoke(rca_app, grant_case, auth_headers):
    case, db = grant_case, grant_case["db"]
    headers = auth_headers(case["actor"].username)
    async with AsyncClient(transport=ASGITransport(app=rca_app), base_url="http://synthetic") as client:
        options = await client.get(ROOT + "/options", headers=headers)
        assert options.status_code == 200 and options.json()["data"]["automatic_model_calls"] is False
        for kind in ("event_investigation", "associated_patient_processing"):
            response = await client.post(ROOT + "/grants", headers=headers, json=grant_body(case, kind))
            assert response.status_code == 200, response.text
            record = i.GrantRecord.model_validate(response.json()["data"])
            assert record.identity.issued_at == "2026-10-21T12:00:00.123456Z"
            assert (await client.get(ROOT + "/grants/" + record.identity.grant_id, headers=headers)).status_code == 200
        response = await client.post(ROOT + "/originals", headers=headers, json=body(case))
        assert response.status_code == 200, response.text
        original = sc.OriginalRecord.model_validate(response.json()["data"])
        assert original.immutable.text == TEXT and original.immutable.recorded_at.endswith(".123456Z")
        response = await client.post(ROOT + "/originals/" + original.immutable.original_id + "/review", headers=headers, json=published_review(original))
        assert response.status_code == 200, response.text
        original = sc.OriginalRecord.model_validate(response.json()["data"])
        actual = await client.get(f"{ROOT}/events/{case['event_id']}/capture", headers=headers)
        assert actual.status_code == 200, actual.text
        capture = kc.Capture.model_validate(actual.json()["data"])
        response = await client.post(
            ROOT + "/cases",
            headers=headers,
            json={"event_id": case["event_id"], "expected_event_patient_id": case["patient_id"], "expected_collection_hash": capture.collection_hash, "basis_note": NOTE},
        )
        assert response.status_code == 200, response.text
        comparison = kc.CaseRecord.model_validate(response.json()["data"])
        response = await client.post(f"{ROOT}/cases/{comparison.immutable.case_id}/review", headers=headers, json=published_review(comparison))
        assert response.status_code == 200, response.text
        comparison = kc.CaseRecord.model_validate(response.json()["data"])
        released = await client.get(f"{ROOT}/cases/{comparison.immutable.case_id}/public-source", headers=headers)
        assert released.status_code == 200, released.text
        source = c.RcaEvidenceSource.model_validate(released.json()["data"])
        assert source.items[0].text == TEXT and source.snapshot_time.endswith(".123456Z")
        assert source.event_state.causal_approval == "not_provided" and len(released.content) <= c.MAX_WIRE_BYTES
        raw = await client.get(f"{ROOT}/events/{case['event_id']}/legacy-witness", params={"kind": "legacy_event", "record_id": case["event_id"]}, headers=headers)
        assert raw.status_code == 200 and raw.json()["data"]["causal_verification"] == "not_provided"
        for kind in ("grants", "originals", "cases"):
            listing = await client.get(f"{ROOT}/events/{case['event_id']}/directory/{kind}", headers=headers)
            assert listing.status_code == 200, listing.text
            directories.Directory.model_validate(listing.json()["data"])
        revoked = await client.post(ROOT + "/originals/" + original.immutable.original_id + "/revoke", headers=headers, json=cas(original))
        assert revoked.status_code == 200, revoked.text
        assert (await client.get(f"{ROOT}/cases/{comparison.immutable.case_id}/public-source", headers=headers)).status_code == 409
        current = await client.get(ROOT + "/cases/" + comparison.immutable.case_id, headers=headers)
        assert current.status_code == 200 and current.json()["data"]["eligible"] is False
        closed = await client.post(ROOT + "/cases/" + comparison.immutable.case_id + "/revoke", headers=headers, json=cas(comparison))
        assert closed.status_code == 200 and closed.json()["data"]["governance"]["revision"] == 3
        assert db.query(AIRcaEvidenceCase).filter_by(event_id=case["event_id"]).count() == 1


@pytest.mark.asyncio
async def test_actual_authentication_role_and_missing_purpose_never_reads_source_text(rca_app, grant_case, auth_headers):
    case, db = grant_case, grant_case["db"]
    async with AsyncClient(transport=ASGITransport(app=rca_app), base_url="http://synthetic") as client:
        assert (await client.get(ROOT + "/options")).status_code == 401
        assert (await client.get(ROOT + "/options", headers=auth_headers(case["users"]["doctor_user"].username))).status_code == 403
        headers = auth_headers(case["actor"].username)
        # The SQL observation is attached across the actual async request.
        from sqlalchemy import Select, event

        fields = []

        def observe(state):
            if state.is_select and isinstance(state.statement, Select):
                fields.extend(col.key for col in state.statement.selected_columns)

        event.listen(db, "do_orm_execute", observe)
        try:
            response = await client.get(f"{ROOT}/events/{case['event_id']}/capture", headers=headers)
            directory = await client.get(f"{ROOT}/events/{case['event_id']}/directory/originals", headers=headers)
        finally:
            event.remove(db, "do_orm_execute", observe)
        assert response.status_code == directory.status_code == 403
        assert not {"description", "root_cause", "original_json", "case_json"}.intersection(fields)


@pytest.mark.asyncio
@pytest.mark.parametrize("raw", [b'{"event_id":1,"event_id":2}', b'{"text":NaN}', b'{"text":"\xff"}', b'{"text":"\\ud800"}', b"[]"])
async def test_invalid_raw_json_rejected_without_echo_or_partial_audit(rca_app, grant_case, auth_headers, raw):
    db = grant_case["db"]
    before = db.query(AIAuditEvent).count()
    async with AsyncClient(transport=ASGITransport(app=rca_app), base_url="http://synthetic") as client:
        response = await client.post(ROOT + "/originals", headers={**auth_headers(grant_case["actor"].username), "content-type": "application/json"}, content=raw)
    assert response.status_code == 422 and db.query(AIAuditEvent).count() == before
    assert len(response.content) < 512 and b"\\ud800" not in response.content


@pytest.mark.asyncio
@pytest.mark.parametrize("update", [{"text": "\ud800"}, {"event_id": True}, {"patient_id": 1}, {"origin_kind": "human_timeline"}])
async def test_strict_body_foreign_scope_unknown_and_surrogate_refuse_whole(rca_app, grant_case, auth_headers, update):
    db = grant_case["db"]
    before = db.query(AIAuditEvent).count()
    raw = json.dumps(body(grant_case, **update), ensure_ascii=True).encode()
    async with AsyncClient(transport=ASGITransport(app=rca_app), base_url="http://synthetic") as client:
        response = await client.post(ROOT + "/originals", headers={**auth_headers(grant_case["actor"].username), "content-type": "application/json"}, content=raw)
    assert response.status_code == 422 and db.query(AIAuditEvent).count() == before
    assert b"123456Z" not in response.content


@pytest.mark.asyncio
async def test_real_directory_pagination_current_total_includes_all_rows_and_no_text_columns(rca_app, grant_case, auth_headers):
    case, db = grant_case, grant_case["db"]
    both(case)
    records = [create(case) for _ in range(23)]
    headers = auth_headers(case["actor"].username)
    from sqlalchemy import Select, event

    columns = []

    def observe(state):
        if state.is_select and isinstance(state.statement, Select):
            columns.extend(col.key for col in state.statement.selected_columns)

    async with AsyncClient(transport=ASGITransport(app=rca_app), base_url="http://synthetic") as client:
        event.listen(db, "do_orm_execute", observe)
        try:
            first = await client.get(f"{ROOT}/events/{case['event_id']}/directory/originals", headers=headers)
            second = await client.get(f"{ROOT}/events/{case['event_id']}/directory/originals", params={"page": 2}, headers=headers)
        finally:
            event.remove(db, "do_orm_execute", observe)
        assert first.status_code == second.status_code == 200
        assert first.json()["data"]["total"] == second.json()["data"]["total"] == 23
        items = first.json()["data"]["items"] + second.json()["data"]["items"]
        assert len(items) == 23 and {item["original_id"] for item in items} == {row.immutable.original_id for row in records}
        assert all(item["complete_current_detail_required"] for item in items)
        assert "original_json" not in columns and "case_json" not in columns
        for query in ("?patient_id=1", "?page=1&page=2", "?page=0"):
            assert (await client.get(f"{ROOT}/events/{case['event_id']}/directory/originals" + query, headers=headers)).status_code == 422


@pytest.mark.asyncio
async def test_actual_slow_upload_whole_byte_cap_and_next_valid_write(rca_app, grant_case, auth_headers, monkeypatch):
    case, db = grant_case, grant_case["db"]
    both(case)
    headers = {**auth_headers(case["actor"].username), "content-type": "application/json"}
    monkeypatch.setattr(r, "UPLOAD_TIMEOUT_SECONDS", 0.02)

    async def slow():
        yield b'{"text":"'
        await asyncio.sleep(0.1)
        yield b'late"}'

    async def oversized():
        for _ in range(9):
            yield b" " * (1024 * 1024)

    before = db.query(AIAuditEvent).count()
    async with AsyncClient(transport=ASGITransport(app=rca_app), base_url="http://synthetic") as client:
        assert (await client.post(ROOT + "/originals", headers=headers, content=slow())).status_code == 408
        assert (await client.post(ROOT + "/originals", headers=headers, content=oversized())).status_code == 413
        assert (await client.post(ROOT + "/originals", headers={**headers, "content-length": str(c.MAX_WIRE_BYTES + 1)}, content=b"{}")).status_code == 413
        assert db.query(AIAuditEvent).count() == before
        accepted = await client.post(ROOT + "/originals", headers=headers, json=body(case))
        assert accepted.status_code == 200, accepted.text
        assert accepted.json()["data"]["immutable"]["text"] == TEXT


@pytest.mark.asyncio
async def test_whole_response_budget_failure_is_before_commit_and_preserves_audit_atomicity(rca_app, grant_case, auth_headers, monkeypatch):
    # Use the production byte-budget path at a deliberately smaller local test
    # boundary. This checks the actual whole-record overhead and SQL rollback;
    # it is not a measured8MiB capacity claim.
    from tests.test_ai_rca_evidence_cases import create_case

    case, db = grant_case, grant_case["db"]
    both(case)
    original = create_case(case)
    raw_size = len(c.utf8(c.canonical(original.immutable)))
    assert raw_size < len(c.utf8(c.canonical(original)))
    monkeypatch.setattr(c, "MAX_WIRE_BYTES", raw_size + 1)
    before = db.query(AIAuditEvent).count()
    capture_hash = original.immutable.capture.collection_hash
    async with AsyncClient(transport=ASGITransport(app=rca_app), base_url="http://synthetic") as client:
        response = await client.post(
            ROOT + "/cases",
            headers=auth_headers(case["actor"].username),
            json={"event_id": case["event_id"], "expected_event_patient_id": case["patient_id"], "expected_collection_hash": capture_hash, "basis_note": NOTE},
        )
    assert response.status_code == 409 and db.query(AIAuditEvent).count() == before
    assert db.query(AIRcaEvidenceCase).filter_by(event_id=case["event_id"]).count() == 1
