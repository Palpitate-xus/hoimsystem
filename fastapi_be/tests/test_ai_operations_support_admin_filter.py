"""Actual Main/JWT global filter cannot silently drop a selected native Case."""

import uuid

import pytest

from tests.test_ai_operations_support_configuration import actors as actors
from tests.test_ai_operations_support_configuration import configured as configured
from tests.test_ai_operations_support_configuration import source as source
from tests.test_ai_operations_support_main import create
from tests.test_ai_operations_support_main import pipeline as pipeline


@pytest.mark.asyncio
async def test_global_actual_operations_case_filter_returns_only_matching_artifact_without_private_body(configured, pipeline, async_client):
    await create(async_client, configured, pipeline)
    pipeline["state"]["authority_lost"] = True  # SQL projection observer only; the actual Source remains current.
    response = await async_client.get("/api/ai/admin/runs", params={"feature_key": "operations_support", "operations_case_id": pipeline["case_id"]}, headers=pipeline["headers"][0])
    assert response.status_code == 200, response.text
    assert response.json()["total"] == 1 and [r["run_id"] for r in response.json()["data"]] == [pipeline["identifier"]]
    response = await async_client.get("/api/ai/admin/runs", params={"feature_key": "operations_support", "operations_case_id": str(uuid.uuid4())}, headers=pipeline["headers"][0])
    assert response.status_code == 200, response.text
    assert response.json()["total"] == 0 and response.json()["data"] == []
    assert pipeline["reads"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "values",
    [
        {"feature_key": "patient_summary", "operations_case_id": str(uuid.uuid4())},
        {"feature_key": "operations_support", "operations_case_id": str(uuid.uuid4()), "patient_id": "1"},
        {"feature_key": "operations_support", "operations_case_id": str(uuid.uuid4()), "deidentification_case_id": str(uuid.uuid4())},
        {"feature_key": "operations_support", "operations_case_id": "not-a-uuid"},
        {"feature_key": "operations_support", "operations_case_id": str(uuid.uuid4()).upper()},
    ],
)
async def test_global_operations_case_foreign_or_noncanonical_scope_is_explicitly_rejected(configured, pipeline, async_client, values):
    await create(async_client, configured, pipeline)
    pipeline["state"]["authority_lost"] = True
    response = await async_client.get("/api/ai/admin/runs", params=values, headers=pipeline["headers"][0])
    assert response.status_code == 422, response.text
    assert pipeline["reads"] == []
