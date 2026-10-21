"""Actual Main lifecycle: an absent accepted result is an honest bare null."""

import json

import httpx
import pytest

from app.ai import operations_support_contract as c
from app.ai import runtime as shared
from tests.test_ai_operations_support_main import BASE
from tests.test_ai_operations_support_main import actors as actors
from tests.test_ai_operations_support_main import configured as configured
from tests.test_ai_operations_support_main import pipeline as pipeline
from tests.test_ai_operations_support_main import source as source
from tests.test_ai_operations_support_storage import selection


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["queued", "running", "cancelled", "failed"])
async def test_actual_main_current_non_success_has_four_complete_parts_and_result_null(configured, pipeline, async_client, state, tmp_path):
    value = pipeline
    body = selection(configured)
    configured[0][0].commit()
    configured[0][0].close()
    response = await async_client.post(BASE + "/tasks", headers=value["headers"][3], json=body)
    assert response.status_code == 200, response.text
    value["identifier"] = response.json()["data"]["run_id"]
    if state in {"running", "failed"}:
        with value["factory"]() as db:
            claimed = shared.claim_next_run(db)
        assert claimed is not None and claimed[0] == value["identifier"]
        if state == "failed":
            transport = httpx.MockTransport(lambda request: httpx.Response(503, json={"error": {"message": "isolated synthetic unavailable"}}))
            await shared.execute_claimed(claimed[0], claimed[1], transport=transport)
    elif state == "cancelled":
        response = await async_client.post(BASE + f"/tasks/{value['identifier']}/cancel", headers=value["headers"][0])
        assert response.status_code == 200, response.text
    metadata = await async_client.get(BASE + f"/tasks/{value['identifier']}", headers=value["headers"][3])
    assert metadata.status_code == 200 and metadata.json()["data"]["status"] == state
    packets = []
    for part in ("task", "source", "binding", "result"):
        response = await async_client.get(BASE + f"/tasks/{value['identifier']}/parts/{part}", headers=value["headers"][3])
        assert response.status_code == 200, (part, response.text)
        assert response.headers["X-AI-Parts-Wire"] == "canonical_json_body_no_envelope"
        assert response.content == c.canonical_json(response.json()).encode()
        if part == "result":
            assert response.content == b"null" and response.json() is None
        packets.append(dict(method="GET", path=response.request.url.path, status=response.status_code, body=response.text, parts_wire=response.headers["X-AI-Parts-Wire"]))
    (tmp_path / "actual-non-success-four-parts.json").write_text(json.dumps(dict(state=state, run_id=value["identifier"], packets=packets), ensure_ascii=False, indent=2) + "\n")
