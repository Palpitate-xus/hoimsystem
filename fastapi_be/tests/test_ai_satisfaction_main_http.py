"""Actual mounted JWT/native worker pipeline with isolated model HTTP replies."""

import asyncio
import copy
import hashlib
import json

import httpx
import pytest
from sqlalchemy import event, text

from app.ai.models import AIRun
from app.ai.runtime import claim_next_run, execute_claimed
from app.ai.satisfaction_artifact_models import AISatisfactionRunArtifact
from app.ai.satisfaction_execution import cancel_satisfaction_run
from app.ai.satisfaction_prompt import SATISFACTION_SYSTEM_PROMPT
from tests.test_ai_satisfaction_gateway import envelope
from tests.test_ai_satisfaction_runtime import runtime_case as _runtime_case
from tests.test_ai_satisfaction_sources import satisfaction_case as _satisfaction_case

runtime_case, satisfaction_case = _runtime_case, _satisfaction_case


@pytest.fixture
def shared_case(runtime_case):
    case, db = runtime_case, runtime_case["db"]
    # The existing helper creates a sample running anchor for storage tests.
    # Discard only that helper task so the test below creates its own real Run
    # through JWT/HTTP and claims it through the actual shared worker.
    sample = case["run"]
    db.delete(db.get(AISatisfactionRunArtifact, sample.run_id))
    db.delete(sample)
    db.commit()
    case["actor_name"] = case["admin_user"].username
    case["actor_id"] = case["admin_user"].user_id
    case["super_name"] = case["super_admin_user"].username
    case["private_comment"] = case["review"].comment
    case["private_identity"] = case["patient"].identity
    case["req"] = copy.deepcopy(case["req"])
    case["req"]["input"]["question"] = "\ufeff请核对\r\n🧪e\u0301 2026-10-21T12:30:00.123456Z"
    db.rollback()
    yield case
    db.rollback()
    # Keep later tests' shared queue deterministic using the real cancellation
    # function, without manufacturing a terminal status or a usage receipt.
    identifiers = (
        db.query(AIRun.run_id)
        .join(AISatisfactionRunArtifact, AIRun.run_id == AISatisfactionRunArtifact.run_id)
        .filter(AISatisfactionRunArtifact.case_id == case["made"]["case_id"], AIRun.status.in_(["queued", "running"]))
        .all()
    )
    for (identifier,) in identifiers:
        cancel_satisfaction_run(db, case["super_admin_user"], identifier)
    db.rollback()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["chat", "responses"])
