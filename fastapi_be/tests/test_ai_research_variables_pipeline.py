"""Actual Main/JWT -> shared durable claim -> controlled provider ASGI -> SQL.

Synthetic data only; controlled Chat/Responses replies are not model inference.
Every result/source/scope is fetched as its own complete bounded HTTP part.
"""

import hashlib
import json
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import event, inspect
from sqlalchemy.orm import Session

from app import database
from app.ai import runtime
from app.ai.models import AIAuditEvent, AIRun
from app.ai.research_cohort_registry import review_registry_original
from app.ai.research_variables_run_models import AIResearchVariableRunArtifact, AIResearchVariableRunResult
from app.ai.research_variables_task_contract import FEATURE_KEY, VariableTaskSource, canonical
from app.models import MedicalRecord, Patient, Registration
from tests.test_ai_research_cohort_contract import BASIS
from tests.test_ai_research_variables_configuration import configured as configured
from tests.test_ai_research_variables_task_context import research_case as research_case
from tests.test_ai_research_variables_task_context import task_factory as task_factory
from tests.test_ai_research_variables_task_result import draft, envelope


@pytest.fixture
def main_case(db_session, configured, task_factory, auth_headers):
    case, scope, acl, permissions, batch, dictionary = task_factory()
    # Scalars/headers are frozen before closing SQL or entering provider I/O.
    return {
        "case": case,
        "scope": scope,
        "acl": acl,
        "permissions": permissions,
        "batch": batch,
        "dictionary": dictionary,
        "admin": auth_headers(case["admin_user"].username),
        "super": auth_headers(case["super_admin_user"].username),
        "super_id": inspect(case["super_admin_user"]).identity[0],
        "provider_id": inspect(configured[2]).identity[0],
        "provider": configured[2],
        "selection": {"research_variable_batch_id": batch["batch_id"], "question": "\ufeff原样问题\r\n🧪e\u0301"},
    }


async def queued_task(client, headers, selection):
    value = await client.post("/api/ai/runs", headers=headers, json={"feature_key": FEATURE_KEY, "input": selection, "preview": False})
    assert value.status_code == 200, value.text
    packet = value.json()["data"]
    assert packet["status"] == "queued" and packet["result"] is None
    assert packet["usage_receipt"] is None and packet["input_tokens"] is packet["output_tokens"] is None
    return packet


def body_observer():
    reads = []

    def record(state):
        if state.is_select and hasattr(state.statement, "selected_columns"):
            # Direct selected columns, across every HTTP/worker Session. Size
            # probes and computed JSON presence booleans are not BODY reads.
            reads.extend(
                str(column.key) for column in state.statement.selected_columns if column.key in {"input_json", "result_json", "evidence_json", "context_metadata_json", "source_json", "binding_json"}
            )

    event.listen(Session, "do_orm_execute", record)
    return reads, record


