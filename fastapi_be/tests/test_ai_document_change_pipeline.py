"""Actual main/JWT/SQL/durable worker with a synthetic ASGI text provider.

This does not claim hospital data, live model HTTP, MySQL locking, or clinical
semantic correctness. Full output is retained across separate bounded packets.
"""

import pytest
from sqlalchemy import event, text

from app.ai import document_change_contract as c
from app.ai import document_change_sources as sources
from app.ai import document_change_storage as storage
from app.ai import runtime
from app.ai.document_change_run_models import AIDocumentChangeRunArtifact, AIDocumentChangeRunResult
from app.ai.models import AIFeedback, AIRun
from app.ai.schemas import RunRequest
from tests.test_ai_document_change_runtime import model_transport, mutate_current, request
from tests.test_ai_document_change_runtime import pipeline as pipeline  # noqa: F401
from tests.test_ai_document_change_sources import change_case as change_case  # noqa: F401
from tests.test_ai_document_change_storage import remove_prior_tasks as remove_prior_tasks  # noqa: F401
from tests.test_ai_document_change_task_access import no_task_text
from tests.test_ai_document_evidence_contract import NOTE
from tests.test_ai_document_evidence_sources import cas


def body(case, **values):
    return vars(request(case, **values))


def headers(auth_headers, case):
    return auth_headers(case["actor"].username)


async def create(client, auth, case):
    result = await client.post("/api/ai/runs", headers=auth, json=body(case))
    assert result.status_code == 200, result.text
    assert result.json()["data"]["status"] == "queued"
    assert "document_change_findings" not in result.json()["data"]
    return result.json()


