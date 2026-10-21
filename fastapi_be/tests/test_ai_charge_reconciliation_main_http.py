"""Actual mounted JWT task lifecycle; only model transport is synthetic."""

import json
import uuid

import httpx
import pytest
from sqlalchemy import event, update
from sqlalchemy.dialects import mysql

from app.ai.charge_reconciliation_run_models import AIChargeRunArtifact
from app.ai.models import AIRun
from app.ai.runtime import claim_next_run, execute_claimed
from app.models import InpatientCharge
from tests.test_ai_charge_reconciliation_gateway import envelope
from tests.test_ai_charge_reconciliation_runtime import configured
from tests.test_ai_charge_reconciliation_sources import LITERAL
from tests.test_ai_charge_reconciliation_sources import charge_case as _charge_case
from tests.test_ai_charge_reconciliation_sources_http import source_app as _source_app

charge_case, source_app = _charge_case, _source_app


def request_body(req):
    return req.model_dump(mode="json")


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["chat", "responses"])
async def test_actual_main_create_context_claim_worker_full_trace_feedback_and_fk_history(source_app, charge_case, auth_headers, kind):
    case, db = charge_case, charge_case["db"]
    actor, req, value, _, _ = configured(case, kind=kind)
    headers = auth_headers(actor.username)
    draft = {
        "schema_version": "charge_reconciliation_draft_v1",
        "source_id": value["source_id"],
        "source_projection_hash": value["projection_hash"],
        "coverage": "partial_questions_no_completeness_or_correctness_claim",
        "observations": [],
    }
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=source_app), base_url="http://synthetic") as client:
        features = await client.get("/api/ai/features", headers=headers)
        assert next(row for row in features.json()["data"] if row["key"] == req.feature_key)["input_mode"] == "charge_reconciliation"
        preview = await client.post(
            "/api/ai/context",
            headers=headers,
            json={"feature_key": req.feature_key, "patient_id": req.patient_id, "encounter_ref": req.encounter_ref, "source_refs": {"charge_case_id": req.input["charge_case_id"]}},
        )
        assert preview.status_code == 200, preview.text
        assert preview.json()["data"]["context"]["charge_source"] == value["public_source"] and LITERAL in preview.text
        queued = await client.post("/api/ai/runs", headers=headers, json=request_body(req))
        assert queued.status_code == 200, queued.text
        queued_data = queued.json()["data"]
        identifier = queued_data["run_id"]
        assert queued_data["usage_receipt"] == {"input_tokens": None, "output_tokens": None, "complete": False, "model_call_attempted": None}
        db.rollback()  # Real request sessions close; this shared test dependency does not.
        claimed = claim_next_run(db)
        assert claimed is not None and claimed[0] == identifier
        calls = []

        def handle(request):
            calls.append(request)
            visible = json.loads(request.content)
            visible = json.loads(visible["messages"][1]["content"] if kind == "chat" else visible["input"])
            assert set(visible) == {"charge_source", "source_projection_hash", "question"} and visible["charge_source"] == value["public_source"]
            return httpx.Response(200, json=envelope(kind, draft))

        await execute_claimed(*claimed, transport=httpx.MockTransport(handle))
        assert len(calls) == 1
        detail = await client.get("/api/ai/runs/" + identifier, headers=headers)
        assert detail.status_code == 200, detail.text
        saved = detail.json()["data"]
        assert saved["status"] == "succeeded" and saved["result"]["charge_analysis"] == draft
        assert saved["charge_artifact"]["created_at"] == "2026-10-21T12:30:00.123456Z" and LITERAL in detail.text
        trace = await client.get("/api/ai/admin/runs/" + identifier, headers=headers)
        assert trace.status_code == 200, trace.text
        trace_data = trace.json()["data"]
        raw = trace_data["raw_frozen_json"]
        db.expire_all()
        run = db.get(AIRun, identifier)
        assert raw == {key: getattr(run, key) for key in ("input_json", "evidence_json", "context_metadata_json")}
        assert trace_data["frozen_request"] == json.loads(raw["input_json"])
        feedback = await client.post("/api/ai/runs/" + identifier + "/feedback", headers=headers, json={"outcome": "rejected", "comment": "合成人工复核：模型问题不能确认财务正确。"})
        assert feedback.status_code == 200, feedback.text
        trace = await client.get("/api/ai/admin/runs/" + identifier, headers=headers)
        assert trace.json()["data"]["feedback"][0]["outcome"] == "rejected"
        params = {"feature_key": req.feature_key, "charge_case_id": value["case_snapshot_id"], "patient_id": req.patient_id, "encounter_ref": req.encounter_ref}
        own = await client.get("/api/ai/runs", headers=headers, params=params)
        admin = await client.get("/api/ai/admin/runs", headers=headers, params=params)
        assert own.status_code == admin.status_code == 200, (own.text, admin.text)
        assert [row["run_id"] for row in own.json()["data"]] == [identifier]
        assert [row["run_id"] for row in admin.json()["data"]] == [identifier] and admin.json()["total"] == 1
        assert admin.json()["data"][0]["input_tokens"] == 13


