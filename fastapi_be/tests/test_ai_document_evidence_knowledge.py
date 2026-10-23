"""Actual main/SQL/worker checks for reviewed excerpts and source revocation."""

import copy
import json

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy import event, text
from sqlalchemy.dialects import mysql

from app.ai import document_evidence_sources as s
from app.ai.catalog import FEATURE_BY_KEY
from app.ai.governance import digest, encode_json
from app.ai.knowledge import evidence_is_current, retrieve_evidence
from app.ai.knowledge_sources import source_state
from app.ai.models import AIAuditEvent, AIFeatureConfig, AIFeedback, AIKnowledgeDocument, AIProvider, AIRun
from app.ai.runtime import claim_next_run, create_run, execute_claimed
from app.ai.schemas import KnowledgeReview, RunRequest
from app.routers import ai_admin
from tests.test_ai_document_evidence_sources import (
    approved_original,
    candidate_request,
    cas,
    document_case,  # noqa: F401 -- shared actual SQL fixture
    publish,
    review,
)


@pytest.fixture
def knowledge_case(document_case):  # noqa: F811 -- pytest injects the imported fixture
    db, actor, seed = document_case
    for model in (AIFeedback, AIRun, AIFeatureConfig, AIProvider):
        db.query(model).delete(synchronize_session=False)
    text = "私有原件背景不得发送模型。\ufeff医学指南问答：合成摘录😀\r\n仅展示已审核适用条件。\n未发布尾部同样不可外发。"
    parent = approved_original(db, actor, text)
    start, end = text.index("\ufeff"), text.index("\n未发布")
    candidate = s.create_candidate(db, actor, candidate_request(parent, start, end))
    db.commit()
    candidate = s.review_candidate(db, actor, candidate.snapshot.candidate_id, review(candidate))
    db.commit()
    request = publish(candidate)
    request["knowledge"]["feature_keys"] = ["guideline_qa"]
    publication = s.publish_candidate(db, actor, candidate.snapshot.candidate_id, request)
    db.commit()
    document = db.get(AIKnowledgeDocument, publication.snapshot.knowledge_document_id)
    provider = AIProvider(name="document synthetic", kind="chat", api_base="http://localhost:11434/v1", model="synthetic", enabled=1, allows_patient_data=1, created_by=actor.user_id)
    db.add(provider)
    db.flush()
    db.add(
        AIFeatureConfig(
            feature_key="guideline_qa",
            provider_id=provider.provider_id,
            enabled=1,
            allowed_roles_json=encode_json(FEATURE_BY_KEY["guideline_qa"].default_roles),
            validation_status="validated",
            validation_note="合成工程验证，不是医学有效性验证",
            updated_by=actor.user_id,
        )
    )
    db.commit()
    return db, actor, seed["doctor_user"], parent, candidate, publication, document


def revoke(case, axis):
    db, actor, _, parent, candidate, publication, _ = case
    functions = {"original": (s.revoke_original, parent), "candidate": (s.revoke_candidate, candidate), "publication": (s.revoke_publication, publication)}
    function, record = functions[axis]
    identity = getattr(record.snapshot, axis + "_id")
    function(db, actor, identity, {**cas(record), "basis_note": "来源已人工撤销，本测试不代表任何临床结论。"})
    db.commit()


def evidence(case):
    return retrieve_evidence(case[0], FEATURE_BY_KEY["guideline_qa"], "医学指南问答合成摘录", set())


def model_reply(request, requests, before_reply=None):
    payload = json.loads(json.loads(request.content)["messages"][-1]["content"])
    requests.append(payload)
    if before_reply:
        before_reply()
    source = next(item["source_id"] for item in payload["evidence"] if item["kind"] == "knowledge")
    result = {"summary": "合成待复核答复", "sections": [{"title": "依据", "content": "仅核对摘录内容", "source_ids": [source]}], "warnings": [], "missing_data": []}
    return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(result, ensure_ascii=False)}}], "usage": {"prompt_tokens": 11, "completion_tokens": 13}})


