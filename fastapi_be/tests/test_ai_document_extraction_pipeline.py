"""Actual JWT/SQLite queue and worker; text provider is a synthetic MockTransport."""

import datetime
import json
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import text

from app.ai import document_evidence_contract as c
from app.ai import document_evidence_sources as sources
from app.ai import document_extraction_runtime as documents
from app.ai import models, runtime
from app.ai.document_evidence_models import AIDocumentOriginal, AIDocumentSpanCandidate
from app.ai.document_extraction_models import AIDocumentExtractionRunAnchor
from app.ai.document_extraction_run_record import parse_record
from app.ai.models import AIAuditEvent, AIFeatureConfig, AIFeedback, AIKnowledgeDocument, AIProvider, AIRun
from tests.test_ai_document_evidence_contract import NOW
from tests.test_ai_document_evidence_sources import approved_original
from tests.test_ai_document_extraction_gateway import envelope
from tests.test_ai_runtime import configure


@pytest.fixture
def document_pipeline(db_session, seed_data, monkeypatch):
    db, actor = db_session, seed_data["super_admin_user"]
    now = c.clock(NOW)

    class Clock(datetime.datetime):
        @classmethod
        def now(cls, tz=None):
            aware = now.replace(tzinfo=datetime.UTC)
            return aware.astimezone(tz) if tz else aware.replace(tzinfo=None)

    monkeypatch.setattr(models, "datetime", SimpleNamespace(datetime=Clock, UTC=datetime.UTC))
    for module in (runtime, documents, sources):
        monkeypatch.setattr(module, "utcnow", lambda: now)
    db.query(AIFeedback).delete()
    db.query(AIDocumentExtractionRunAnchor).delete()
    db.query(AIRun).delete()
    db.query(AIFeatureConfig).delete()
    db.query(AIProvider).delete()
    db.commit()
    original = approved_original(db, actor, "\ufeff合成指南🧪\r\n此句仅用于工程区间核对，适用性仍待复核。")
    provider, config = configure(db, seed_data, "guideline_ingestion")
    yield {"db": db, "actor": actor, "original": original, "provider": provider, "config": config, "seed": seed_data, "now": now}
    db.rollback()
    db.execute(text("DROP TRIGGER IF EXISTS document_accept_fault"))
    db.execute(text("DROP TRIGGER IF EXISTS document_create_fault"))
    db.refresh(actor)
    actor.user_role, actor.token_invalid_before = "super_admin", None
    db.query(AIFeedback).delete()
    db.query(AIDocumentExtractionRunAnchor).delete()
    db.query(AIRun).delete()
    db.query(AIFeatureConfig).delete()
    db.query(AIProvider).delete()
    db.query(AIAuditEvent).filter(AIAuditEvent.target == original.snapshot.original_id).delete(synchronize_session=False)
    db.query(AIDocumentSpanCandidate).filter_by(original_id=original.snapshot.original_id).delete(synchronize_session=False)
    db.query(AIDocumentOriginal).filter_by(original_id=original.snapshot.original_id).delete(synchronize_session=False)
    db.commit()


def request(case):
    return {"feature_key": "guideline_ingestion", "input": {"document_original_id": case["original"].snapshot.original_id, "question": "保留逐字原文及未知适用性"}}


def model_transport(case, *, mutate=None, usage="complete", bad_quote=False):
    packets = []

    def handler(outbound):
        packet = json.loads(outbound.content)
        packets.append(packet)
        public = json.loads(packet["messages"][-1]["content"] if case["provider"].kind == "chat" else packet["input"][0]["content"])
        assert set(public) == {"document_source", "question"}
        raw = public["document_source"]["text"]
        assert raw == case["original"].snapshot.text
        if mutate:
            mutate()
        value = envelope(
            case["provider"].kind,
            json.dumps({"spans": [{"proposed_heading": "待审工程原文", "clause_kind": "other", "start": 0, "end": len(raw), "quote": raw + ("错" if bad_quote else "")}]}, ensure_ascii=False),
        )
        if usage == "input_only":
            value["usage"].pop("completion_tokens" if case["provider"].kind == "chat" else "output_tokens")
        elif usage == "output_only":
            value["usage"].pop("prompt_tokens" if case["provider"].kind == "chat" else "input_tokens")
        elif usage == "missing":
            value.pop("usage")
        return httpx.Response(200, json=value)

    return httpx.MockTransport(handler), packets