@pytest.mark.asyncio
async def test_actual_main_queued_cancel_has_specific_zero_receipt_and_no_accepted_result(source_app, charge_case, auth_headers):
    case = charge_case
    actor, req, _, _, _ = configured(case)
    headers = auth_headers(actor.username)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=source_app), base_url="http://synthetic") as client:
        created = await client.post("/api/ai/runs", headers=headers, json=request_body(req))
        identifier = created.json()["data"]["run_id"]
        cancelled = await client.post("/api/ai/runs/" + identifier + "/cancel", headers=headers)
        assert cancelled.status_code == 200, cancelled.text
        detail = await client.get("/api/ai/runs/" + identifier, headers=headers)
        assert detail.status_code == 200, detail.text
        data = detail.json()["data"]
        assert data["status"] == "cancelled" and data["result"] is None
        assert data["usage_receipt"] == {"input_tokens": 0, "output_tokens": 0, "complete": True, "model_call_attempted": False}
        assert (await client.post("/api/ai/runs/" + identifier + "/feedback", headers=headers, json={"outcome": "accepted", "comment": ""})).status_code == 409


@pytest.mark.asyncio
@pytest.mark.parametrize("attack", ["no_case", "mixed_refs", "wrong_admission", "foreign_feature", "bool_patient", "string_patient", "float_patient", "string_preview"])
async def test_actual_main_new_tasks_cannot_fall_back_to_legacy_partial_billing_or_other_feature(source_app, charge_case, auth_headers, attack):
    case, db = charge_case, charge_case["db"]
    actor, req, _, _, _ = configured(case)
    if attack == "no_case":
        req.input = {}
    elif attack == "mixed_refs":
        req.input["inpatient_charge_id"] = str(uuid.uuid4())
    elif attack == "wrong_admission":
        req.encounter_ref = str(uuid.uuid4())
    elif attack == "foreign_feature":
        req.feature_key = "patient_summary"
    body = request_body(req)
    if attack == "bool_patient":
        body["patient_id"] = True
    elif attack == "string_patient":
        body["patient_id"] = str(req.patient_id)
    elif attack == "float_patient":
        body["patient_id"] = float(req.patient_id)
    elif attack == "string_preview":
        body["preview"] = "true"
    before = db.query(AIRun).count()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=source_app), base_url="http://synthetic") as client:
        response = await client.post("/api/ai/runs", headers=auth_headers(actor.username), json=body)
    assert response.status_code in {403, 409, 422}, response.text
    assert db.query(AIRun).count() == before


@pytest.mark.asyncio
async def test_actual_main_native_history_current_count_and_actor_guard_precede_artifact_lock(source_app, charge_case, auth_headers):
    case, db = charge_case, charge_case["db"]
    actor, req, value, _, _ = configured(case)
    headers = auth_headers(actor.username)
    statements = []

    def observe(state):
        if state.is_select:
            statements.append(str(state.statement.compile(dialect=mysql.dialect())))

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=source_app), base_url="http://synthetic") as client:
        created = await client.post("/api/ai/runs", headers=headers, json=request_body(req))
        identifier = created.json()["data"]["run_id"]
        event.listen(db, "do_orm_execute", observe)
        try:
            directory = await client.get("/api/ai/admin/runs", headers=headers, params={"feature_key": req.feature_key, "charge_case_id": value["case_snapshot_id"]})
        finally:
            event.remove(db, "do_orm_execute", observe)
        assert directory.status_code == 200, directory.text
        counts = [query for query in statements if "count(" in query.lower() and "hoimsystem_ai_run" in query]
        assert len(counts) == 1 and "LOCK IN SHARE MODE" in counts[0]
        db.execute(update(AIRun).where(AIRun.run_id == identifier).values(feature_key="patient_summary", input_json='{"payload":{"context":{"billing_scope":{}}}}', result_json="{}"))
        db.commit()
        response = await client.get("/api/ai/runs/" + identifier, headers=headers)
        assert response.status_code == 409, response.text
        assert db.get(AIChargeRunArtifact, identifier) is not None


@pytest.mark.asyncio
async def test_actual_main_stale_ordinary_task_is_denied_while_super_retains_frozen_case(source_app, charge_case, auth_headers):
    case, db = charge_case, charge_case["db"]
    actor, req, value, _, _ = configured(case, actor=case["admin_user"], preview=False)
    headers = auth_headers(actor.username)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=source_app), base_url="http://synthetic") as client:
        response = await client.post("/api/ai/runs", headers=headers, json=request_body(req))
        identifier = response.json()["data"]["run_id"]
        db.execute(update(InpatientCharge).where(InpatientCharge.admission_id == req.encounter_ref).values(status=-7))
        db.commit()
        assert (await client.get("/api/ai/runs/" + identifier, headers=headers)).status_code == 409
        audit = await client.get("/api/ai/admin/runs/" + identifier, headers=auth_headers(case["super_admin_user"].username))
        assert audit.status_code == 200, audit.text
        assert audit.json()["data"]["charge_findings"]["charge_source"] == value["public_source"]
        assert LITERAL in audit.text


@pytest.mark.asyncio
@pytest.mark.parametrize("value", [True, "1", 1.0])
async def test_actual_main_native_preview_does_not_coerce_patient_scope(source_app, charge_case, auth_headers, value):
    case = charge_case
    actor, req, _, _, _ = configured(case)
    body = {"feature_key": req.feature_key, "patient_id": value, "encounter_ref": req.encounter_ref, "source_refs": {"charge_case_id": req.input["charge_case_id"]}}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=source_app), base_url="http://synthetic") as client:
        response = await client.post("/api/ai/context", headers=auth_headers(actor.username), json=body)
    assert response.status_code == 422