async def execute(case):
    claim = runtime.claim_next_run(case["db"])
    assert claim is not None
    transport, packets, close = model_transport(case)
    try:
        await runtime.execute_claimed(*claim, transport=transport)
    finally:
        close()
    return claim, packets


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["chat", "responses"])
async def test_main_jwt_preview_queue_shared_worker_split_result_frozen_trace_feedback_history(async_client, auth_headers, pipeline, kind, tmp_path):
    case, db = pipeline, pipeline["db"]
    case["provider"].kind = kind
    db.commit()
    auth = headers(auth_headers, case)
    preview = await async_client.post("/api/ai/document-change/context", headers=auth, json=body(case)["input"])
    assert preview.status_code == 200, preview.text
    assert preview.json()["data"]["context"]["scope"] == "document_change_review"
    assert set(preview.json()["data"]) == {"context", "metadata", "evidence", "document_change_source_reference", "model_preview_scope"}
    queued = await create(async_client, auth, case)
    identifier = queued["data"]["run_id"]
    claim, outbound = await execute(case)
    assert claim[0] == identifier and len(outbound) == 1
    db.expire_all()
    assert db.get(AIRun, identifier).status == "succeeded"
    packets = {"preview": preview.json(), "queued": queued}
    for key, path in {
        "detail": f"/api/ai/runs/{identifier}",
        "source": f"/api/ai/runs/{identifier}/document-change/source",
        "scope": f"/api/ai/runs/{identifier}/document-change/scope",
        "result": f"/api/ai/runs/{identifier}/document-change/result",
        "trace": f"/api/ai/admin/runs/{identifier}",
        "history": "/api/ai/runs?feature_key=guideline_change_review&document_change_scope_id=" + case["scope"].snapshot.scope_id,
        "admin_history": "/api/ai/admin/runs?feature_key=guideline_change_review&document_change_scope_id=" + case["scope"].snapshot.scope_id,
    }.items():
        response = await async_client.get(path, headers=auth)
        assert response.status_code == 200, (key, response.text)
        packets[key] = response.json()
    detail, trace = packets["detail"]["data"], packets["trace"]["data"]
    assert detail["split_artifacts"] is True and detail["result"]["schema_version"] == "document_change_result_ref_v1"
    assert packets["result"]["data"]["result"]["document_change"]["automatic_changes"] is False
    assert packets["source"]["data"]["document_change_source"] == case["source"].model_dump(mode="json")
    assert packets["scope"]["data"]["scope_snapshot"] == case["scope"].snapshot.model_dump(mode="json")
    assert "document_change_source" not in trace and "scope_snapshot" not in trace
    for field, anchor in (("frozen_request_json", "input_hash"), ("frozen_evidence_json", "evidence_hash"), ("frozen_context_metadata_json", "metadata_hash")):
        assert c.e.bytes_hash(trace[field]) == detail["document_change_artifact"][anchor]
    assert trace["frozen_request_json"] == db.get(AIRun, identifier).input_json
    feedback = await async_client.post(f"/api/ai/runs/{identifier}/feedback", headers=auth, json={"outcome": "accepted", "comment": "仅工程逐字复核，不是已确认临床影响"})
    assert feedback.status_code == 200, feedback.text
    assert db.query(AIFeedback).filter_by(run_id=identifier).count() == 1
    assert db.query(AIDocumentChangeRunResult).filter_by(run_id=identifier).count() == 1
    assert db.query(AIDocumentChangeRunArtifact).filter_by(run_id=identifier).count() == 1
    packets.update(outbound=outbound, feedback=feedback.json())
    (tmp_path / f"actual-document-change-pipeline-{kind}.json").write_text(c.e.canonical_json(packets))


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["detail", "source", "scope", "result", "feedback"])
async def test_main_current_scope_rejection_reads_zero_private_task_text(async_client, auth_headers, pipeline, path):
    case, db = pipeline, pipeline["db"]
    auth = headers(auth_headers, case)
    queued = await create(async_client, auth, case)
    identifier = queued["data"]["run_id"]
    sources.revoke_scope(db, case["actor"], case["scope"].snapshot.scope_id, {**cas(case["scope"]), "basis_note": NOTE})
    db.commit()
    db.expire_all()
    statements = []

    def record(connection, cursor, statement, parameters, context, many):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    event.listen(db.get_bind(), "before_cursor_execute", record)
    try:
        endpoint = f"/api/ai/runs/{identifier}" + ("" if path == "detail" else "/feedback" if path == "feedback" else "/document-change/" + path)
        response = await async_client.post(endpoint, headers=auth, json={"outcome": "accepted", "comment": NOTE}) if path == "feedback" else await async_client.get(endpoint, headers=auth)
        assert response.status_code == 409, response.text
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", record)
    no_task_text(statements)
    # Explicit frozen Super view still retains the exact registered pieces.
    response = await async_client.get(f"/api/ai/admin/runs/{identifier}/document-change/scope", headers=auth)
    assert response.status_code == 200, response.text
    assert response.json()["data"]["published_governance"]["status"] == "published"


@pytest.mark.asyncio
async def test_main_explicit_cancel_after_scope_revocation_returns_no_private_body(async_client, auth_headers, pipeline):
    case, db = pipeline, pipeline["db"]
    auth = headers(auth_headers, case)
    queued = await create(async_client, auth, case)
    identifier = queued["data"]["run_id"]
    sources.revoke_scope(db, case["actor"], case["scope"].snapshot.scope_id, {**cas(case["scope"]), "basis_note": NOTE})
    db.commit()
    response = await async_client.post(f"/api/ai/runs/{identifier}/cancel", headers=auth)
    assert response.status_code == 200 and set(response.json()) == {"code", "msg"}
    db.expire_all()
    assert storage.usage_receipt(db, db.get(AIRun, identifier)).model_call_attempted is False