async def queue(client, headers, case):
    response = await client.post("/api/ai/runs", headers=headers, json=request(case))
    assert response.status_code == 200, response.text
    claim = runtime.claim_next_run(case["db"])
    assert claim and claim[0] == response.json()["data"]["run_id"]
    return claim, response.json()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["chat", "responses"])
async def test_actual_current_context_queue_worker_trace_and_explicit_unreviewed_candidate(async_client, auth_headers, document_pipeline, kind, tmp_path):
    case, db = document_pipeline, document_pipeline["db"]
    headers = auth_headers(case["actor"].username)
    case["provider"].kind = kind
    case["provider"].temperature = 0.0 if kind == "chat" else 1.0
    db.commit()
    before = (db.query(AIDocumentSpanCandidate).count(), db.query(AIKnowledgeDocument).count())
    preview = await async_client.post("/api/ai/document-extraction/context", headers=headers, json=request(case)["input"])
    assert preview.status_code == 200, preview.text
    assert preview.json()["data"]["model_preview"]["document_source"]["text"] == case["original"].snapshot.text
    claim, queued = await queue(async_client, headers, case)
    assert queued["data"]["input_tokens"] is None and "document_original" not in queued["data"]
    assert db.get(AIDocumentExtractionRunAnchor, claim[0]) is not None
    transport, packets = model_transport(case)
    await runtime.execute_claimed(*claim, transport=transport)
    db.expire_all()
    run = db.get(AIRun, claim[0])
    assert run.status == "succeeded", (run.error_code, run.error_message)
    detail = await async_client.get(f"/api/ai/runs/{claim[0]}", headers=headers)
    assert detail.status_code == 200, detail.text
    data = detail.json()["data"]
    assert data["usage_receipt"] == {"input_tokens": 11, "output_tokens": 13, "complete": True, "model_call_attempted": True}
    assert data["result"]["document_extraction"]["spans"][0]["quote"] == case["original"].snapshot.text
    assert data["document_original"]["snapshot"]["text"] == case["original"].snapshot.text
    assert db.query(AIAuditEvent).filter_by(target=run.run_id, action=documents.ACCEPT).count() == 1
    feedback = await async_client.post(f"/api/ai/runs/{claim[0]}/feedback", headers=headers, json={"outcome": "accepted", "comment": "仅工程复核，不表示医学或条款覆盖正确"})
    assert feedback.status_code == 200, feedback.text
    trace = await async_client.get(f"/api/ai/admin/runs/{claim[0]}", headers=headers)
    assert trace.status_code == 200, trace.text
    assert trace.json()["data"]["frozen_request"]["payload"]["context"] == data["document_extraction_findings"]
    assert before == (db.query(AIDocumentSpanCandidate).count(), db.query(AIKnowledgeDocument).count())
    assert len(packets) == 1 and "document_review" not in str(packets[0]) and "authorization_note" not in str(packets[0])
    anchor = data["document_extraction_anchor"]
    trace_data = trace.json()["data"]
    for raw_key, expected, hash_key in (
        ("frozen_request_json", trace_data["frozen_request"], "input_hash"),
        ("frozen_evidence_json", data["evidence"], "evidence_hash"),
        ("frozen_context_metadata_json", data["context_metadata"], "metadata_hash"),
    ):
        assert c.parse_json(trace_data[raw_key]) == expected
        assert c.bytes_hash(trace_data[raw_key]) == anchor[hash_key]
    assert '"temperature":' + ("0.0" if kind == "chat" else "1.0") in trace_data["frozen_request_json"]
    for route in ("/api/ai/runs", "/api/ai/admin/runs"):
        history = await async_client.get(route, headers=headers, params={"feature_key": "guideline_ingestion", "document_original_id": case["original"].snapshot.original_id})
        assert history.status_code == 200 and [item["run_id"] for item in history.json()["data"]] == [claim[0]], history.text
    saved = await async_client.post(f"/api/ai/runs/{claim[0]}/document-candidates", headers=headers, json={"ordinal": 0})
    assert saved.status_code == 200, saved.text
    candidate = saved.json()["data"]
    assert candidate["governance"]["status"] == "draft" and candidate["governance"]["revision"] == 1
    assert candidate["governance"]["privacy_review"] == candidate["governance"]["faithfulness_review"] == "unknown"
    assert candidate["snapshot"]["proposal"]["quote"] == case["original"].snapshot.text
    assert candidate["snapshot"]["proposal"]["provenance"] == "unverified_submission"
    assert db.query(AIKnowledgeDocument).count() == before[1]
    duplicate = await async_client.post(f"/api/ai/runs/{claim[0]}/document-candidates", headers=headers, json={"ordinal": 0})
    assert duplicate.status_code == 409 and db.query(AIDocumentSpanCandidate).count() == before[0] + 1
    (tmp_path / f"actual-document-pipeline-{kind}.json").write_text(
        json.dumps(
            {
                "scope": "Actual synthetic JWT/SQLite/worker with MockTransport; no real model/clinical validation",
                "preview": preview.json(),
                "queued": queued,
                "detail": detail.json(),
                "trace": trace.json(),
                "outbound": packets[0],
                "saved_candidate": saved.json(),
                "save_request": {"ordinal": 0},
            },
            ensure_ascii=False,
            indent=2,
        )
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["chat", "responses"])
@pytest.mark.parametrize("usage,expected", [("input_only", (11, None)), ("output_only", (None, 13)), ("missing", (None, None))])
async def test_unknown_actual_usage_remains_nullable_in_terminal_audit_and_api(async_client, auth_headers, document_pipeline, kind, usage, expected):
    case, db = document_pipeline, document_pipeline["db"]
    case["provider"].kind = kind
    db.commit()
    headers = auth_headers(case["actor"].username)
    claim, _ = await queue(async_client, headers, case)
    transport, _ = model_transport(case, usage=usage)
    await runtime.execute_claimed(*claim, transport=transport)
    db.expire_all()
    run = db.get(AIRun, claim[0])
    assert run.status == "failed" and parse_record(run.result_json).result is None
    assert run.error_code == "DOCUMENT_PROVIDER_REPLY_INVALID"
    result = await async_client.get(f"/api/ai/runs/{claim[0]}", headers=headers)
    assert result.status_code == 200, result.text
    data = result.json()["data"]
    assert (data["input_tokens"], data["output_tokens"]) == expected
    assert data["usage_receipt"]["complete"] is False and data["result"] is None
    assert db.query(AIAuditEvent).filter_by(action=documents.ACCEPT, target=run.run_id).count() == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("when", ["queued", "inflight"])