def test_retrieval_uses_only_reviewed_exact_excerpt_and_complete_source_chain(knowledge_case):
    db, _, _, parent, _, publication, document = knowledge_case
    rows = evidence(knowledge_case)
    assert len(rows) == 1 and rows[0]["content"] == publication.snapshot.quote
    assert rows[0]["content"].startswith("\ufeff") and "😀\r\n" in rows[0]["content"]
    assert parent.snapshot.text not in encode_json(rows) and "私有原件背景" not in encode_json(rows)
    assert source_state(db, document) == "current" and evidence_is_current(db, rows)
    assert rows[0]["source_snapshot_hash"] == publication.content_hash


@pytest.mark.parametrize("field", ["source_id", "title", "version", "source_uri", "reviewed_at", "content", "chunk_hash", "source_snapshot_hash", "kind"])
def test_task_excerpt_tampering_cannot_reuse_valid_publication_hash(knowledge_case, field):
    rows = copy.deepcopy(evidence(knowledge_case))
    rows[0][field] = "changed"
    if field == "content":
        rows[0]["chunk_hash"] = digest(rows[0]["content"])
    assert not evidence_is_current(knowledge_case[0], rows)


@pytest.mark.parametrize("axis", ["original", "candidate", "publication"])
@pytest.mark.parametrize("inflight", [False, True])
@pytest.mark.asyncio
async def test_revocation_before_or_during_model_does_not_accept_result(knowledge_case, axis, inflight):
    db, _, doctor, *_ = knowledge_case
    run = create_run(db, doctor, RunRequest(feature_key="guideline_qa", input={"question": "医学指南问答合成摘录"}))
    if not inflight:
        revoke(knowledge_case, axis)
    requests = []
    transport = httpx.MockTransport(lambda request: model_reply(request, requests, lambda: revoke(knowledge_case, axis)))
    await execute_claimed(*claim_next_run(db), transport=transport)
    db.refresh(run)
    assert len(requests) == int(inflight) and run.status == "failed" and run.result_json == "{}"
    assert run.error_code == "TASK_NO_LONGER_AUTHORIZED"
    assert (run.input_tokens, run.output_tokens) == ((11, 13) if inflight else (0, 0))
    assert not db.query(AIAuditEvent).filter_by(action="run.succeeded", target=run.run_id).count()


@pytest.mark.asyncio
async def test_success_sends_only_excerpt_then_revocation_hides_ordinary_history_and_feedback(knowledge_case, async_client, auth_headers):
    db, actor, doctor, *_ = knowledge_case
    run = create_run(db, doctor, RunRequest(feature_key="guideline_qa", input={"question": "医学指南问答合成摘录"}))
    requests = []
    await execute_claimed(*claim_next_run(db), transport=httpx.MockTransport(lambda request: model_reply(request, requests)))
    db.refresh(run)
    assert run.status == "succeeded" and len(requests) == 1
    assert "私有原件背景" not in encode_json(requests) and "未发布尾部" not in encode_json(requests)
    headers = auth_headers(doctor.username)
    path = "/api/ai/runs/" + run.run_id
    assert (await async_client.get(path, headers=headers)).status_code == 200
    frozen = run.input_json
    revoke(knowledge_case, "original")
    assert (await async_client.get(path, headers=headers)).status_code == 409
    assert (await async_client.post(path + "/feedback", headers=headers, json={"outcome": "rejected", "comment": "已失效"})).status_code == 409
    listed = await async_client.get("/api/ai/runs", headers=headers, params={"feature_key": "guideline_qa"})
    assert listed.status_code == 200 and all(row["run_id"] != run.run_id for row in listed.json()["data"])
    audit = await async_client.get("/api/ai/admin/runs/" + run.run_id, headers=auth_headers(actor.username))
    assert audit.status_code == 200
    db.refresh(run)
    assert run.input_json == frozen and not db.query(AIFeedback).filter_by(run_id=run.run_id).count()


