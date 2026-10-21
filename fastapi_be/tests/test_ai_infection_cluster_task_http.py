"""Actual Main JWT/ASGI→durable queue→local worker→split current reads."""

# ruff: noqa: F811 -- imported actual Source/Task fixtures are intentionally registered.

import json

import pytest
from sqlalchemy import event

from app import database
from app.ai import infection_cluster_contract as c
from app.ai import infection_cluster_registry as registry
from app.ai import runtime
from app.ai.infection_cluster_run_models import AIInfectionRunArtifact as Artifact
from app.ai.models import AIRun
from app.main import app
from app.routers.ai_infection_cluster_tasks import router
from tests.test_ai_infection_cluster_sources import cas
from tests.test_ai_infection_cluster_task_storage import profile_case, stage, task_case, task_text_queries  # noqa: F401

ROOT = "/api/ai/infection-cluster"


@pytest.mark.asyncio
async def test_actual_main_full_local_queue_shared_claim_worker_split_trace_and_withdrawal_even_super(async_client, task_case, auth_headers, monkeypatch, tmp_path):
    case, db = task_case, task_case["db"]
    own, sup = auth_headers(case["author"].username), auth_headers(case["reviewer"].username)
    packets = []

    async def send(path, *, method="GET", body=None, headers=own, status=200):
        response = await async_client.request(method, path, headers=headers, json=body)
        packets.append(
            dict(
                path=path, method=method, request=body, status=response.status_code, raw_utf8=response.text, bytes=len(response.content), sha256=c.text_digest(response.text), response=response.json()
            )
        )
        assert response.status_code == status, response.text
        return response.json().get("data")

    context = await send(ROOT + "/context", method="POST", body=case["task_request"])
    assert context["external_model_transfer"] is False and context["automatic_actions"] is False
    queued = await send("/api/ai/runs", method="POST", body=dict(feature_key="infection_cluster", input={"infection_cluster_scenario_id": case["scenario"].scenario_id}, preview=False))
    assert set(queued) == {"run_id", "feature_key", "status", "result_available"} and queued["status"] == "queued"
    rid = queued["run_id"]
    meta = await send(ROOT + f"/tasks/{rid}")
    assert meta["status"] == "queued" and meta["usage"] is None and meta["clinical_body_included"] is False
    task = await send(ROOT + f"/tasks/{rid}/parts/task")
    source = await send(ROOT + f"/tasks/{rid}/parts/source")
    assert task["value"]["external_model_transfer"] is False and source["value_hash"] == context["source_hash"]
    db.rollback()
    claim = runtime.claim_next_run(db)
    assert claim is not None and claim[0] == rid
    # Use the same real database and dedicated native dispatcher. No HTTP/model
    # stub substitutes the arithmetic, Source, permissions or SQL acceptance.
    monkeypatch.setattr(database, "SessionLocal", lambda: db.__class__(bind=db.get_bind(), expire_on_commit=False, autoflush=False))
    db.rollback()
    await runtime.execute_claimed(*claim)
    full = await send(ROOT + f"/tasks/{rid}")
    assert full["status"] == "succeeded" and full["usage"]["input_tokens"] == full["usage"]["output_tokens"] == 0
    assert full["usage"]["calculation_completed"] is True
    result = await send(ROOT + f"/tasks/{rid}/parts/result")
    assert result["value"]["family_size"] == 2 and result["value"]["denominator"] == "not_provided"
    assert result["value"]["automatic_actions"] is False
    trace = await send(f"/api/ai/admin/runs/{rid}", headers=sup)
    assert trace["schema_version"] == "infection_local_split_trace_v1" and trace["clinical_body_included"] is False
    assert set(trace["parts"]) == {"task", "source", "result"}
    await send("/api/ai/runs?feature_key=infection_cluster")
    await send("/api/ai/admin/runs?feature_key=infection_cluster", headers=sup)
    for grant in case["grants"]:
        registry.revoke_record(db, case["reviewer"], "grant", grant.record_id, cas(grant))
        db.commit()
    queries = []

    def capture(conn, cursor, sql, params, ctx, many):
        queries.append(sql)

    event.listen(db.get_bind(), "before_cursor_execute", capture)
    try:
        for headers in [own, sup]:
            safe = await send(f"/api/ai/runs/{rid}", headers=headers)
            assert safe["protected_hashes_are_opaque"] and not safe["clinical_body_included"]
            assert safe["usage"]["model_call_attempted"] is False
            for part in ["task", "source", "result"]:
                await send(ROOT + f"/tasks/{rid}/parts/{part}", headers=headers, status=403)
        withdrawn_trace = await send(f"/api/ai/admin/runs/{rid}", headers=sup)
        assert withdrawn_trace["current_patient_purpose_required_even_for_super"]
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", capture)
    assert task_text_queries(queries) == []
    assert all("mapping_key" not in packet["raw_utf8"] for packet in packets)
    (tmp_path / "actual-infection-local-task-main-http.json").write_text(
        json.dumps(
            dict(
                scope="Actual Main JWT/ASGI; real synthetic SQLite Source→reviewed local configuration→shared queue/claim/dedicated local worker; no external model, hospital or actual clinical validation",
                packets=packets,
            ),
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad",
    [
        dict(patient_id=1),
        dict(encounter_ref="admission:1"),
        dict(preview=1),
        dict(input={}),
        dict(input={"infection_cluster_scenario_id": None}),
        dict(input={"infection_cluster_scenario_id": "00000000-0000-0000-0000-000000000001", "alpha_decimal": "0.01"}),
    ],
)
async def test_actual_main_generic_request_cannot_inject_patient_scope_override_or_bool_coercion(async_client, task_case, auth_headers, bad):
    body = dict(feature_key="infection_cluster", input={"infection_cluster_scenario_id": task_case["scenario"].scenario_id}, preview=False)
    body.update(bad)
    response = await async_client.post("/api/ai/runs", headers=auth_headers(task_case["author"].username), json=body)
    assert response.status_code == 422, response.text
    assert task_case["db"].query(Artifact).count() == 0


@pytest.mark.asyncio
async def test_actual_main_queued_cancel_after_processing_withdrawal_never_needs_body_and_does_not_generic_stop(async_client, task_case, auth_headers):
    case, db = task_case, task_case["db"]
    rid = stage(case)
    grant = case["grants"][0]
    registry.revoke_record(db, case["reviewer"], "grant", grant.record_id, cas(grant))
    db.commit()
    queries = []

    def capture(conn, cursor, sql, params, ctx, many):
        queries.append(sql)

    event.listen(db.get_bind(), "before_cursor_execute", capture)
    try:
        cancelled = await async_client.post(f"/api/ai/runs/{rid}/cancel", headers=auth_headers(case["author"].username))
        safe = await async_client.get(ROOT + f"/tasks/{rid}", headers=auth_headers(case["author"].username))
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", capture)
    assert cancelled.status_code == safe.status_code == 200
    usage = safe.json()["data"]["usage"]
    assert usage["calculation_attempted"] is usage["calculation_completed"] is False
    assert task_text_queries(queries) == [] and db.get(AIRun, rid).status == "cancelled"


def test_main_explicit_jsonresponse_and_six_new_mounted_routes():
    assert router.default_response_class.__name__ == "JSONResponse" and len(router.routes) == 6
    assert all(any(actual.path == "/api" + route.path for actual in app.routes) for route in router.routes)