@pytest.mark.parametrize("change", ["revoke", "role", "token", "provider", "feature", "prompt"])
async def test_current_original_actor_model_or_prompt_change_prevents_acceptance(async_client, auth_headers, document_pipeline, when, change):
    case, db = document_pipeline, document_pipeline["db"]
    claim, _ = await queue(async_client, auth_headers(case["actor"].username), case)

    def mutate():
        if change == "revoke":
            original = case["original"]
            from tests.test_ai_document_evidence_sources import cas

            sources.revoke_original(db, case["actor"], original.snapshot.original_id, {**cas(original), "basis_note": "本合成原件撤销，不能继续接收旧草稿。"})
        elif change == "role":
            case["actor"].user_role = "doctor"
        elif change == "token":
            case["actor"].token_invalid_before = case["now"] + datetime.timedelta(seconds=1)
        elif change == "provider":
            case["provider"].revision += 1
        elif change == "feature":
            case["config"].enabled = 0
        elif change == "prompt":
            case["config"].revision += 1
        db.commit()

    if when == "queued":
        mutate()
    transport, packets = model_transport(case, mutate=mutate if when == "inflight" else None)
    await runtime.execute_claimed(*claim, transport=transport)
    db.expire_all()
    run = db.get(AIRun, claim[0])
    assert run.status == "failed", (run.error_code, run.error_message)
    assert parse_record(run.result_json).result is None and db.query(AIAuditEvent).filter_by(action=documents.ACCEPT, target=run.run_id).count() == 0
    assert len(packets) == (1 if when == "inflight" else 0)
    receipt = documents.usage_receipt(db, run)
    assert receipt["complete"] is (when == "inflight")


