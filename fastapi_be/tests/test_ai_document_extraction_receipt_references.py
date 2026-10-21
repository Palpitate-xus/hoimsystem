"""Real task/candidate receipts use exact audit PKs, never range SHARE scans."""

import httpx
import pytest
from sqlalchemy import event, text

from app.ai import document_evidence_contract as c
from app.ai import runtime
from app.ai.document_evidence_models import AIDocumentSpanCandidate
from app.ai.document_extraction_contract import parse_extraction_reply
from app.ai.document_extraction_result import result_for_draft
from app.ai.document_extraction_run_record import encode_record, parse_record
from app.ai.document_extraction_storage import load_snapshot
from app.ai.models import AIAuditEvent, AIKnowledgeDocument, AIRun
from tests.test_ai_document_evidence_sources import approved_original
from tests.test_ai_document_extraction_gateway import envelope
from tests.test_ai_document_extraction_pipeline import document_pipeline as _document_pipeline
from tests.test_ai_document_extraction_pipeline import model_transport, queue

document_pipeline = _document_pipeline


async def succeeded(client, headers, case):
    claim, _ = await queue(client, headers, case)
    transport, _ = model_transport(case)
    await runtime.execute_claimed(*claim, transport=transport)
    case["db"].expire_all()
    row = case["db"].get(AIRun, claim[0])
    assert row.status == "succeeded"
    return row


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["plain_result", "missing_ref", "nonexistent_ref", "foreign_ref", "actor", "target", "action", "result_hash", "deleted_receipt"])
async def test_runtime_api_requires_exact_current_receipt_pk_even_rehashed_complete_result(async_client, auth_headers, document_pipeline, mutation):
    case, db = document_pipeline, document_pipeline["db"]
    headers = auth_headers(case["actor"].username)
    row = await succeeded(async_client, headers, case)
    record = c.parse_json(row.result_json)
    receipt = db.get(AIAuditEvent, record["receipt_event_id"])
    if mutation == "plain_result":
        row.result_json = c.canonical_json(record["result"])
    elif mutation == "missing_ref":
        del record["receipt_event_id"]
        row.result_json = c.canonical_json(record)
    elif mutation == "nonexistent_ref":
        record["receipt_event_id"] = 2147483647
        row.result_json = c.canonical_json(record)
    elif mutation == "foreign_ref":
        record["receipt_event_id"] = db.query(AIAuditEvent.event_id).filter_by(action="run.create", target=row.run_id).one()[0]
        row.result_json = c.canonical_json(record)
    elif mutation == "actor":
        receipt.actor_id = case["seed"]["doctor_user"].user_id
    elif mutation == "target":
        receipt.target = case["original"].snapshot.original_id
    elif mutation == "action":
        receipt.action = "run.document_extraction.fail"
    elif mutation == "result_hash":
        details = c.parse_json(receipt.detail_json)
        details["result_hash"] = c.bytes_hash(row.result_json)
        receipt.detail_json = c.canonical_json(details)
    else:
        db.delete(receipt)
    db.commit()
    denied = await async_client.get(f"/api/ai/runs/{row.run_id}", headers=headers)
    assert denied.status_code == 409, denied.text


@pytest.mark.asyncio
async def test_two_explicit_ordinals_retain_result_hash_and_only_read_actual_audit_primary_keys(async_client, auth_headers, document_pipeline):
    case, db = document_pipeline, document_pipeline["db"]
    headers = auth_headers(case["actor"].username)
    claim, _ = await queue(async_client, headers, case)
    raw = case["original"].snapshot.text
    spans = [
        {"proposed_heading": "第一未核实条款", "clause_kind": "other", "start": 0, "end": 7, "quote": raw[:7]},
        {"proposed_heading": "第二未核实条款", "clause_kind": "other", "start": 7, "end": len(raw), "quote": raw[7:]},
    ]
    await runtime.execute_claimed(*claim, transport=httpx.MockTransport(lambda _: httpx.Response(200, json=envelope("chat", c.canonical_json({"spans": spans})))))
    db.expire_all()
    row = db.get(AIRun, claim[0])
    first = parse_record(row.result_json)
    receipt_hash = c.parse_json(db.get(AIAuditEvent, first.receipt_event_id).detail_json)["result_hash"]
    assert receipt_hash == c.digest(first.result)
    statements = []

    def observe(conn, cursor, query, parameters, context, many):
        if query.lstrip().upper().startswith("SELECT") and "hoimsystem_ai_audit_event" in query:
            statements.append(query)

    event.listen(db.get_bind(), "before_cursor_execute", observe)
    try:
        for ordinal in (0, 1):
            response = await async_client.post(f"/api/ai/runs/{row.run_id}/document-candidates", headers=headers, json={"ordinal": ordinal})
            assert response.status_code == 200, response.text
            assert response.json()["data"]["governance"]["status"] == "draft"
        duplicate = await async_client.post(f"/api/ai/runs/{row.run_id}/document-candidates", headers=headers, json={"ordinal": 0})
        assert duplicate.status_code == 409
        detail = await async_client.get(f"/api/ai/runs/{row.run_id}", headers=headers)
        assert detail.status_code == 200, detail.text
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", observe)
    db.expire_all()
    saved = parse_record(db.get(AIRun, row.run_id).result_json)
    assert set(saved.saved_candidates) == {"0", "1"}
    assert saved.receipt_event_id == first.receipt_event_id and saved.result == first.result
    assert detail.json()["data"]["result"] == first.result.model_dump(mode="json")
    assert all("WHERE hoimsystem_ai_audit_event.event_id =" in query for query in statements), statements
    assert len(statements) > 5
    for ordinal, reference in saved.saved_candidates.items():
        audit = db.get(AIAuditEvent, reference.audit_event_id)
        original = c.parse_json(audit.detail_json)
        assert audit.action == "run.document_extraction.candidate" and audit.target == row.run_id
        assert original["ordinal"] == int(ordinal) and original["candidate_id"] == reference.candidate_id and original["result_hash"] == receipt_hash
    assert db.query(AIDocumentSpanCandidate).count() == 2
    assert db.query(AIKnowledgeDocument).count() == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["input_tokens", "error_code", "feature_key", "result_json"])
