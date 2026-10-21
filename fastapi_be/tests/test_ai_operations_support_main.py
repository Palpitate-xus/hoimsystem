"""Actual Main/JWT -> shared queue -> local ASGI -> committed split parts."""

import asyncio
import json

import pytest
from fastapi.routing import APIRoute
from sqlalchemy import event, text
from sqlalchemy.orm import Session

from app.ai import operations_support_attempts as attempts
from app.ai import operations_support_contract as c
from app.ai import operations_support_receipts as receipts
from app.ai import operations_support_registry as registry
from app.ai import operations_support_storage as storage
from app.ai import runtime as shared
from app.ai.models import AIAuditEvent, AIFeedback, AIRun
from app.ai.operations_support_run_models import AIOperationsRunArtifact, AIOperationsRunResult
from app.ai.operations_support_usage_contract import usage
from tests.test_ai_operations_support_configuration import actors as actors
from tests.test_ai_operations_support_configuration import configured as configured
from tests.test_ai_operations_support_configuration import source as source
from tests.test_ai_operations_support_execution import provider_service
from tests.test_ai_operations_support_storage import selection

BASE = "/api/ai/operations-support"


@pytest.fixture
def pipeline(configured, auth_headers, monkeypatch):
    from app import database

    db, registrar, creator, reviewer, admin = configured[0]
    names = [u.username for u in (registrar, creator, reviewer, admin)]
    headers = [auth_headers(name) for name in names]
    engine = db.get_bind()
    value = dict(active=[], connections=set(), reads=[], state={"authority_lost": False}, headers=headers, owner=admin.user_id, stopper=registrar.user_id, original_id=configured[1]["original_id"], case_id=configured[3]["case_id"])

    def observe(conn, cursor, statement, params, context, many):
        if value["state"]["authority_lost"] and statement.lstrip().lower().startswith("select"):
            protected = [*storage.RUN_TEXT, "source_json", "prompt_snapshot_json", "execution_snapshot_json", "identity_json", "content_text", "draft_json", "published_review_json", "review_basis", "private_json", "public_json"]
            value["reads"].extend(column[0] for column in cursor.description or [] if any(column[0] == key or column[0].endswith("_" + key) for key in protected))

    def checkout(connection, record, proxy):
        value["connections"].add(id(connection))

    def checkin(connection, record):
        value["connections"].discard(id(connection))

    class TrackedSession(Session):
        def __init__(self):
            super().__init__(bind=engine, autoflush=False)
            value["active"].append(self)

        def close(self):
            try:
                super().close()
            finally:
                if self in value["active"]:
                    value["active"].remove(self)

    factory = TrackedSession

    value["factory"] = factory
    callbacks = [("after_cursor_execute", observe), ("checkout", checkout), ("checkin", checkin)]
    for name, callback in callbacks:
        event.listen(engine, name, callback)
    monkeypatch.setattr(database, "SessionLocal", factory)
    yield value
    for name, callback in callbacks:
        event.remove(engine, name, callback)


async def create(client, configured, value, *, dedicated=False, kind="chat"):
    db = configured[0][0]
    configured[-2].kind = kind
    body = selection(configured)
    db.commit()
    db.close()
    response = await client.post(BASE + "/tasks" if dedicated else "/api/ai/runs", headers=value["headers"][3], json=body if dedicated else dict(feature_key="operations_support", input=body))
    assert response.status_code == 200, response.text
    metadata = response.json()["data"]
    assert metadata["status"] == "queued" and metadata["binding"]["operations_case_id"] == value["case_id"]
    value["identifier"] = metadata["run_id"]
    with value["factory"]() as db:
        claimed = shared.claim_next_run(db)
    assert claimed is not None and claimed[0] == value["identifier"] and len(claimed) == 2
    value["lease"] = claimed[1]
    return metadata