@pytest.mark.asyncio
async def test_revoked_original_remains_truthfully_revoked_in_super_frozen_audit(async_client, auth_headers, document_pipeline):
    from tests.test_ai_document_evidence_sources import cas

    case, db = document_pipeline, document_pipeline["db"]
    headers = auth_headers(case["actor"].username)
    claim, _ = await queue(async_client, headers, case)
    transport, _ = model_transport(case)
    await runtime.execute_claimed(*claim, transport=transport)
    original = case["original"]
    sources.revoke_original(db, case["actor"], original.snapshot.original_id, {**cas(original), "basis_note": "合成原文撤销，保留已发布历史签署审计。"})
    db.commit()
    trace = await async_client.get(f"/api/ai/admin/runs/{claim[0]}", headers=headers)
    assert trace.status_code == 200, trace.text
    data = trace.json()["data"]
    assert data["document_original"]["governance"]["status"] == "revoked"
    assert data["document_original"]["eligible"] is False
    assert data["document_extraction_findings"]["document_review"]["status"] == "published"
    assert data["result"]["document_extraction"]["spans"][0]["quote"] == original.snapshot.text


@pytest.mark.asyncio
@pytest.mark.parametrize("change", [{"patient_id": 1}, {"encounter_ref": "wrong-encounter"}, {"input": {"text": "伪造原文"}}, {"input": {"document_original_id": None}}, {"input": {"question": " "}}])
async def test_other_business_scopes_or_caller_originals_cannot_queue(async_client, auth_headers, document_pipeline, change):
    case, db = document_pipeline, document_pipeline["db"]
    req = {**request(case), **change}
    if "input" in change:
        req["input"] = {**request(case)["input"], **change["input"]}
    response = await async_client.post("/api/ai/runs", headers=auth_headers(case["actor"].username), json=req)
    assert response.status_code == 422, response.text
    assert db.query(AIRun).count() == db.query(AIDocumentExtractionRunAnchor).count() == 0


@pytest.mark.asyncio
async def test_ordinary_doctor_cannot_preview_or_queue_private_original(async_client, auth_headers, document_pipeline):
    case, db = document_pipeline, document_pipeline["db"]
    headers = auth_headers(case["seed"]["doctor_user"].username)
    for path, body in (("/api/ai/document-extraction/context", request(case)["input"]), ("/api/ai/runs", request(case))):
        denied = await async_client.post(path, headers=headers, json=body)
        assert denied.status_code == 403 and case["original"].snapshot.text not in denied.text
    assert db.query(AIRun).count() == 0


@pytest.mark.asyncio
async def test_inflight_cancel_keeps_reported_usage_without_accepting_draft(async_client, auth_headers, document_pipeline):
    case, db = document_pipeline, document_pipeline["db"]
    headers = auth_headers(case["actor"].username)
    claim, _ = await queue(async_client, headers, case)

    def cancel():
        db.query(AIRun).filter_by(run_id=claim[0]).update({"status": "cancelled"})
        db.commit()

    transport, _ = model_transport(case, mutate=cancel)
    await runtime.execute_claimed(*claim, transport=transport)
    detail = await async_client.get(f"/api/ai/runs/{claim[0]}", headers=headers)
    assert detail.status_code == 200, detail.text
    data = detail.json()["data"]
    assert data["status"] == "cancelled" and data["result"] is None
    assert (data["input_tokens"], data["output_tokens"]) == (11, 13)
    assert db.query(AIAuditEvent).filter_by(action=documents.ACCEPT, target=claim[0]).count() == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["tokens", "error", "audit", "metadata", "result"])