async def test_actual_main_source_context_create_native_claim_worker_full_result_trace_feedback_and_fk_history(async_client, shared_case, auth_headers, kind):
    case, db = shared_case, shared_case["db"]
    case["provider"].kind = kind
    db.commit()
    headers, super_headers = auth_headers(case["actor_name"]), auth_headers(case["super_name"])
    case_id = case["made"]["case_id"]
    source = case["made"]["public_source"]
    source_detail = await async_client.get(f"/api/ai/satisfaction-sources/cases/{case_id}", headers=headers)
    assert source_detail.status_code == 200, source_detail.text
    assert source_detail.json()["data"]["public_source"] == source
    features = await async_client.get("/api/ai/features", headers=headers)
    assert features.status_code == 200, features.text
    assert next(value for value in features.json()["data"] if value["key"] == "feedback_analysis")["input_mode"] == "satisfaction_evidence"
    preview = await async_client.post("/api/ai/operational-context", headers=headers, json={"feature_key": "feedback_analysis", "input": case["req"]["input"]})
    assert preview.status_code == 200, preview.text
    assert preview.json()["data"]["context"]["satisfaction_source"] == source
    assert preview.json()["data"]["context"]["satisfaction_case"]["snapshot"] is None
    created = await async_client.post("/api/ai/runs", headers=headers, json=case["req"])
    assert created.status_code == 200, created.text
    short = created.json()["data"]
    assert short["status"] == "queued" and short["usage"] == {"input_tokens": None, "output_tokens": None, "complete": False, "model_call_attempted": None}
    assert short["patient_id"] is short["encounter_ref"] is None
    assert "result" not in short and "satisfaction_findings" not in short and "legacy_feedback_read_only" not in short
    identifier = short["run_id"]
    db.rollback()
    claimed = claim_next_run(db)
    assert claimed is not None and claimed[0] == identifier
    db.rollback()
    calls, checkouts = [], []

    def checkout(*_):
        checkouts.append(1)

    def checkin(*_):
        checkouts.pop()

    def handle(request):
        calls.append(request)
        assert not checkouts
        sent = json.loads(request.content)
        assert sent["store"] is False
        instructions = sent["messages"][0]["content"] if kind == "chat" else sent["instructions"]
        assert instructions.startswith(SATISFACTION_SYSTEM_PROMPT + "\n\n")
        visible = json.loads(sent["messages"][1]["content"] if kind == "chat" else sent["input"])
        assert visible == {"satisfaction_source": source, "question": case["req"]["input"]["question"]}
        assert case["private_comment"] not in request.content.decode() and case["private_identity"] not in request.content.decode()
        return httpx.Response(200, json=envelope(kind, case["result"]["satisfaction_analysis"]))

    engine = db.get_bind()
    event.listen(engine, "checkout", checkout)
    event.listen(engine, "checkin", checkin)
    try:
        await execute_claimed(*claimed, transport=httpx.MockTransport(handle))
        assert not checkouts
    finally:
        event.remove(engine, "checkout", checkout)
        event.remove(engine, "checkin", checkin)
    assert len(calls) == 1
    full = await async_client.get(f"/api/ai/runs/{identifier}", headers=headers)
    assert full.status_code == 200, full.text
    value = full.json()["data"]
    assert value["status"] == "succeeded" and value["result"] == case["result"]
    assert value["satisfaction_findings"]["satisfaction_source"] == source
    assert value["usage"] == {"input_tokens": 13, "output_tokens": 7, "complete": True, "model_call_attempted": True}
    assert "legacy_feedback_read_only" not in value
    trace = await async_client.get(f"/api/ai/admin/runs/{identifier}", headers=super_headers)
    assert trace.status_code == 200, trace.text
    traced = trace.json()["data"]
    assert traced["frozen_satisfaction_audit"] is True
    assert traced["frozen_request"]["payload"]["context"]["satisfaction_source"] == source
    raw, artifact = traced["raw_frozen_json"], traced["satisfaction_artifact"]
    for original, anchor in (("input_json", "input_hash"), ("evidence_json", "evidence_hash"), ("context_metadata_json", "metadata_hash")):
        assert hashlib.sha256(raw[original].encode()).hexdigest() == artifact[anchor]
    assert json.loads(raw["input_json"])["payload"]["input"] == case["req"]["input"]
    assert "satisfaction_source" not in json.loads(raw["input_json"])["payload"]["context"]
    assert artifact["receipt_event_id"] != artifact["usage_event_id"]
    assert artifact["receipt_event_id"] > 0 and artifact["usage_event_id"] > 0
    assert case["private_comment"] not in trace.text and case["private_identity"] not in trace.text
    feedback = await async_client.post(f"/api/ai/runs/{identifier}/feedback", headers=headers, json={"outcome": "rejected", "comment": "合成逐字复核，主题含义仍待人工核实。"})
    assert feedback.status_code == 200, feedback.text
    trace = await async_client.get(f"/api/ai/admin/runs/{identifier}", headers=super_headers)
    assert trace.status_code == 200 and trace.json()["data"]["feedback"][0]["outcome"] == "rejected"
    params = {"feature_key": "feedback_analysis", "satisfaction_case_id": case_id, "satisfaction_native_only": True}
    own = await async_client.get("/api/ai/runs", headers=headers, params=params)
    global_history = await async_client.get("/api/ai/admin/runs", headers=super_headers, params=params)
    assert own.status_code == global_history.status_code == 200, (own.text, global_history.text)
    assert [value["run_id"] for value in own.json()["data"]] == [identifier]
    assert [value["run_id"] for value in global_history.json()["data"]] == [identifier]
    assert global_history.json()["total"] == 1