def receipt(value):
    with value["factory"]() as db:
        return receipts.read_receipt(db, attempts.technical_header(db, value["identifier"]))


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["chat", "responses"])
@pytest.mark.parametrize("shape", ["full", "missing", "partial", "partial_total"])
async def test_actual_main_jwt_shared_worker_nullable_success_full_parts_and_feedback(configured, pipeline, async_client, kind, shape, tmp_path):
    value = pipeline
    await create(async_client, configured, value, dedicated=shape == "partial_total", kind=kind)

    def reply(body):
        if shape == "missing":
            body.pop("usage")
        elif shape in {"partial", "partial_total"}:
            body["usage"] = {"prompt_tokens" if kind == "chat" else "input_tokens": 11}
            if shape == "partial_total":
                body["usage"]["total_tokens"] = 24
        return body

    transport, calls = provider_service(value, kind, reply)
    await shared.execute_claimed(value["identifier"], value["lease"], transport=transport)
    actual = receipt(value)
    assert actual.status == "succeeded" and actual.usage.model_dump() == usage(None if shape == "missing" else 11, 13 if shape == "full" else None, True)
    packets = []
    parts = {}
    for name in ("task", "source", "binding", "result"):
        response = await async_client.get(BASE + f"/tasks/{value['identifier']}/parts/{name}", headers=value["headers"][3])
        assert response.status_code == 200, response.text
        assert response.headers["X-AI-Parts-Wire"] == "canonical_json_body_no_envelope"
        assert response.content == c.canonical_json(response.json()).encode()
        parts[name] = response.json()
        packets.append(dict(method="GET", path=BASE + f"/tasks/{value['identifier']}/parts/{name}", status=response.status_code, body=response.text, parts_wire=response.headers["X-AI-Parts-Wire"]))
    assert parts["result"]["observations"][0]["evidence"][0]["quote"] == "😀\r\n\x00"
    assert registry.raw_sha(parts["task"]["prompt_snapshot_json"]) == parts["task"]["binding"]["prompt_snapshot_hash"]
    with value["factory"]() as db:
        artifact = db.get(AIOperationsRunArtifact, value["identifier"])
        result = db.get(AIOperationsRunResult, value["identifier"])
        assert len({artifact.created_audit_event_id, artifact.claim_event_id, artifact.dispatch_event_id, artifact.usage_event_id, result.accept_audit_event_id}) == 5
        for key, raw in parts["task"]["raw"].items():
            assert raw.encode() == getattr(db.get(AIRun, value["identifier"]), key).encode()
    comment = "\ufeff人工独立复核😀\r\n\x00  尾部"
    response = await async_client.post(f"/api/ai/runs/{value['identifier']}/feedback", headers=value["headers"][3], json=dict(outcome="modified", comment=comment))
    assert response.status_code == 200, response.text
    key = response.json()["data"]["feedback_id"]
    with value["factory"]() as db:
        assert db.get(AIFeedback, key).comment.encode() == comment.encode()
        assert db.query(AIAuditEvent).filter_by(target=value["identifier"], action="operations.task.feedback").count() == 1
    for url, header, expected in [
        (f"/api/ai/runs/{value['identifier']}", 3, "run"),
        (f"/api/ai/runs?feature_key=operations_support&operations_case_id={value['case_id']}", 3, "list"),
        (BASE + f"/tasks?case_id={value['case_id']}", 3, "directory"),
        (f"/api/ai/admin/runs/{value['identifier']}", 0, "trace"),
    ]:
        response = await async_client.get(url, headers=value["headers"][header])
        assert response.status_code == 200, (url, response.text)
        data = response.json()["data"]
        if expected == "run":
            assert data["status"] == "succeeded"
        elif expected == "list":
            assert any(item["run_id"] == value["identifier"] for item in data)
        elif expected == "directory":
            assert any(item["run_id"] == value["identifier"] for item in data["items"])
        else:
            assert set(data["parts"]) == set(parts) and data["parts_require_independent_current_reads"]
    await shared.execute_claimed(value["identifier"], value["lease"], transport=transport)
    assert len(calls) == 1
    (tmp_path / "actual-main-task-packets.json").write_text(json.dumps(packets, ensure_ascii=False, indent=2))


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["withdraw", "cancel"])
async def test_actual_main_held_worker_duplicate_source_loss_or_cancel_keeps_partial_paid(configured, pipeline, async_client, action):
    value = pipeline
    await create(async_client, configured, value)
    entered, release = asyncio.Event(), asyncio.Event()

    async def reply(body):
        entered.set()
        await release.wait()
        body["usage"] = {"prompt_tokens": 11}
        return body

    transport, calls = provider_service(value, callback=reply)
    first = asyncio.create_task(shared.execute_claimed(value["identifier"], value["lease"], transport=transport))
    try:
        await asyncio.wait_for(entered.wait(), 10)
        await shared.execute_claimed(value["identifier"], value["lease"], transport=transport)
        if action == "withdraw":
            response = await async_client.post(BASE + f"/originals/{value['original_id']}/revoke", headers=value["headers"][0], json=dict(revision=1, reason="在途完整来源撤回"))
            assert response.status_code == 200, response.text
            value["state"]["authority_lost"] = True
        else:
            response = await async_client.post(f"/api/ai/runs/{value['identifier']}/cancel", headers=value["headers"][0])
            assert response.status_code == 200, response.text
            assert response.json()["data"]["receipt_pending"] is True
            pending_result = await async_client.get(BASE + f"/tasks/{value['identifier']}/parts/result", headers=value["headers"][3])
            assert pending_result.status_code == 200 and pending_result.content == b"null"
            assert pending_result.headers["X-AI-Parts-Wire"] == "canonical_json_body_no_envelope"
    finally:
        release.set()
        await first
    assert len(calls) == 1 and receipt(value).status == ("failed" if action == "withdraw" else "cancelled")
    assert receipt(value).usage.model_dump() == usage(11, None, True)
    with value["factory"]() as db:
        assert db.query(AIOperationsRunResult.run_id).filter_by(run_id=value["identifier"]).first() is None
    if action == "withdraw":
        for part in ("task", "source", "binding", "result"):
            response = await async_client.get(BASE + f"/tasks/{value['identifier']}/parts/{part}", headers=value["headers"][0])
            assert response.status_code == 403
        response = await async_client.get(f"/api/ai/runs/{value['identifier']}", headers=value["headers"][0])
        assert response.status_code == 200 and response.json()["data"]["parts_state"] == "current_parts_unavailable"
        response = await async_client.get(f"/api/ai/runs?feature_key=operations_support&operations_case_id={value['case_id']}", headers=value["headers"][3])
        assert response.status_code == 200 and response.json()["data"] == []
        assert value["reads"] == []
        # Other earlier cases in this module remain legitimately readable; a
        # mixed directory may authorize their complete Sources independently.
        response = await async_client.get("/api/ai/runs", headers=value["headers"][0])
        assert response.status_code == 200 and not any(row["run_id"] == value["identifier"] for row in response.json()["data"])



