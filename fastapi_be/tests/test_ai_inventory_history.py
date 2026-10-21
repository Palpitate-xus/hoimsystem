"""Actual JWT history, immutable numeric proof and original-scope authorization."""

import json

import pytest

from app.ai import supply_sources as units
from app.ai.inventory_contract import canonical_json, hash_content
from app.ai.inventory_scenario_models import AIInventoryRunResult
from app.ai.models import AIFeedback, AIRun
from app.ai.runtime import execute_claimed
from app.models import Pharmaceutical
from tests.test_ai_inventory_native_source_input import NOTE
from tests.test_ai_inventory_pipeline import NativeInventoryTransport, queued_and_claimed, request
from tests.test_ai_inventory_pipeline import clear_inventory_tasks as clear_inventory_tasks
from tests.test_ai_inventory_pipeline import inventory_case as inventory_case
from tests.test_ai_inventory_pipeline import pipeline_case as pipeline_case


def filters(case):
    return {
        "feature_key": "inventory_optimization",
        "inventory_item_kind": "pharmaceutical",
        "inventory_item_id": case["drug"].pharmaceutical_id,
        "inventory_scenario_id": case["scenario"].scenario_id,
    }


async def create(client, headers, case):
    response = await client.post("/api/ai/runs", headers=headers, json=request(case))
    assert response.status_code == 200, response.text
    return response.json()["data"]["run_id"]


@pytest.mark.asyncio
async def test_own_and_super_history_use_exact_original_sku_and_scenario(async_client, auth_headers, pipeline_case):
    case = pipeline_case
    headers = auth_headers(case["admin"].username)
    run_id = await create(async_client, headers, case)
    own = await async_client.get("/api/ai/runs", headers=headers, params=filters(case))
    assert own.status_code == 200 and [row["run_id"] for row in own.json()["data"]] == [run_id], own.text
    assert "inventory_findings" not in own.json()["data"][0]
    global_history = await async_client.get("/api/ai/admin/runs", headers=auth_headers(case["super"].username), params=filters(case))
    assert global_history.status_code == 200 and global_history.json()["total"] == 1, global_history.text
    assert [row["run_id"] for row in global_history.json()["data"]] == [run_id]
    other = await async_client.get("/api/ai/runs", headers=auth_headers(case["director"].username), params=filters(case))
    assert other.status_code == 200 and other.json()["data"] == [], other.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "scope", ["only_kind", "only_id", "wrong_kind", "float_id", "mixed_patient", "mixed_department", "mixed_bed", "mixed_forecast", "other_feature", "other_original_sku", "uppercase_scenario"]
)
async def test_history_rejects_ambiguous_coerced_or_mixed_original_scope(scope, async_client, auth_headers, db_session, pipeline_case):
    case, values = pipeline_case, filters(pipeline_case)
    if scope == "only_kind":
        values.pop("inventory_item_id")
    elif scope == "only_id":
        values.pop("inventory_item_kind")
    elif scope == "wrong_kind":
        values["inventory_item_kind"] = "drug"
    elif scope == "float_id":
        values["inventory_item_id"] = "1.0"
    elif scope == "mixed_patient":
        values["patient_id"] = 1
    elif scope == "mixed_department":
        values["department_id"] = 1
    elif scope == "mixed_bed":
        values["bed_series_id"] = values["inventory_scenario_id"]
    elif scope == "mixed_forecast":
        values["supply_series_id"] = values["inventory_scenario_id"]
    elif scope == "other_feature":
        values["feature_key"] = "supply_forecast"
    elif scope == "other_original_sku":
        other = Pharmaceutical(name="另一真实合成历史SKU", stock=0, price="0", status=0)
        db_session.add(other)
        db_session.commit()
        values["inventory_item_id"] = other.pharmaceutical_id
    else:
        values["inventory_scenario_id"] = values["inventory_scenario_id"].upper()
    response = await async_client.get("/api/ai/runs", headers=auth_headers(case["admin"].username), params=values)
    assert response.status_code == 422, response.text


