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