@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["source", "audit", "feedback"])
async def test_real_feedback_sql_trigger_rolls_back_feedback_and_specific_audit(configured, pipeline, async_client, fault):
    value = pipeline
    await create(async_client, configured, value)
    transport, calls = provider_service(value)
    await shared.execute_claimed(value["identifier"], value["lease"], transport=transport)
    with value["factory"]() as db:
        before = db.query(AIFeedback).count(), db.query(AIAuditEvent).count()
        if fault == "source":
            body = "UPDATE hoimsystem_ai_operations_original SET raw_text_sha256='" + "0" * 64 + "' WHERE original_id='" + value["original_id"] + "';"
        elif fault == "audit":
            body = "UPDATE hoimsystem_ai_audit_event SET action='broken' WHERE event_id=NEW.event_id;"
        else:
            body = "UPDATE hoimsystem_ai_feedback SET comment='rewritten' WHERE feedback_id=(SELECT feedback_id FROM hoimsystem_ai_feedback WHERE run_id=NEW.target ORDER BY rowid DESC LIMIT 1);"
        db.execute(text("CREATE TRIGGER operations_feedback_tamper AFTER INSERT ON hoimsystem_ai_audit_event WHEN NEW.action='operations.task.feedback' BEGIN " + body + " END"))
        db.commit()
    try:
        response = await async_client.post(f"/api/ai/runs/{value['identifier']}/feedback", headers=value["headers"][3], json=dict(outcome="accepted", comment="独立人工核对"))
        assert response.status_code in {403, 409}, response.text
        with value["factory"]() as db:
            assert (db.query(AIFeedback).count(), db.query(AIAuditEvent).count()) == before
    finally:
        with value["factory"]() as db:
            db.execute(text("DROP TRIGGER operations_feedback_tamper"))
            db.commit()


@pytest.mark.asyncio
async def test_main_route_registration_and_foreign_scope_rejects_before_task_write(configured, pipeline, async_client):
    from app.main import app

    routes = [row for row in app.routes if isinstance(row, APIRoute) and row.endpoint.__module__ == "app.routers.ai_operations_support_tasks"]
    assert len(routes) == 7
    value = pipeline
    body = selection(configured)
    configured[0][0].close()
    with value["factory"]() as db:
        before = db.query(AIRun).count()
    for changes in [dict(patient_id=1), dict(encounter_ref="1"), dict(preview=1), dict(feature_key="patient_summary")]:
        response = await async_client.post("/api/ai/runs", headers=value["headers"][3], json={"feature_key": "operations_support", "input": body, **changes})
        assert response.status_code == 422, response.text
    for suffix in ["&patient_id=1", "&encounter_ref=1", "&document_original_id=" + value["original_id"], "&charge_native_only=true", "&limit=51"]:
        response = await async_client.get("/api/ai/runs?feature_key=operations_support" + suffix, headers=value["headers"][3])
        assert response.status_code == 422, response.text
    response = await async_client.get(BASE + "/tasks?patient_id=1", headers=value["headers"][3])
    assert response.status_code == 422
    with value["factory"]() as db:
        assert db.query(AIRun).count() == before