@pytest.mark.asyncio
@pytest.mark.parametrize("scope", ["patient_id", "encounter_ref", "roster_plan_id", "document_original_id", "unknown"])
async def test_main_mixed_scope_request_is_rejected_before_queue(async_client, auth_headers, pipeline, scope):
    case = pipeline
    values = body(case)
    if scope == "patient_id":
        values[scope] = 1
    elif scope == "encounter_ref":
        values[scope] = "synthetic-other-scope"
    else:
        values["input"][scope] = "00000000-0000-0000-0000-000000000001"
    response = await async_client.post("/api/ai/runs", headers=headers(auth_headers, case), json=values)
    assert response.status_code == 422
    assert case["db"].query(AIRun).filter_by(feature_key=storage.FEATURE_KEY).count() == 0


@pytest.mark.asyncio
async def test_main_history_rejects_foreign_scope_and_damaged_feature_markers_never_become_generic(async_client, auth_headers, pipeline):
    case, db = pipeline, pipeline["db"]
    auth = headers(auth_headers, case)
    queued = await create(async_client, auth, case)
    identifier = queued["data"]["run_id"]
    mixed = await async_client.get("/api/ai/runs?feature_key=guideline_change_review&patient_id=1", headers=auth)
    assert mixed.status_code == 422
    db.execute(
        text("UPDATE hoimsystem_ai_run SET feature_key='patient_summary', input_json='{}', context_metadata_json='{}', evidence_json='[]', result_json='{}' WHERE run_id=:id"), {"id": identifier}
    )
    db.commit()
    response = await async_client.get(f"/api/ai/runs/{identifier}", headers=auth)
    assert response.status_code == 409, response.text


@pytest.mark.parametrize("feature", ["patient_summary", "guideline_ingestion", "feedback_trends"])
def test_scope_reference_cannot_enter_another_feature(feature):
    with pytest.raises(ValueError):
        RunRequest(feature_key=feature, input={"document_change_scope_id": "00000000-0000-0000-0000-000000000001"})


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["queued_result", "unknown_status"])
async def test_unaccepted_model_body_and_unknown_status_cannot_be_displayed(async_client, auth_headers, pipeline, mutation):
    case, db = pipeline, pipeline["db"]
    auth = headers(auth_headers, case)
    queued = await create(async_client, auth, case)
    identifier = queued["data"]["run_id"]
    run = db.get(AIRun, identifier)
    if mutation == "queued_result":
        run.result_json = c.e.canonical_json({"summary": "UNACCEPTED_PRIVATE_SENTINEL"})
    else:
        run.status = "unknown_status"
    db.commit()
    response = await async_client.get(f"/api/ai/runs/{identifier}", headers=auth)
    assert response.status_code == 409 and "UNACCEPTED_PRIVATE_SENTINEL" not in response.text


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["scope", "role", "provider", "cancel"])
async def test_main_paid_reply_lost_authority_or_explicit_cancel_has_receipt_but_no_body(async_client, auth_headers, pipeline, mutation):
    case, db = pipeline, pipeline["db"]
    auth = headers(auth_headers, case)
    queued = await create(async_client, auth, case)
    identifier = queued["data"]["run_id"]
    claimed = runtime.claim_next_run(db)
    assert claimed and claimed[0] == identifier
    transport, packets, close = model_transport(case, mutate=lambda: mutate_current(case, mutation, identifier))
    try:
        await runtime.execute_claimed(*claimed, transport=transport)
    finally:
        close()
    db.expire_all()
    run = db.get(AIRun, identifier)
    assert len(packets) == 1 and run.status == ("cancelled" if mutation == "cancel" else "failed")
    assert run.result_json == "{}" and db.get(AIDocumentChangeRunResult, identifier) is None
    usage = storage.usage_receipt(db, run)
    assert (usage.input_tokens, usage.output_tokens, usage.complete, usage.model_call_attempted) == (11, 13, True, True)


