"""Actual Main JWT with only the dedicated router test-mounted; Mock model."""

import pytest
from sqlalchemy import event

from app.ai import deidentification_runtime as runtime
from app.ai.models import AIRun
from app.ai.research_cohort_registry import review_registry_original
from app.main import app
from app.routers.ai_deidentification_tasks import router
from tests.test_ai_deidentification_runtime import model
from tests.test_ai_deidentification_storage import body_sql
from tests.test_ai_deidentification_storage import task_case as task_case  # noqa: F401
from tests.test_ai_research_cohort_contract import BASIS
from tests.test_ai_research_cohort_sources import research_case as research_case  # noqa: F401


@pytest.fixture(scope="module", autouse=True)
def mount_dedicated_router_for_actual_main_only():
    if not any(route.path == "/api/ai/deidentification/tasks/context" for route in app.routes):
        app.include_router(router, prefix="/api")


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["chat", "responses"])
async def test_main_jwt_complete_source_literal_clocks_queued_then_full_and_authorized_super_trace(task_case, async_client, auth_headers, kind):
    case, db = task_case, task_case["db"]
    case["provider"].kind = kind
    db.commit()
    header = auth_headers(case["actor"].username)
    body = {"input": case["input"]}
    preview = await async_client.post("/api/ai/deidentification/tasks/context", headers=header, json=body)
    assert preview.status_code == 200, preview.text
    assert preview.json()["data"]["source"]["documents"][0]["text"] == case["source"]["public_source"]["documents"][0]["text"]
    assert "2026-10-21T12:00:00.123456Z" in preview.json()["data"]["source"]["documents"][0]["text"]
    response = await async_client.post("/api/ai/deidentification/tasks", headers=header, json=body)
    assert response.status_code == 200, response.text
    ack = response.json()["data"]
    assert ack["status"] == "queued" and ack["detail_required"] and ack["input_tokens"] is None
    assert "source" not in ack and "result" not in ack
    identifier = ack["run_id"]
    claimed = runtime.claim_deidentification_run(db, identifier)
    db.rollback()
    await runtime.execute_deidentification_claimed(*claimed, transport=model(case))
    full = await async_client.get("/api/ai/deidentification/tasks/" + identifier, headers=header)
    assert full.status_code == 200, full.text
    assert full.json()["data"]["result"]["draft"]["candidates"][0]["quote"] == "张三"
    trace = await async_client.get("/api/ai/deidentification/tasks/" + identifier + "/trace", headers=auth_headers(case["users"]["super_admin_user"].username))
    assert trace.status_code == 200, trace.text
    assert set(trace.json()["data"]["raw_frozen_json"]) == {"input_json", "evidence_json", "context_metadata_json"}


