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