@pytest.mark.asyncio
async def test_revoke_hides_ordinary_history_while_super_retains_complete_frozen_numeric_audit(async_client, auth_headers, db_session, pipeline_case):
    case, db = pipeline_case, db_session
    headers = auth_headers(case["admin"].username)
    claim = await queued_and_claimed(async_client, headers, db, case)
    await execute_claimed(*claim, transport=NativeInventoryTransport(case["service"]))
    before = await async_client.get(f"/api/ai/runs/{claim[0]}", headers=headers)
    assert before.status_code == 200 and before.json()["data"]["status"] == "succeeded", before.text
    unit = case["unit"]
    units.review_source(db, case["super"], "unit", unit.unit_definition_id, {"expected_revision": unit.revision, "expected_content_hash": unit.content_hash, "basis_note": NOTE}, revoke=True)
    db.commit()
    detail = await async_client.get(f"/api/ai/runs/{claim[0]}", headers=headers)
    assert detail.status_code == 409, detail.text
    own = await async_client.get("/api/ai/runs", headers=headers, params={"feature_key": "inventory_optimization"})
    assert own.status_code == 200 and own.json()["data"] == [], own.text
    audit = await async_client.get(f"/api/ai/admin/runs/{claim[0]}", headers=auth_headers(case["super"].username))
    assert audit.status_code == 200, audit.text
    frozen = audit.json()["data"]["frozen_request"]["payload"]["context"]["inventory_scenario"]
    assert frozen["snapshot"] and frozen["review_basis_note"] == NOTE and frozen["frozen_task_view"]
    assert frozen["can_review"] is False and frozen["automatic_purchase"] is False
    assert audit.json()["data"]["result"] == before.json()["data"]["result"]


@pytest.mark.asyncio
@pytest.mark.parametrize("endpoint", ["detail", "cancel", "super_trace"])
async def test_native_markers_reject_tampered_feature_before_revealing_originals(endpoint, async_client, auth_headers, db_session, pipeline_case):
    case = pipeline_case
    run_id = await create(async_client, auth_headers(case["admin"].username), case)
    db_session.get(AIRun, run_id).feature_key = "operations_qa"
    db_session.commit()
    path = f"/api/ai/admin/runs/{run_id}" if endpoint == "super_trace" else f"/api/ai/runs/{run_id}" + ("/cancel" if endpoint == "cancel" else "")
    actor = case["super"] if endpoint == "super_trace" else case["admin"]
    response = await (async_client.post if endpoint == "cancel" else async_client.get)(path, headers=auth_headers(actor.username))
    assert response.status_code == 409, response.text
    assert "payload_json" not in response.text and "原明确计数包" not in response.text


@pytest.mark.asyncio
async def test_both_new_hashes_cannot_make_a_false_numeric_proof_readable_or_reviewable(async_client, auth_headers, db_session, pipeline_case):
    case, db = pipeline_case, db_session
    headers = auth_headers(case["admin"].username)
    claim = await queued_and_claimed(async_client, headers, db, case)
    await execute_claimed(*claim, transport=NativeInventoryTransport(case["service"]))
    db.expire_all()
    run = db.get(AIRun, claim[0])
    assert run.status == "succeeded", (run.error_code, run.error_message)
    blob = db.query(AIInventoryRunResult).filter_by(run_id=run.run_id).one()
    value = json.loads(blob.result_json)
    value["inventory_analysis"]["best_known_feasible_cost"]["numerator"] = "999"
    blob.result_json, blob.content_hash = canonical_json(value), hash_content(value)
    blob.result_bytes = len(blob.result_json.encode())
    reference = json.loads(run.result_json)
    reference.update(content_hash=blob.content_hash, result_bytes=blob.result_bytes)
    run.result_json = canonical_json(reference)
    db.commit()
    for path, actor in ((f"/api/ai/runs/{run.run_id}", case["admin"]), (f"/api/ai/admin/runs/{run.run_id}", case["super"])):
        response = await async_client.get(path, headers=auth_headers(actor.username))
        assert response.status_code == 409 and "candidate_results" not in response.text, response.text
    response = await async_client.post(f"/api/ai/runs/{run.run_id}/feedback", headers=headers, json={"outcome": "accepted", "comment": "不能复核损坏的完整工程结果"})
    assert response.status_code == 409 and db.query(AIFeedback).filter_by(run_id=run.run_id).count() == 0, response.text
