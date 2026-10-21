"""Actual native history stays distinct from retained pre-native billing tasks."""

import json
import uuid

import httpx
import pytest

from app.ai.models import AIRun
from tests.test_ai_charge_reconciliation_main_http import charge_case, configured, request_body, source_app

_FIXTURES = (charge_case, source_app)


@pytest.mark.asyncio
async def test_native_only_history_uses_actual_artifact_fk_without_hiding_legacy_read_access(source_app, charge_case, auth_headers):
    case, db = charge_case, charge_case["db"]
    actor, req, _, _, _ = configured(case)
    headers = auth_headers(actor.username)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=source_app), base_url="http://synthetic") as client:
        created = await client.post("/api/ai/runs", headers=headers, json=request_body(req))
        assert created.status_code == 200, created.text
        identifier = created.json()["data"]["run_id"]
        legacy = AIRun(
            run_id=str(uuid.uuid4()),
            feature_key=req.feature_key,
            requested_by=actor.user_id,
            patient_id=req.patient_id,
            encounter_ref=req.encounter_ref,
            status="cancelled",
            prompt_hash="0" * 64,
            context_digest="1" * 64,
            input_json=json.dumps({"payload": {"context": {"billing_scope": {"admission_id": req.encounter_ref}}}}),
        )
        db.add(legacy)
        db.commit()
        query = {"feature_key": req.feature_key, "patient_id": req.patient_id, "encounter_ref": req.encounter_ref}
        old_directory = await client.get("/api/ai/runs", headers=headers, params=query)
        assert old_directory.status_code == 200, old_directory.text
        assert {row["run_id"] for row in old_directory.json()["data"]} == {identifier, legacy.run_id}
        legacy_detail = await client.get("/api/ai/runs/" + legacy.run_id, headers=headers)
        assert legacy_detail.status_code == 200, legacy_detail.text
        native = await client.get("/api/ai/runs", headers=headers, params={**query, "charge_native_only": True})
        assert native.status_code == 200, native.text
        assert [row["run_id"] for row in native.json()["data"]] == [identifier]


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["missing_patient", "missing_admission", "wrong_feature", "invalid_admission", "foreign_admission"])
async def test_native_only_history_requires_current_complete_charge_scope(source_app, charge_case, auth_headers, mutation):
    actor, req, _, _, _ = configured(charge_case)
    query = {"feature_key": req.feature_key, "patient_id": req.patient_id, "encounter_ref": req.encounter_ref, "charge_native_only": True}
    if mutation == "missing_patient":
        query.pop("patient_id")
    elif mutation == "missing_admission":
        query.pop("encounter_ref")
    elif mutation == "wrong_feature":
        query["feature_key"] = "patient_summary"
    elif mutation == "invalid_admission":
        query["encounter_ref"] = "old-ambiguous-admission"
    else:
        query["encounter_ref"] = str(uuid.uuid4())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=source_app), base_url="http://synthetic") as client:
        response = await client.get("/api/ai/runs", headers=auth_headers(actor.username), params=query)
    assert response.status_code in {403, 422}, response.text


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/api/ai/runs", "/api/ai/admin/runs"])
@pytest.mark.parametrize("feature,reference", [("charge_reconciliation", "document_original_id"), ("guideline_ingestion", "charge_case_id")])
async def test_native_histories_reject_the_other_complete_source_scope(source_app, charge_case, auth_headers, path, feature, reference):
    actor, _, _, _, _ = configured(charge_case)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=source_app), base_url="http://synthetic") as client:
        response = await client.get(path, headers=auth_headers(actor.username), params={"feature_key": feature, reference: str(uuid.uuid4())})
    assert response.status_code == 422, response.text


@pytest.mark.asyncio
async def test_document_history_cannot_accept_native_charge_directory_mode(source_app, charge_case, auth_headers):
    actor, _, _, _, _ = configured(charge_case)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=source_app), base_url="http://synthetic") as client:
        response = await client.get("/api/ai/runs", headers=auth_headers(actor.username), params={"feature_key": "guideline_ingestion", "charge_native_only": True})
    assert response.status_code == 422, response.text


def test_charge_read_identity_locators_take_gate_before_any_document_anchor_lock(charge_case):
    from sqlalchemy import event, inspect
    from sqlalchemy.dialects import mysql

    from app.ai.charge_reconciliation_runtime import create_charge_run
    from app.ai.native_task_access import guard_private_task_read

    actor, req, _, _, _ = configured(charge_case)
    db = charge_case["db"]
    run = create_charge_run(db, actor, req)
    run_id = inspect(run).identity[0]
    statements = []

    def observe(state):
        if state.is_select:
            statements.append(str(state.statement.compile(dialect=mysql.dialect())))

    event.listen(db, "do_orm_execute", observe)
    try:
        guard_private_task_read(db, actor, run_id)
    finally:
        event.remove(db, "do_orm_execute", observe)
    gate = next(i for i, sql in enumerate(statements) if "hoimsystem_ai_charge_write_gate" in sql)
    original = next(i for i, sql in enumerate(statements) if "hoimsystem_ai_document_extraction_run_anchor" in sql)
    assert gate < original
    assert statements[gate].rstrip().endswith("FOR UPDATE")
    assert all("FOR UPDATE" not in sql and "LOCK IN SHARE MODE" not in sql for sql in statements[:gate])
    assert all("input_json" not in sql and "result_json" not in sql for sql in statements)