@pytest.mark.asyncio
async def test_shared_claim_selects_only_header_and_pre_call_scope_loss_is_known_zero(async_client, auth_headers, pipeline):
    case, db = pipeline, pipeline["db"]
    auth = headers(auth_headers, case)
    queued = await create(async_client, auth, case)
    identifier = queued["data"]["run_id"]
    mutate_current(case, "scope", identifier)
    statements = []

    def note(connection, cursor, statement, parameters, context, many):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    event.listen(db.get_bind(), "before_cursor_execute", note)
    try:
        claim = runtime.claim_next_run(db)
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", note)
    assert claim[0] == identifier
    no_task_text(statements)
    transport, packets, close = model_transport(case)
    try:
        await runtime.execute_claimed(*claim, transport=transport)
    finally:
        close()
    db.expire_all()
    run = db.get(AIRun, identifier)
    assert not packets and run.status == "failed"
    assert storage.usage_receipt(db, run).model_dump(mode="json") == {"input_tokens": 0, "output_tokens": 0, "complete": True, "model_call_attempted": False}


@pytest.mark.asyncio
@pytest.mark.parametrize("cancelled", [False, True])
async def test_abandoned_claim_recovery_uses_specific_unknown_receipt_and_never_retries(async_client, auth_headers, pipeline, monkeypatch, cancelled):
    import datetime

    case, db = pipeline, pipeline["db"]
    queued = await create(async_client, headers(auth_headers, case), case)
    identifier = queued["data"]["run_id"]
    claim = runtime.claim_next_run(db)
    run = db.get(AIRun, identifier)
    if cancelled:
        from app.ai.document_change_runtime import cancel_change_run

        cancel_change_run(db, case["actor"], identifier)
    future = sources.utcnow() + datetime.timedelta(minutes=11)
    monkeypatch.setattr(sources, "utcnow", lambda: future)
    assert runtime.expire_interrupted_runs(db) == 1
    db.expire_all()
    run = db.get(AIRun, identifier)
    assert run.status == ("cancelled" if cancelled else "failed")
    assert run.lease_token == claim[1] and run.error_code == "WORKER_INTERRUPTED" and run.result_json == "{}"
    assert storage.usage_receipt(db, run).model_dump(mode="json") == {"input_tokens": None, "output_tokens": None, "complete": False, "model_call_attempted": None}
    assert runtime.expire_interrupted_runs(db) == 0 and runtime.claim_next_run(db) is None


@pytest.mark.parametrize("reader", ["list", "trace"])
@pytest.mark.parametrize("change", ["role", "token"])
def test_admin_reader_captures_loaded_request_epoch_before_orm_refresh(db_session, seed_data, reader, change):
    from fastapi import HTTPException

    from app.routers import ai_admin

    actor = seed_data["super_admin_user"]
    assert actor.user_role == "super_admin" and actor.token_invalid_before is None
    db_session.execute(
        text("UPDATE hoimsystem_users SET " + ("user_role='admin'" if change == "role" else "token_invalid_before='2030-01-01 00:00:00.123456'") + " WHERE user_id=:id"), {"id": actor.user_id}
    )
    statements = []

    def note(connection, cursor, statement, parameters, context, many):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    event.listen(db_session.get_bind(), "before_cursor_execute", note)
    try:
        with pytest.raises(HTTPException) as error:
            if reader == "list":
                ai_admin.list_global_runs(db=db_session, user=actor)
            else:
                ai_admin.inspect_run_trace("no-private-task-read", db=db_session, user=actor)
        assert error.value.status_code == 403
    finally:
        event.remove(db_session.get_bind(), "before_cursor_execute", note)
        db_session.rollback()
    # Mixed native directories acquire their common canonical Gate order
    # before refreshing the authenticated actor. No private task read follows.
    from app.ai.charge_reconciliation_models import AIChargeWriteGate
    from app.ai.infection_cluster_models import AIInfectionWriteGate
    from app.ai.inventory_native_source_models import AIInventoryWriteGate
    from app.ai.satisfaction_models import AISatisfactionWriteGate

    tables = [AIChargeWriteGate.__tablename__, AISatisfactionWriteGate.__tablename__, AIInventoryWriteGate.__tablename__, AIInfectionWriteGate.__tablename__, "hoimsystem_users"]
    assert len(statements) == len(tables)
    assert all(("FROM " + table) in statement for table, statement in zip(tables, statements, strict=True))
    no_task_text(statements)