async def test_actual_postflush_accept_faults_rollback_draft_and_preserve_real_usage(async_client, auth_headers, document_pipeline, fault):
    case, db = document_pipeline, document_pipeline["db"]
    claim, _ = await queue(async_client, auth_headers(case["actor"].username), case)
    if fault in {"tokens", "error", "result"}:
        assignment = "input_tokens=999" if fault == "tokens" else "result_json='{}'" if fault == "result" else "error_code='unexpected-success-error'"
        sql = f"CREATE TRIGGER document_accept_fault AFTER UPDATE ON hoimsystem_ai_run WHEN NEW.status='succeeded' BEGIN UPDATE hoimsystem_ai_run SET {assignment} WHERE run_id=NEW.run_id; END"
    else:
        effect = (
            "DELETE FROM hoimsystem_ai_audit_event WHERE event_id=NEW.event_id"
            if fault == "audit"
            else "UPDATE hoimsystem_ai_run SET " + ("context_metadata_json='{}'" if fault == "metadata" else "result_json='{}'") + " WHERE run_id=NEW.target"
        )
        sql = f"CREATE TRIGGER document_accept_fault AFTER INSERT ON hoimsystem_ai_audit_event WHEN NEW.action='run.document_extraction.accept' BEGIN {effect}; END"
    db.execute(text(sql))
    db.commit()
    transport, packets = model_transport(case)
    await runtime.execute_claimed(*claim, transport=transport)
    db.expire_all()
    run = db.get(AIRun, claim[0])
    assert run.status == "failed" and run.error_code == "RESULT_STORAGE_ERROR" and parse_record(run.result_json).result is None
    assert (run.input_tokens, run.output_tokens) == (11, 13) and len(packets) == 1
    assert db.query(AIAuditEvent).filter_by(action=documents.ACCEPT, target=run.run_id).count() == 0
    assert documents.usage_receipt(db, run)["complete"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize("terminal", ["fail", "cancel"])
async def test_actual_deleted_terminal_receipt_refuses_initial_and_fallback_transactions(async_client, auth_headers, document_pipeline, terminal):
    from fastapi import HTTPException

    case, db = document_pipeline, document_pipeline["db"]
    claim, _ = await queue(async_client, auth_headers(case["actor"].username), case)
    db.execute(
        text(
            f"CREATE TRIGGER document_accept_fault AFTER INSERT ON hoimsystem_ai_audit_event WHEN NEW.action='run.document_extraction.{terminal}' BEGIN DELETE FROM hoimsystem_ai_audit_event WHERE event_id=NEW.event_id; END"
        )
    )
    db.commit()

    def cancel():
        db.query(AIRun).filter_by(run_id=claim[0]).update({"status": "cancelled"})
        db.commit()

    transport, packets = model_transport(case, usage="input_only" if terminal == "fail" else "complete", mutate=cancel if terminal == "cancel" else None)
    with pytest.raises(HTTPException) as rejected:
        await runtime.execute_claimed(*claim, transport=transport)
    assert rejected.value.status_code == 409
    db.expire_all()
    run = db.get(AIRun, claim[0])
    assert run.status == ("running" if terminal == "fail" else "cancelled")
    assert run.result_json == "{}" and run.latency_ms is None and len(packets) == 1
    assert db.query(AIAuditEvent).filter(AIAuditEvent.target == run.run_id, AIAuditEvent.action.in_(documents.FINAL_ACTIONS)).count() == 0
    assert documents.usage_receipt(db, run) == {"input_tokens": None, "output_tokens": None, "complete": False, "model_call_attempted": None}


@pytest.mark.asyncio
async def test_actual_create_audit_trigger_cannot_add_fake_usage_to_queue(async_client, auth_headers, document_pipeline):
    case, db = document_pipeline, document_pipeline["db"]
    db.execute(
        text(
            "CREATE TRIGGER document_create_fault AFTER INSERT ON hoimsystem_ai_audit_event WHEN NEW.action='run.create' BEGIN UPDATE hoimsystem_ai_run SET input_tokens=999 WHERE run_id=NEW.target; END"
        )
    )
    db.commit()
    response = await async_client.post("/api/ai/runs", headers=auth_headers(case["actor"].username), json=request(case))
    assert response.status_code == 409, response.text
    assert db.query(AIRun).count() == db.query(AIDocumentExtractionRunAnchor).count() == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("ordinal", [-1, 64, True, 0.0, 1])
async def test_only_a_real_strict_ordinal_can_explicitly_create_a_candidate(async_client, auth_headers, document_pipeline, ordinal):
    case, db = document_pipeline, document_pipeline["db"]
    headers = auth_headers(case["actor"].username)
    claim, _ = await queue(async_client, headers, case)
    transport, _ = model_transport(case)
    await runtime.execute_claimed(*claim, transport=transport)
    before = db.query(AIDocumentSpanCandidate).count()
    rejected = await async_client.post(f"/api/ai/runs/{claim[0]}/document-candidates", headers=headers, json={"ordinal": ordinal})
    assert rejected.status_code == 422, rejected.text
    assert db.query(AIDocumentSpanCandidate).count() == before


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["audit", "candidate", "result", "anchor"])
async def test_actual_save_audit_fault_rolls_back_candidate_and_run_link(async_client, auth_headers, document_pipeline, fault):
    case, db = document_pipeline, document_pipeline["db"]
    headers = auth_headers(case["actor"].username)
    claim, _ = await queue(async_client, headers, case)
    transport, _ = model_transport(case)
    await runtime.execute_claimed(*claim, transport=transport)
    db.expire_all()
    original_result = db.get(AIRun, claim[0]).result_json
    before = db.query(AIDocumentSpanCandidate).count()
    actions = {
        "audit": "DELETE FROM hoimsystem_ai_audit_event WHERE event_id=NEW.event_id",
        "candidate": "UPDATE hoimsystem_ai_document_span_candidate SET candidate_json='{}' WHERE candidate_id=json_extract(NEW.detail_json,'$.candidate_id')",
        "result": "UPDATE hoimsystem_ai_run SET result_json='{}' WHERE run_id=NEW.target",
        "anchor": "UPDATE hoimsystem_ai_document_extraction_run_anchor SET input_hash='" + "0" * 64 + "' WHERE run_id=NEW.target",
    }
    db.execute(text("CREATE TRIGGER document_accept_fault AFTER INSERT ON hoimsystem_ai_audit_event WHEN NEW.action='run.document_extraction.candidate' BEGIN " + actions[fault] + "; END"))
    db.commit()
    rejected = await async_client.post(f"/api/ai/runs/{claim[0]}/document-candidates", headers=headers, json={"ordinal": 0})
    assert rejected.status_code == 409, rejected.text
    db.expire_all()
    assert db.get(AIRun, claim[0]).result_json == original_result
    assert db.query(AIDocumentSpanCandidate).count() == before
    assert db.query(AIAuditEvent).filter_by(action="run.document_extraction.candidate", target=claim[0]).count() == 0