@pytest.mark.asyncio
async def test_actual_main_queued_cancellation_has_specific_known_zero_receipt_and_no_result(async_client, shared_case, auth_headers):
    case = shared_case
    headers = auth_headers(case["actor_name"])
    created = await async_client.post("/api/ai/runs", headers=headers, json=case["req"])
    assert created.status_code == 200, created.text
    identifier = created.json()["data"]["run_id"]
    cancelled = await async_client.post(f"/api/ai/runs/{identifier}/cancel", headers=headers)
    assert cancelled.status_code == 200, cancelled.text
    detail = await async_client.get(f"/api/ai/runs/{identifier}", headers=headers)
    assert detail.status_code == 200, detail.text
    value = detail.json()["data"]
    assert value["status"] == "cancelled" and value["result"] == {}
    assert value["usage"] == {"input_tokens": 0, "output_tokens": 0, "complete": True, "model_call_attempted": False}
    case["db"].rollback()
    assert claim_next_run(case["db"]) is None
    assert (await async_client.post(f"/api/ai/runs/{identifier}/feedback", headers=headers, json={"outcome": "accepted", "comment": ""})).status_code == 409


@pytest.mark.asyncio
async def test_actual_main_withdrawn_source_refuses_before_selecting_private_task_text(async_client, shared_case, auth_headers):
    case, db = shared_case, shared_case["db"]
    headers, super_headers = auth_headers(case["actor_name"]), auth_headers(case["super_name"])
    created = await async_client.post("/api/ai/runs", headers=headers, json=case["req"])
    assert created.status_code == 200, created.text
    identifier = created.json()["data"]["run_id"]
    revoked = await async_client.post(
        f"/api/ai/satisfaction-sources/cases/{case['made']['case_id']}/revoke",
        headers=super_headers,
        json={"expected_revision": 2, "basis_note": "合成测试：先撤销来源，再确认任务私有正文没有提前读取。"},
    )
    assert revoked.status_code == 200, revoked.text
    statements = []

    def capture(_connection, _cursor, statement, _parameters, _context, _many):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    engine = db.get_bind()
    event.listen(engine, "before_cursor_execute", capture)
    try:
        refused = await async_client.get(f"/api/ai/runs/{identifier}", headers=headers)
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert refused.status_code == 409, refused.text
    assert statements
    private_reads = [
        statement for statement in statements if any(f"hoimsystem_ai_run.{column}" in statement.split("\nFROM", 1)[0] for column in ("input_json", "evidence_json", "context_metadata_json"))
    ]
    assert private_reads == [], private_reads