async def test_save_checks_all_actual_run_fields_and_the_second_record_write(async_client, auth_headers, document_pipeline, field):
    case, db = document_pipeline, document_pipeline["db"]
    headers = auth_headers(case["actor"].username)
    row = await succeeded(async_client, headers, case)
    before = row.result_json
    assignments = {
        "input_tokens": "input_tokens=999",
        "error_code": "error_code='unexpected-save-error'",
        "feature_key": "feature_key='operations_qa'",
        "result_json": "result_json=json_set(NEW.result_json,'$.receipt_event_id',2147483647)",
    }
    db.execute(
        text(
            "CREATE TRIGGER document_accept_fault AFTER UPDATE ON hoimsystem_ai_run WHEN json_extract(NEW.result_json,'$.saved_candidates.\"0\"') IS NOT NULL BEGIN UPDATE hoimsystem_ai_run SET "
            + assignments[field]
            + " WHERE run_id=NEW.run_id; END"
        )
    )
    db.commit()
    denied = await async_client.post(f"/api/ai/runs/{row.run_id}/document-candidates", headers=headers, json={"ordinal": 0})
    assert denied.status_code == 409, denied.text
    db.expire_all()
    assert db.get(AIRun, row.run_id).result_json == before
    assert db.query(AIDocumentSpanCandidate).count() == 0
    assert db.query(AIAuditEvent).filter_by(action="run.document_extraction.candidate", target=row.run_id).count() == 0


@pytest.mark.asyncio
async def test_appending_saved_reference_over_complete_text_capacity_rolls_back_without_truncation(async_client, auth_headers, document_pipeline):
    case, db = document_pipeline, document_pipeline["db"]
    case["original"] = approved_original(db, case["actor"], "Q" * 1024)
    headers = auth_headers(case["actor"].username)
    claim, _ = await queue(async_client, headers, case)
    _, context, metadata = load_snapshot(db, db.get(AIRun, claim[0]))

    def make_spans(length, extra=0):
        return [{"proposed_heading": f"条款{index}" + ("x" * extra if index == 63 else ""), "clause_kind": "other", "start": 0, "end": length, "quote": "Q" * length} for index in range(64)]

    def expected(spans):
        draft = parse_extraction_reply({"spans": spans}, context.document_source, metadata["instructions_digest"])
        return result_for_draft(draft, context.document_source, metadata["instructions_digest"])

    length, high = 1, 1024
    while length < high:
        candidate_length = (length + high + 1) // 2
        try:
            fits = len(c.utf8(encode_record(expected(make_spans(candidate_length)), 1))) <= 65500
        except ValueError:
            fits = False
        if fits:
            length = candidate_length
        else:
            high = candidate_length - 1
    extra = 65500 - len(c.utf8(encode_record(expected(make_spans(length)), 1)))
    spans = make_spans(length, extra)
    await runtime.execute_claimed(*claim, transport=httpx.MockTransport(lambda _: httpx.Response(200, json=envelope("chat", c.canonical_json({"spans": spans})))))
    db.expire_all()
    row = db.get(AIRun, claim[0])
    assert row.status == "succeeded"
    before = row.result_json
    assert 65500 <= len(c.utf8(before)) < 65535
    denied = await async_client.post(f"/api/ai/runs/{row.run_id}/document-candidates", headers=headers, json={"ordinal": 0})
    assert denied.status_code == 409, denied.text
    db.expire_all()
    assert db.get(AIRun, row.run_id).result_json == before
    assert len(parse_record(before).result.document_extraction.spans) == 64
    assert db.query(AIDocumentSpanCandidate).count() == 0
    assert db.query(AIAuditEvent).filter_by(action="run.document_extraction.candidate", target=row.run_id).count() == 0