@pytest.mark.parametrize("strip_markers", [False, True])
@pytest.mark.asyncio
async def test_generic_knowledge_review_cannot_bypass_document_lineage(knowledge_case, strip_markers, async_client, auth_headers):
    db, actor, _, _, _, _, document = knowledge_case
    if strip_markers:
        document.source_kind = document.source_snapshot_hash = None
        document.source_uri = "manual://forged"
        db.commit()
    audit_count = db.query(AIAuditEvent).filter_by(action="knowledge.review", target=document.document_id).count()
    reply = await async_client.post(
        "/api/ai/admin/knowledge/" + document.document_id + "/review", headers=auth_headers(actor.username), json={"content_hash": document.content_hash, "status": "retired"}
    )
    assert reply.status_code == 409
    db.refresh(document)
    assert document.status == "published"
    assert db.query(AIAuditEvent).filter_by(action="knowledge.review", target=document.document_id).count() == audit_count
    headers = auth_headers(actor.username)
    detail = await async_client.get("/api/ai/admin/knowledge/" + document.document_id, headers=headers)
    listed = await async_client.get("/api/ai/admin/knowledge", headers=headers)
    assert detail.status_code == listed.status_code == 200
    assert detail.json()["data"]["document_evidence_bound"] is True
    assert next(row for row in listed.json()["data"] if row["document_id"] == document.document_id)["document_evidence_bound"] is True
    if strip_markers:
        assert source_state(db, document) == "invalid_binding" and evidence(knowledge_case) == []


@pytest.mark.parametrize("strip_markers", [False, True])
def test_document_review_uses_current_nonwaiting_classification_before_any_knowledge_exclusive_lock(knowledge_case, strip_markers):
    db, actor, _, _, _, _, document = knowledge_case
    if strip_markers:
        document.source_kind = document.source_snapshot_hash = None
        document.source_uri = "manual://forged"
        db.commit()
    document_id, content_hash = document.document_id, document.content_hash
    statements, exclusive_tables = [], []

    def observe(state):
        if state.is_select:
            sql = str(state.statement.compile(dialect=mysql.dialect()))
            statements.append(sql)
            if "FOR UPDATE" in sql:
                exclusive_tables.append(tuple(getattr(table, "name", None) for table in state.statement.get_final_froms()))

    event.listen(db, "do_orm_execute", observe)
    try:
        with pytest.raises(HTTPException) as rejected:
            ai_admin.review_knowledge(document_id, KnowledgeReview(content_hash=content_hash, status="retired"), db=db, user=actor)
        assert rejected.value.status_code == 409
    finally:
        event.remove(db, "do_orm_execute", observe)
        db.rollback()
    knowledge = [statement for statement in statements if "FROM hoimsystem_ai_knowledge_document" in statement]
    assert len(knowledge) == 1 and knowledge[0].rstrip().endswith("LOCK IN SHARE MODE NOWAIT")
    # Shared management authority takes technical Gates before User. The
    # document/publication classifier must still never take a business X lock.
    technical_gates = {
        "hoimsystem_ai_charge_write_gate",
        "hoimsystem_ai_satisfaction_write_gate",
        "hoimsystem_ai_inventory_write_gate",
        "hoimsystem_ai_infection_write_gate",
        "hoimsystem_ai_research_write_gate",
        "hoimsystem_ai_operations_write_gate",
        "hoimsystem_ai_training_write_gate",
    }
    assert all(len(tables) == 1 and tables[0] in technical_gates for tables in exclusive_tables)
    publication = [statement for statement in statements if "FROM hoimsystem_ai_document_knowledge_publication" in statement]
    if strip_markers:
        assert len(publication) == 1 and publication[0].rstrip().endswith("LOCK IN SHARE MODE NOWAIT")


@pytest.mark.parametrize("uri", ["hoim://document-evidence/00000000-0000-0000-0000-000000000071", "HOIM://DOCUMENT-EVIDENCE/fake"])
@pytest.mark.asyncio
async def test_manual_knowledge_cannot_spoof_document_evidence_uri(seed_data, async_client, auth_headers, uri):
    reply = await async_client.post(
        "/api/ai/admin/knowledge",
        headers=auth_headers("super01"),
        json={"title": "手工合成条目", "version": "v1", "source_uri": uri, "content": "不能冒充已审核原文证据的手工正文内容。", "feature_keys": ["guideline_qa"]},
    )
    assert reply.status_code == 422