@pytest.mark.asyncio
@pytest.mark.parametrize("kind,counts", [("chat", "full"), ("responses", "full"), ("chat", "absent"), ("responses", "partial")])
async def test_actual_main_jwt_shared_queue_native_protocol_split_blob_nullable_receipt_history_trace_feedback(db_session, main_case, async_client, tmp_path, kind, counts):
    value = main_case
    value["provider"].kind = kind
    db_session.commit()
    before = {model.__name__: db_session.query(model).count() for model in (Patient, MedicalRecord, Registration)}
    preview = await async_client.post("/api/ai/research-variables/context", headers=value["admin"], json=value["selection"])
    assert preview.status_code == 200, preview.text
    inspected = preview.json()["data"]
    assert inspected["model_preview"]["included"] is False
    assert inspected["research_variable_binding"]["batch_id"] == value["batch"]["batch_id"]
    assert "research_variable_source" not in inspected["context"] and "snapshot" not in inspected["context"]
    queued = await queued_task(async_client, value["admin"], value["selection"])
    identifier = queued["run_id"]
    with database.SessionLocal() as db:
        claim = runtime.claim_next_run(db)
        assert claim is not None and claim[0] == identifier
        stored = db.get(AIResearchVariableRunArtifact, identifier)
        assert stored.claim_event_id is not None and stored.dispatch_event_id is None
    running_response = await async_client.get("/api/ai/runs/" + identifier, headers=value["admin"])
    assert running_response.status_code == 200, running_response.text
    running = running_response.json()["data"]
    assert running["status"] == "running" and running["usage_receipt"] is None
    db_session.close()
    active, outbound = set(), []

    def checkout(connection, record, proxy):
        active.add(id(record))

    def checkin(connection, record):
        active.discard(id(record))

    provider = FastAPI()

    @provider.post("/v1/chat/completions")
    @provider.post("/v1/responses")
    async def reply(request: Request):
        assert not active, "Shared worker retained a SQL connection across provider I/O"
        body = await request.json()
        outbound.append(body)
        payload = json.loads(body["messages"][1]["content"] if kind == "chat" else body["input"][0]["content"])
        assert set(payload) == {"research_variable_source", "question"}
        source = VariableTaskSource.model_validate(payload["research_variable_source"])
        assert payload["question"] == value["selection"]["question"]
        assert body.get("store") is False and not body.get("tools")
        assert not any(key in canonical(payload) for key in ("patient_ids", "identity_key", "patient_authorizations", "acl_id", "original_authority_text"))
        usage = False if counts == "absent" else {"input_tokens": 11} if counts == "partial" else True
        return JSONResponse(envelope(kind, canonical(draft(source)), usage))

    engine = db_session.bind
    event.listen(engine, "checkout", checkout)
    event.listen(engine, "checkin", checkin)
    try:
        await runtime.execute_claimed(*claim, transport=httpx.ASGITransport(app=provider))
        assert not active and len(outbound) == 1
    finally:
        event.remove(engine, "checkout", checkout)
        event.remove(engine, "checkin", checkin)
    detail_response = await async_client.get("/api/ai/runs/" + identifier, headers=value["admin"])
    assert detail_response.status_code == 200, detail_response.text
    detail = detail_response.json()["data"]
    assert detail["status"] == "succeeded" and detail["result"] is None
    assert detail["usage_receipt_status"] == "recorded"
    assert (detail["input_tokens"], detail["output_tokens"]) == ((None, None) if counts == "absent" else (11, None) if counts == "partial" else (11, 13))
    assert detail["usage_receipt"]["model_call_attempted"] is True
    assert detail["automatic_export"] is detail["automatic_clinical_write"] is False
    parts = {}
    for part, path in detail["parts"].items():
        response = await async_client.get("/api" + path, headers=value["admin"])
        assert response.status_code == 200, (part, response.text)
        parts[part] = response.json()
        assert "code" not in parts[part] and len(response.content) <= 8388608
    literal = parts["result"]["result"]["research_variable_extraction"]["literal_draft"]
    assert literal["candidates"] and parts["result"]["reference"] == detail["result_reference"]
    source = VariableTaskSource.model_validate(parts["source"]["source"])
    assert literal["candidates"] == draft(source)["candidates"]
    trace_response = await async_client.get("/api/ai/admin/runs/" + identifier, headers=value["super"])
    assert trace_response.status_code == 200, trace_response.text
    trace = trace_response.json()["data"]
    assert trace["frozen_audit"] is True and trace["execution_current"] is False
    for raw, anchor in (("input_json", "input_hash"), ("evidence_json", "evidence_hash"), ("context_metadata_json", "metadata_hash")):
        assert hashlib.sha256(trace["raw_frozen_json"][raw].encode()).hexdigest() == trace["research_variable_artifact"][anchor]
    for part, path in trace["parts"].items():
        assert path.startswith("/ai/admin/runs/")
        response = await async_client.get("/api" + path, headers=value["super"])
        assert response.status_code == 200, (part, response.text)
        assert response.json() == parts[part]
    params = {"feature_key": FEATURE_KEY, "research_variable_batch_id": value["batch"]["batch_id"]}
    history = await async_client.get("/api/ai/runs", headers=value["admin"], params=params)
    admin_history = await async_client.get("/api/ai/admin/runs", headers=value["super"], params=params)
    assert history.status_code == admin_history.status_code == 200, (history.text, admin_history.text)
    assert [row["run_id"] for row in history.json()["data"]] == [identifier]
    assert [row["run_id"] for row in admin_history.json()["data"]] == [identifier]
    feedback = await async_client.post("/api/ai/runs/" + identifier + "/feedback", headers=value["admin"], json={"outcome": "modified", "comment": "人工仍需逐项核实候选，不构成正式矩阵"})
    assert feedback.status_code == 200, feedback.text
    with database.SessionLocal() as db:
        assert before == {model.__name__: db.query(model).count() for model in (Patient, MedicalRecord, Registration)}
        run = db.get(AIRun, identifier)
        artifact = db.get(AIResearchVariableRunArtifact, identifier)
        blob = db.get(AIResearchVariableRunResult, identifier)
        assert len(run.input_json.encode()) <= 65535 and len(run.result_json.encode()) < 2000
        assert artifact.usage_event_id and blob.accept_audit_event_id and artifact.dispatch_event_id
        for action in ("create", "claim", "dispatch", "usage", "accept", "feedback"):
            assert db.query(AIAuditEvent).filter_by(target=identifier, action="research_variable_run." + action).count() == 1
    (tmp_path / f"actual-research-variable-pipeline-{kind}-{counts}.json").write_text(
        json.dumps(
            {
                "preview": preview.json(),
                "queued": queued,
                "running": running,
                "detail": detail,
                "trace": trace,
                "parts": parts,
                "history": history.json(),
                "admin_history": admin_history.json(),
                "feedback": feedback.json(),
                "outbound": outbound,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


@pytest.mark.asyncio
async def test_shared_terminal_duplicate_and_wrong_lease_after_actual_http_source_loss_never_read_task_body_or_resend(db_session, main_case, async_client):
    value = main_case
    queued = await queued_task(async_client, value["admin"], value["selection"])
    identifier = queued["run_id"]
    with database.SessionLocal() as db:
        claim = runtime.claim_next_run(db)
    assert claim[0] == identifier
    db_session.close()
    calls = []

    async def reply(request):
        calls.append(request.url.path)
        source = VariableTaskSource.model_validate(json.loads(json.loads(request.content)["messages"][1]["content"])["research_variable_source"])
        with database.SessionLocal() as db:
            review_registry_original(
                db, SimpleNamespace(user_id=value["super_id"]), "authorization", value["permissions"][1]["source_record_id"], {"expected_revision": 2, "basis_note": BASIS}, revoke=True
            )
        return httpx.Response(200, json=envelope("chat", canonical(draft(source))))

    await runtime.execute_claimed(*claim, transport=httpx.MockTransport(reply))
    reads, record = body_observer()
    try:
        await runtime.execute_claimed(*claim, transport=httpx.MockTransport(reply))
        await runtime.execute_claimed(identifier, "wrong-lease", transport=httpx.MockTransport(reply))
        for path in ("/api/ai/runs/" + identifier, "/api/ai/admin/runs/" + identifier, "/api/ai/runs/" + identifier + "/research-variables/receipt"):
            response = await async_client.get(path, headers=value["super"])
            assert response.status_code == 403, response.text
    finally:
        event.remove(Session, "do_orm_execute", record)
    assert calls == ["/v1/chat/completions"] and not reads
    with database.SessionLocal() as db:
        run = db.get(AIRun, identifier)
        artifact = db.get(AIResearchVariableRunArtifact, identifier)
        assert run.status == "failed" and artifact.usage_event_id is not None
        assert db.query(AIAuditEvent).filter_by(target=identifier, action="research_variable_run.usage").count() == 1
        assert db.get(AIResearchVariableRunResult, identifier) is None