@pytest.mark.asyncio
async def test_actual_super_management_directory_descriptor_native_trace_and_queued_stop_are_bodyless(configured, pipeline, async_client):
    value = pipeline
    body = selection(configured)
    configured[0][0].commit()
    configured[0][0].close()
    response = await async_client.post(BASE + "/tasks", headers=value["headers"][3], json=body)
    assert response.status_code == 200, response.text
    identifier = response.json()["data"]["run_id"]
    response = await async_client.get(BASE + f"/tasks/{identifier}/trace", headers=value["headers"][0])
    assert response.status_code == 200 and set(response.json()["data"]["parts"]) == {"task", "source", "binding", "result"}
    response = await async_client.get(BASE + f"/tasks/{identifier}", headers=value["headers"][3])
    assert response.status_code == 200 and response.json()["data"]["binding"]["operations_case_id"] == value["case_id"]
    value["state"]["authority_lost"] = True  # Observe body columns even though this Source is current.
    for path in ["/api/ai/admin/runs?feature_key=operations_support", BASE + f"/tasks?case_id={value['case_id']}"]:
        response = await async_client.get(path, headers=value["headers"][0])
        assert response.status_code == 200, response.text
        assert response.json()["data"]
    response = await async_client.get(BASE + "/task-descriptor", headers=value["headers"][3])
    assert response.status_code == 200 and len(response.json()["data"]["objectives"]) == 3
    assert value["reads"] == []
    response = await async_client.post(BASE + f"/tasks/{identifier}/cancel", headers=value["headers"][3])
    assert response.status_code == 403
    response = await async_client.post(BASE + f"/tasks/{identifier}/cancel", headers=value["headers"][0])
    assert response.status_code == 200, response.text
    assert response.json()["data"]["receipt_pending"] is False
    with value["factory"]() as db:
        actual = attempts.technical_header(db, identifier)
        paid = receipts.read_receipt(db, actual)
        assert actual.claim is None and actual.header["start_time"] is None and actual.header["lease_token"] is None
        assert paid.usage.model_dump() == usage(0, 0, False)
    assert value["reads"] == []


