"""Actual JWT history filters and global native markers protect the same originals."""

import pytest

from app.ai import supply_sources as facts
from app.ai.models import AIRun
from tests.test_ai_supply_pipeline import clear_supply_tasks as clear_supply_tasks
from tests.test_ai_supply_pipeline import pipeline_case as pipeline_case
from tests.test_ai_supply_pipeline import request
from tests.test_ai_supply_series import series_case as series_case
from tests.test_ai_supply_sources import NOTE
from tests.test_ai_supply_sources import supply_case as supply_case


async def create(client, headers, case):
    response = await client.post("/api/ai/runs", headers=headers, json=request(case))
    assert response.status_code == 200, response.text
    return response.json()["data"]["run_id"]


def filters(case):
    return {"feature_key": "supply_forecast", "supply_item_kind": "pharmaceutical", "supply_item_id": case["drug"].pharmaceutical_id, "supply_series_id": case["series"].series_id}


@pytest.mark.asyncio
async def test_real_own_and_super_history_use_exact_sku_and_original_series(async_client, auth_headers, pipeline_case):
    case = pipeline_case
    headers = auth_headers(case["admin"].username)
    run_id = await create(async_client, headers, case)
    history = await async_client.get("/api/ai/runs", headers=headers, params=filters(case))
    assert history.status_code == 200, history.text
    assert [row["run_id"] for row in history.json()["data"]] == [run_id]
    assert "supply_findings" not in history.json()["data"][0]
    super_history = await async_client.get("/api/ai/admin/runs", headers=auth_headers(case["super"].username), params=filters(case))
    assert super_history.status_code == 200, super_history.text
    assert [row["run_id"] for row in super_history.json()["data"]] == [run_id]
    assert super_history.json()["total"] == 1
    other = await async_client.get("/api/ai/runs", headers=auth_headers(case["director"].username), params=filters(case))
    assert other.status_code == 200 and other.json()["data"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("case_name", ["only_kind", "only_id", "wrong_kind", "float_id", "mixed_patient", "mixed_department", "mixed_bed", "other_feature", "wrong_sku_series", "uppercase_series"])
async def test_real_history_query_rejects_ambiguous_or_mixed_scope(case_name, async_client, auth_headers, pipeline_case):
    case = pipeline_case
    values = filters(case)
    if case_name == "only_kind":
        values.pop("supply_item_id")
    elif case_name == "only_id":
        values.pop("supply_item_kind")
    elif case_name == "wrong_kind":
        values["supply_item_kind"] = "drug"
    elif case_name == "float_id":
        values["supply_item_id"] = "1.0"
    elif case_name == "mixed_patient":
        values["patient_id"] = 1
    elif case_name == "mixed_department":
        values["department_id"] = 1
    elif case_name == "mixed_bed":
        values["bed_series_id"] = values["supply_series_id"]
    elif case_name == "other_feature":
        values["feature_key"] = "inventory_optimization"
    elif case_name == "wrong_sku_series":
        values["supply_item_kind"], values["supply_item_id"] = "consumable", case["consumable"].consumable_id
    else:
        values["supply_series_id"] = values["supply_series_id"].upper()
    response = await async_client.get("/api/ai/runs", headers=auth_headers(case["admin"].username), params=values)
    assert response.status_code == 422, response.text


@pytest.mark.asyncio
async def test_source_revoke_removes_ordinary_history_but_preserves_complete_super_frozen_audit(async_client, auth_headers, db_session, pipeline_case):
    case, db = pipeline_case, db_session
    headers = auth_headers(case["admin"].username)
    run_id = await create(async_client, headers, case)
    unit = case["unit"]
    facts.review_source(db, case["super"], "unit", unit.unit_definition_id, {"expected_revision": unit.revision, "expected_content_hash": unit.content_hash, "basis_note": NOTE}, revoke=True)
    db.commit()
    ordinary = await async_client.get(f"/api/ai/runs/{run_id}", headers=headers)
    assert ordinary.status_code == 409, ordinary.text
    history = await async_client.get("/api/ai/runs", headers=headers, params={"feature_key": "supply_forecast"})
    assert history.status_code == 200 and history.json()["data"] == []
    audit = await async_client.get(f"/api/ai/admin/runs/{run_id}", headers=auth_headers(case["super"].username))
    assert audit.status_code == 200, audit.text
    frozen = audit.json()["data"]["frozen_request"]["payload"]["context"]["supply_series"]
    assert frozen["snapshot"] and frozen["review_basis_note"] == NOTE
    assert frozen["frozen_task_view"] is True and frozen["can_review"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("endpoint", ["detail", "cancel", "super_trace"])
async def test_native_markers_block_tampered_feature_before_any_result_or_trace(endpoint, async_client, auth_headers, db_session, pipeline_case):
    case, db = pipeline_case, db_session
    run_id = await create(async_client, auth_headers(case["admin"].username), case)
    run = db.get(AIRun, run_id)
    run.feature_key = "operations_qa"
    db.commit()
    if endpoint == "super_trace":
        path, actor = f"/api/ai/admin/runs/{run_id}", case["super"]
    else:
        path, actor = f"/api/ai/runs/{run_id}" + ("/cancel" if endpoint == "cancel" else ""), case["admin"]
    response = await (async_client.post if endpoint == "cancel" else async_client.get)(path, headers=auth_headers(actor.username))
    assert response.status_code == 409, response.text
    assert "payload_json" not in response.text and "原明确计数包" not in response.text