MARKERS = [
    ("input_json", {"payload": {"input": {"document_change_scope_id": None}, "context": {}}}),
    ("input_json", {"payload": {"input": {}, "context": {"document_change_binding": None}}}),
    ("input_json", {"payload": {"input": {}, "context": {"document_change_source": None}}}),
    ("input_json", {"payload": {"input": {}, "context": {"document_change_private_scope": None}}}),
    ("input_json", {"payload": {"input": {}, "context": {"scope": "document_change_review"}}}),
    ("input_json", {"payload": {"input": {}, "context": {"source_domain": "document_change_review"}}}),
    ("input_json", {"payload": {"input": {}, "context": {"selected_sources": {"document_change_scope_id": None}}}}),
    ("context_metadata_json", {"selected_sources": {"document_change_scope_id": None}}),
    ("result_json", {"document_change": None}),
    ("result_json", {"schema_version": "document_change_result_ref_v1"}),
    ("evidence_json", [{"kind": "document_change_scope"}]),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("field,marker", MARKERS)
async def test_missing_artifact_rewritten_feature_each_remaining_native_marker_returns409_without_text(async_client, auth_headers, pipeline, field, marker):
    case, db = pipeline, pipeline["db"]
    auth = headers(auth_headers, case)
    queued = await create(async_client, auth, case)
    identifier = queued["data"]["run_id"]
    db.query(AIDocumentChangeRunArtifact).filter_by(run_id=identifier).delete(synchronize_session=False)
    db.execute(
        text("UPDATE hoimsystem_ai_run SET feature_key='patient_summary', input_json='{}', context_metadata_json='{}', evidence_json='[]', result_json='{}' WHERE run_id=:id"), {"id": identifier}
    )
    db.execute(text("UPDATE hoimsystem_ai_run SET " + field + "=:marker WHERE run_id=:id"), {"id": identifier, "marker": c.e.canonical_json(marker)})
    db.commit()
    result_columns = []

    def note(connection, cursor, statement, parameters, context, many):
        if statement.lstrip().upper().startswith("SELECT") and context.compiled is not None:
            result_columns.extend(item.keyname for item in context.compiled._result_columns)

    event.listen(db.get_bind(), "before_cursor_execute", note)
    try:
        response = await async_client.get(f"/api/ai/runs/{identifier}", headers=auth)
        assert response.status_code == 409, response.text
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", note)
        db.query(AIRun).filter_by(run_id=identifier).delete(synchronize_session=False)
        db.commit()
    private = {"input_json", "evidence_json", "context_metadata_json", "result_json", "source_json"}
    assert not any(name == field or name.endswith("_" + field) for name in result_columns for field in private)
    assert "document_change_marker" in result_columns


@pytest.mark.parametrize("raw", ["{", "null", "[]", '{"unrelated":null}', '{"summary":"ordinary generic"}'])
def test_marker_metadata_probe_handles_invalid_scalar_json_without_native_false_positive(pipeline, raw):
    from app.ai.document_change_access import has_native_identity

    case, db = pipeline, pipeline["db"]
    identifier = "ordinary-non-uuid-marker-probe"
    run = AIRun(
        run_id=identifier,
        feature_key="patient_summary",
        requested_by=case["actor_id"],
        provider_id=case["provider_id"],
        provider_revision=1,
        prompt_version=0,
        prompt_hash="0" * 64,
        context_digest="0" * 64,
        preview=1,
        status="failed",
        input_json=raw,
        evidence_json=raw,
        context_metadata_json=raw,
        result_json=raw,
    )
    db.add(run)
    db.commit()
    try:
        assert has_native_identity(db, identifier) is False
    finally:
        db.delete(run)
        db.commit()
