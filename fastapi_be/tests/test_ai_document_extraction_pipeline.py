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
async def test_actual_current_context_queue_worker_full_trace_feedback_without_candidate_or_knowledge_writes(async_client, auth_headers, document_pipeline, kind, tmp_path):
    case, db = document_pipeline, document_pipeline["db"]
    headers = auth_headers(case["actor"].username)
    case["provider"].kind = kind
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
    (tmp_path / f"actual-document-pipeline-{kind}.json").write_text(
        json.dumps(
            {
                "scope": "Actual synthetic JWT/SQLite/worker with MockTransport; no real model/clinical validation",
                "preview": preview.json(),
                "queued": queued,
                "detail": detail.json(),
                "trace": trace.json(),
                "outbound": packets[0],
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
    assert run.status == "failed" and run.result_json == "{}"
    assert run.error_code == "DOCUMENT_PROVIDER_REPLY_INVALID"
    result = await async_client.get(f"/api/ai/runs/{claim[0]}", headers=headers)
    assert result.status_code == 200, result.text
    data = result.json()["data"]
    assert (data["input_tokens"], data["output_tokens"]) == expected
    assert data["usage_receipt"]["complete"] is False and data["result"] is None
    assert db.query(AIAuditEvent).filter_by(action=documents.ACCEPT, target=run.run_id).count() == 0