@pytest.mark.parametrize("content", ["汉" * 21846, "a" * 65536, "safe" * 10 + "\ud800"])
@pytest.mark.asyncio
async def test_manual_knowledge_complete_utf8_capacity_is_enforced_before_sql(seed_data, db_session, async_client, auth_headers, content):
    count = db_session.query(AIKnowledgeDocument).count()
    request = {"title": "UTF8容量合成测试", "version": "v1", "source_uri": "synthetic://capacity", "content": content, "feature_keys": ["guideline_qa"]}
    reply = await async_client.post("/api/ai/admin/knowledge", headers={**auth_headers("super01"), "Content-Type": "application/json"}, content=json.dumps(request).encode())
    assert reply.status_code == 422 and db_session.query(AIKnowledgeDocument).count() == count
    details = reply.json().get("detail")
    if isinstance(details, list):
        assert all("input" not in item for item in details)


@pytest.mark.asyncio
async def test_document_routes_are_mounted_in_real_main_with_super_only_role(seed_data, async_client, auth_headers):
    path = "/api/ai/admin/document-evidence/options"
    assert (await async_client.get(path, headers=auth_headers("super01"))).status_code == 200
    assert (await async_client.get(path, headers=auth_headers(seed_data["doctor_user"].username))).status_code == 403


@pytest.mark.parametrize("reader", ["list", "detail"])
def test_generic_knowledge_readers_recheck_stale_super_before_private_body(db_session, seed_data, reader):
    actor = seed_data["super_admin_user"]
    db_session.execute(text("UPDATE hoimsystem_users SET user_role='doctor' WHERE user_id=:pk"), {"pk": actor.user_id})
    assert actor.user_role == "super_admin"
    statements = []

    def observe(state):
        if state.is_select:
            statements.append(str(state.statement.compile(dialect=mysql.dialect())))

    event.listen(db_session, "do_orm_execute", observe)
    try:
        with pytest.raises(HTTPException) as rejected:
            if reader == "list":
                ai_admin.list_knowledge(db=db_session, user=actor)
            else:
                ai_admin.knowledge_detail("no-private-body-read", db=db_session, user=actor)
        assert rejected.value.status_code == 403
    finally:
        event.remove(db_session, "do_orm_execute", observe)
        db_session.rollback()
    assert len(statements) == 1 and "hoimsystem_users" in statements[0] and statements[0].rstrip().endswith("LOCK IN SHARE MODE")


@pytest.mark.parametrize("fault", ["metadata", "result", "audit", "source"])
@pytest.mark.asyncio
async def test_actual_sql_acceptance_fault_rolls_back_result_audit_and_source(knowledge_case, fault):
    db, _, doctor, _, _, _, document = knowledge_case
    run = create_run(db, doctor, RunRequest(feature_key="guideline_qa", input={"question": "医学指南问答合成摘录"}))
    run_id, document_id = run.run_id, document.document_id
    if fault == "audit":
        sql = "AFTER INSERT ON hoimsystem_ai_audit_event WHEN NEW.action='run.document_evidence.accept' BEGIN DELETE FROM hoimsystem_ai_audit_event WHERE event_id=NEW.event_id; END"
    else:
        mutation = {
            "metadata": "UPDATE hoimsystem_ai_run SET context_metadata_json='{}' WHERE run_id=NEW.run_id;",
            "result": "UPDATE hoimsystem_ai_run SET result_json='{}' WHERE run_id=NEW.run_id;",
            "source": "UPDATE hoimsystem_ai_knowledge_document SET title='trigger changed' WHERE document_id='" + document_id + "';",
        }[fault]
        sql = "AFTER UPDATE OF status ON hoimsystem_ai_run WHEN NEW.status='succeeded' BEGIN " + mutation + " END"
    db.execute(text("CREATE TRIGGER document_accept_fault " + sql))
    db.commit()
    requests = []
    try:
        await execute_claimed(*claim_next_run(db), transport=httpx.MockTransport(lambda request: model_reply(request, requests)))
    finally:
        db.execute(text("DROP TRIGGER document_accept_fault"))
        db.commit()
    db.expire_all()
    run = db.get(AIRun, run_id)
    assert len(requests) == 1 and run.status == "failed" and run.error_code == "RESULT_STORAGE_ERROR"
    assert run.result_json == "{}" and (run.input_tokens, run.output_tokens) == (11, 13)
    assert not db.query(AIAuditEvent).filter_by(action="run.document_evidence.accept", target=run_id).count()
    assert db.get(AIKnowledgeDocument, document_id).title != "trigger changed"