@pytest.mark.asyncio
async def test_actual_anchor_protects_private_run_loading_after_all_markers_are_stripped(async_client, auth_headers, document_pipeline):
    from sqlalchemy import event

    case, db = document_pipeline, document_pipeline["db"]
    claim, _ = await queue(async_client, auth_headers(case["actor"].username), case)
    db.query(AIRun).filter_by(run_id=claim[0]).update({"feature_key": "operations_qa", "input_json": "{}", "result_json": "{}", "context_metadata_json": "{}", "evidence_json": "[]"})
    db.commit()
    statements = []
    selected_columns = []

    def observed(conn, cursor, statement, parameters, context, many):
        statements.append(statement)
        if context.compiled is not None:
            selected_columns.extend(item.keyname for item in context.compiled._result_columns)

    connection = db.get_bind()
    event.listen(connection, "before_cursor_execute", observed)
    try:
        denied = await async_client.get(f"/api/ai/runs/{claim[0]}", headers=auth_headers(case["seed"]["doctor_user"].username))
    finally:
        event.remove(connection, "before_cursor_execute", observed)
    assert denied.status_code == 403, denied.text
    # The #72 closed-path probe returns only one SQL boolean, not Task TEXT.
    # Check actual result-column names, including ORM table-prefixed aliases.
    private = {"input_json", "evidence_json", "context_metadata_json", "result_json", "source_json"}
    assert not any(name == field or name.endswith("_" + field) for name in selected_columns for field in private)
    closed = await async_client.get(f"/api/ai/runs/{claim[0]}", headers=auth_headers(case["actor"].username))
    assert closed.status_code == 409, closed.text


@pytest.mark.asyncio
async def test_revoked_source_cannot_save_a_new_candidate_from_frozen_audit(async_client, auth_headers, document_pipeline):
    from tests.test_ai_document_evidence_sources import cas

    case, db = document_pipeline, document_pipeline["db"]
    headers = auth_headers(case["actor"].username)
    claim, _ = await queue(async_client, headers, case)
    transport, _ = model_transport(case)
    await runtime.execute_claimed(*claim, transport=transport)
    original = case["original"]
    sources.revoke_original(db, case["actor"], original.snapshot.original_id, {**cas(original), "basis_note": "此原件撤销，仅保留历史审计，不再接受新候选。"})
    db.commit()
    before = db.query(AIDocumentSpanCandidate).count()
    denied = await async_client.post(f"/api/ai/runs/{claim[0]}/document-candidates", headers=headers, json={"ordinal": 0})
    assert denied.status_code == 409 and db.query(AIDocumentSpanCandidate).count() == before