@pytest.mark.asyncio
async def test_main_current_patient_authority_denies_every_private_part_but_keeps_technical_receipt(task_case, async_client, auth_headers):
    case, db = task_case, task_case["db"]
    run = runtime.create_deidentification_run(db, case["actor"], case["input"])
    identifier = run.run_id
    runtime.cancel_deidentification_run(db, case["actor"], identifier)
    review_registry_original(db, case["users"]["super_admin_user"], "authorization", case["values"][3]["source_record_id"], {"expected_revision": 2, "basis_note": BASIS}, revoke=True)
    header = auth_headers(case["users"]["super_admin_user"].username)
    statements = []

    def observe(conn, cursor, sql, args, context, many):
        statements.append(sql)

    event.listen(db.bind, "before_cursor_execute", observe)
    try:
        for suffix in ("?audit_only=true", "/source?audit_only=true", "/result?audit_only=true", "/trace"):
            response = await async_client.get("/api/ai/deidentification/tasks/" + identifier + suffix, headers=header)
            assert response.status_code == 403, response.text
        assert body_sql(statements) == []
    finally:
        event.remove(db.bind, "before_cursor_execute", observe)
    safe = await async_client.get("/api/ai/deidentification/tasks/" + identifier + "/technical", headers=header)
    assert safe.status_code == 200, safe.text
    assert safe.json()["data"]["usage_receipt"] == {"input_tokens": 0, "output_tokens": 0, "complete": True, "model_call_attempted": False}
    assert safe.json()["data"]["source"] is safe.json()["data"]["result"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("extra", [{"patient_id": 123}, {"home_id": "foreign"}, {"export_release_id": "foreign"}])
async def test_main_foreign_or_direct_scope_cannot_be_added_to_case_only_task_input(task_case, async_client, auth_headers, extra):
    before = task_case["db"].query(AIRun).count()
    response = await async_client.post("/api/ai/deidentification/tasks", headers=auth_headers(task_case["actor"].username), json={"input": {**task_case["input"], **extra}})
    assert response.status_code == 422 and task_case["db"].query(AIRun).count() == before


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["chat", "responses"])
async def test_main_inflight_cancel_is_pending_unknown_until_the_original_worker_records_actual_paid_usage(task_case, async_client, auth_headers, kind):
    import asyncio

    import httpx

    case, db = task_case, task_case["db"]
    case["provider"].kind = kind
    db.commit()
    headers = auth_headers(case["actor"].username)
    queued = await async_client.post("/api/ai/deidentification/tasks", headers=headers, json={"input": case["input"]})
    assert queued.status_code == 200, queued.text
    identifier = queued.json()["data"]["run_id"]
    claimed = runtime.claim_deidentification_run(db, identifier)
    db.rollback()
    entered, released = asyncio.Event(), asyncio.Event()
    actual_reply = model(case, partial=kind == "responses")

    async def held(request):
        entered.set()
        await released.wait()
        return actual_reply.handle_request(request)

    worker = asyncio.create_task(runtime.execute_deidentification_claimed(*claimed, transport=httpx.MockTransport(held)))
    try:
        await asyncio.wait_for(entered.wait(), 10)
        cancelled = await async_client.post("/api/ai/deidentification/tasks/" + identifier + "/cancel", headers=headers, json={})
        assert cancelled.status_code == 200, cancelled.text
        pending = cancelled.json()["data"]
        assert pending["status"] == "cancelled" and pending["source"] is pending["result"] is pending["raw_frozen_json"] is None
        assert pending["usage_receipt"] == {"input_tokens": None, "output_tokens": None, "complete": False, "model_call_attempted": None}
        detail = await async_client.get("/api/ai/deidentification/tasks/" + identifier, headers=headers)
        assert detail.status_code == 200, detail.text
        assert detail.json()["data"]["result"] is None
        assert detail.json()["data"]["usage_receipt"] == pending["usage_receipt"]
    finally:
        released.set()
        await worker
    paid = await async_client.get("/api/ai/deidentification/tasks/" + identifier, headers=headers)
    assert paid.status_code == 200, paid.text
    value = paid.json()["data"]
    assert value["status"] == "cancelled" and value["result"] is None
    assert value["usage_receipt"] == {"input_tokens": 11, "output_tokens": None if kind == "responses" else 13, "complete": kind == "chat", "model_call_attempted": True}


@pytest.mark.asyncio
async def test_main_completed_cancel_with_removed_specific_receipt_never_degrades_to_pending_unknown(task_case, async_client, auth_headers):
    from app.ai.deidentification_run_models import AIDeidentificationRunResult

    case, db = task_case, task_case["db"]
    run = runtime.create_deidentification_run(db, case["actor"], case["input"])
    identifier = run.run_id
    claimed = runtime.claim_deidentification_run(db, identifier)
    db.rollback()
    await runtime.execute_deidentification_claimed(*claimed, transport=model(case, mutate=lambda: runtime.cancel_deidentification_run(db, case["actor"], identifier)))
    # Actual durable paid terminal state remains; remove only the actual PK link.
    db.expire_all()
    db.get(AIDeidentificationRunResult, identifier).usage_event_id = None
    db.commit()
    response = await async_client.get("/api/ai/deidentification/tasks/" + identifier + "/technical", headers=auth_headers(case["actor"].username))
    assert response.status_code == 409 and "终态实际用量回执缺失" in response.text