@pytest.mark.asyncio
async def test_current_super_frozen_history_ignores_malformed_live_roles_while_ordinary_history_refuses(async_client, shared_case, auth_headers):
    case, db = shared_case, shared_case["db"]
    headers, super_headers = auth_headers(case["actor_name"]), auth_headers(case["super_name"])
    created = await async_client.post("/api/ai/runs", headers=headers, json=case["req"])
    assert created.status_code == 200, created.text
    identifier = created.json()["data"]["run_id"]
    db.execute(text("UPDATE hoimsystem_ai_feature_config SET allowed_roles_json='malformed live JSON' WHERE feature_key='feedback_analysis'"))
    db.commit()
    params = {"feature_key": "feedback_analysis", "satisfaction_case_id": case["made"]["case_id"], "satisfaction_native_only": True}
    ordinary = await async_client.get("/api/ai/runs", headers=headers, params=params)
    assert ordinary.status_code == 409, ordinary.text
    frozen = await async_client.get("/api/ai/runs", headers=super_headers, params=params)
    assert frozen.status_code == 200, frozen.text
    assert [row["run_id"] for row in frozen.json()["data"]] == [identifier]
    trace = await async_client.get(f"/api/ai/admin/runs/{identifier}", headers=super_headers)
    assert trace.status_code == 200 and trace.json()["data"]["frozen_satisfaction_audit"] is True, trace.text


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["cancel", "source", "role", "source_then_super_cancel"])
async def test_actual_main_inflight_changes_preserve_paid_usage_without_accepting_a_result(async_client, shared_case, auth_headers, change):
    case, db = shared_case, shared_case["db"]
    headers, super_headers = auth_headers(case["actor_name"]), auth_headers(case["super_name"])
    made = await async_client.post("/api/ai/runs", headers=headers, json=case["req"])
    assert made.status_code == 200, made.text
    identifier = made.json()["data"]["run_id"]
    db.rollback()
    claimed = claim_next_run(db)
    assert claimed is not None and claimed[0] == identifier
    db.rollback()
    entered, release = asyncio.Event(), asyncio.Event()
    calls, checkouts = [], []

    def checkout(*_):
        checkouts.append(1)

    def checkin(*_):
        checkouts.pop()

    async def handle(request):
        assert not checkouts
        calls.append(request)
        entered.set()
        await release.wait()
        assert not checkouts
        return httpx.Response(200, json=envelope("chat", case["result"]["satisfaction_analysis"]))

    engine = db.get_bind()
    event.listen(engine, "checkout", checkout)
    event.listen(engine, "checkin", checkin)
    worker = asyncio.create_task(execute_claimed(*claimed, transport=httpx.MockTransport(handle)))
    try:
        await asyncio.wait_for(entered.wait(), timeout=10)
        running = await async_client.get(f"/api/ai/runs/{identifier}", headers=headers)
        assert running.status_code == 200, running.text
        assert running.json()["data"]["status"] == "running"
        assert running.json()["data"]["usage"] == {"input_tokens": None, "output_tokens": None, "complete": False, "model_call_attempted": None}
        if change in {"source", "source_then_super_cancel"}:
            revoked = await async_client.post(
                f"/api/ai/satisfaction-sources/cases/{case['made']['case_id']}/revoke",
                headers=super_headers,
                json={"expected_revision": 2, "basis_note": "合成测试：请求进行中撤销来源，原付费用量仍须记录。"},
            )
            assert revoked.status_code == 200, revoked.text
        if change == "role":
            db.execute(text("UPDATE hoimsystem_users SET user_role='patient' WHERE user_id=:id"), {"id": case["actor_id"]})
            db.commit()
        if change in {"cancel", "source_then_super_cancel"}:
            stopped = await async_client.post(f"/api/ai/runs/{identifier}/cancel", headers=super_headers if change == "source_then_super_cancel" else headers)
            assert stopped.status_code == 200, stopped.text
            pending = await async_client.get(f"/api/ai/runs/{identifier}", headers=super_headers)
            assert pending.status_code == 200, pending.text
            assert pending.json()["data"]["status"] == "cancelled" and pending.json()["data"]["result"] == {}
            assert pending.json()["data"]["usage"] == {"input_tokens": None, "output_tokens": None, "complete": False, "model_call_attempted": None}
        assert not checkouts
        release.set()
        await worker
        assert len(calls) == 1 and not checkouts
        full = await async_client.get(f"/api/ai/runs/{identifier}", headers=super_headers)
        assert full.status_code == 200, full.text
        value = full.json()["data"]
        assert value["status"] == ("cancelled" if change in {"cancel", "source_then_super_cancel"} else "failed")
        assert value["result"] == {} and value["usage"] == {"input_tokens": 13, "output_tokens": 7, "complete": True, "model_call_attempted": True}
        ordinary = await async_client.get(f"/api/ai/runs/{identifier}", headers=headers)
        assert ordinary.status_code == (200 if change == "cancel" else 403 if change == "role" else 409), ordinary.text
        trace = await async_client.get(f"/api/ai/admin/runs/{identifier}", headers=super_headers)
        assert trace.status_code == 200, trace.text
        artifact = trace.json()["data"]["satisfaction_artifact"]
        assert artifact["usage_event_id"] > 0
        assert all(artifact[key] is None for key in ("result_hash", "result_bytes", "receipt_event_id", "accepted_lease", "accepted_at"))
        assert (await async_client.post(f"/api/ai/runs/{identifier}/feedback", headers=super_headers, json={"outcome": "accepted", "comment": ""})).status_code == 409
    finally:
        release.set()
        await worker
        event.remove(engine, "checkout", checkout)
        event.remove(engine, "checkin", checkin)
        if change == "role":
            db.execute(text("UPDATE hoimsystem_users SET user_role='admin' WHERE user_id=:id"), {"id": case["actor_id"]})
            db.commit()