@pytest.mark.asyncio
async def test_actual_super_prompt_version_preview_and_revalidation_bind_database_uuid(configured, pipeline, async_client, monkeypatch, tmp_path):
    from app.ai.operations_support_task_prompt import SYSTEM_PROMPT, TASK_PROMPT

    value = pipeline
    chosen = selection(configured)
    packets = []

    class CapturingClient:
        def __init__(self, client):
            self.client = client

        async def record(self, method, path, **kwargs):
            response = await self.client.request(method, path, **kwargs)
            packets.append(dict(method=method, path=path, status=response.status_code, body=response.text, request_body=kwargs.get("json"), actor_role="super_admin" if kwargs.get("headers") == value["headers"][0] else "admin", parts_wire=response.headers.get("X-AI-Parts-Wire")))
            return response

        async def get(self, path, **kwargs):
            return await self.record("GET", path, **kwargs)

        async def post(self, path, **kwargs):
            return await self.record("POST", path, **kwargs)

        async def put(self, path, **kwargs):
            return await self.record("PUT", path, **kwargs)

    async_client = CapturingClient(async_client)
    original_id = configured[1]["original_id"]
    release_id = configured[2]["release_id"]
    configured[0][0].commit()
    configured[0][0].close()
    for path, who in [
        ("/api/ai/admin/features", 0),
        (BASE + "/task-descriptor", 3),
        (BASE + "/originals", 0),
        (BASE + f"/originals/{original_id}", 0),
        (BASE + f"/originals/{original_id}/body", 0),
        (BASE + "/releases", 0),
        (BASE + f"/releases/{release_id}", 0),
        (BASE + f"/releases/{release_id}/draft", 0),
        (BASE + f"/releases/{release_id}/source", 3),
        (BASE + "/cases", 3),
        (BASE + f"/cases/{value['case_id']}", 3),
        (BASE + f"/cases/{value['case_id']}/parts/source", 3),
        (BASE + f"/cases/{value['case_id']}/parts/private", 0),
    ]:
        response = await async_client.get(path, headers=value["headers"][who])
        assert response.status_code == 200, response.text
    response = await async_client.get("/api/ai/admin/prompts/operations_support", headers=value["headers"][0])
    assert response.status_code == 200
    assert response.json()["data"]["system_prompt"] == SYSTEM_PROMPT
    assert response.json()["data"]["versions"][-1]["task_prompt"] == TASK_PROMPT
    custom = "明确当前独立受审资料，不扩大范围，保留实际逐字引用与所有未知项。\r\n😀  不推定实时兼容或执行权限。"
    response = await async_client.post("/api/ai/admin/prompts/operations_support", headers=value["headers"][0], json=dict(expected_revision=1, task_prompt=custom, change_note="仅合成资料验证范围", activate=True))
    assert response.status_code == 200, response.text
    prompt_id = response.json()["data"]["prompt_id"]
    assert registry.identifier(prompt_id) == prompt_id
    response = await async_client.post(BASE + "/tasks", headers=value["headers"][3], json=chosen)
    assert response.status_code == 409
    response = await async_client.put("/api/ai/admin/features/operations_support", headers=value["headers"][0], json=dict(expected_revision=2, enabled=True))
    assert response.status_code == 422 and "验证" in response.text
    response = await async_client.post(BASE + "/tasks", headers=value["headers"][0], json={**chosen, "preview": True})
    assert response.status_code == 200, response.text
    identifier = response.json()["data"]["run_id"]
    response = await async_client.get(BASE + f"/tasks/{identifier}/parts/binding", headers=value["headers"][0])
    assert response.status_code == 200, response.text
    assert response.json()["prompt_id"] == prompt_id and response.json()["prompt_version"] == 1
    response = await async_client.get(BASE + f"/tasks/{identifier}/parts/task", headers=value["headers"][0])
    snapshot = json.loads(response.json()["prompt_snapshot_json"])
    assert snapshot["prompt_id"] == prompt_id and snapshot["task_prompt"] == custom and snapshot["system_prompt"] == SYSTEM_PROMPT
    response = await async_client.post(BASE + f"/tasks/{identifier}/cancel", headers=value["headers"][0])
    assert response.status_code == 200
    response = await async_client.put("/api/ai/admin/features/operations_support", headers=value["headers"][0], json=dict(expected_revision=2, enabled=True, validation_status="validated", validation_note="只验证当前合成审核资料三种任务目标，不代表环境兼容性验证"))
    assert response.status_code == 200 and response.json()["data"]["enabled"] is True
    assert response.json()["data"]["input_mode"] == "operations_support_evidence"
    response = await async_client.post(BASE + "/tasks", headers=value["headers"][3], json=chosen)
    assert response.status_code == 200, response.text
    value["identifier"] = response.json()["data"]["run_id"]
    response = await async_client.get(BASE + f"/tasks/{value['identifier']}", headers=value["headers"][3])
    assert response.status_code == 200 and response.json()["data"]["status"] == "queued"
    with value["factory"]() as db:
        claimed = shared.claim_next_run(db)
    assert claimed[0] == value["identifier"]
    value["lease"] = claimed[1]
    response = await async_client.get(BASE + f"/tasks/{value['identifier']}", headers=value["headers"][3])
    assert response.status_code == 200 and response.json()["data"]["status"] == "running"
    monkeypatch.setattr("tests.test_ai_operations_support_execution.TASK_PROMPT", custom)
    transport, calls = provider_service(value)
    await shared.execute_claimed(value["identifier"], value["lease"], transport=transport)
    assert len(calls) == 1 and receipt(value).status == "succeeded"
    for part in ("task", "source", "binding", "result"):
        path = BASE + f"/tasks/{value['identifier']}/parts/{part}"
        response = await async_client.get(path, headers=value["headers"][3])
        assert response.status_code == 200, response.text
    for path, who in [
        (BASE + f"/tasks/{value['identifier']}", 3),
        (BASE + f"/tasks/{value['identifier']}/trace", 0),
        (BASE + f"/tasks?case_id={value['case_id']}", 3),
        (BASE + f"/tasks?case_id={value['case_id']}", 0),
        (f"/api/ai/runs?feature_key=operations_support&operations_case_id={value['case_id']}", 3),
        ("/api/ai/admin/runs?feature_key=operations_support", 0),
    ]:
        response = await async_client.get(path, headers=value["headers"][who])
        assert response.status_code == 200, response.text
    (tmp_path / "actual-main-custom-prompt-task-packets.json").write_text(json.dumps(packets, ensure_ascii=False, indent=2))
