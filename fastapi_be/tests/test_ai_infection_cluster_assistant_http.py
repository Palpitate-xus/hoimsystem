"""Same-case actual Main payloads for the local Task UI; no stitched flags."""

# ruff: noqa: F811 -- actual Source/configuration fixtures are intentionally registered.

import json

import pytest
from sqlalchemy.orm import sessionmaker

from app.ai import infection_cluster_contract as c
from app.ai import infection_cluster_task_runtime as local
from tests.test_ai_infection_cluster_task_storage import profile_case, task_case  # noqa: F401

ROOT = "/api/ai/infection-cluster"


@pytest.mark.asyncio
async def test_actual_main_same_case_feature_source_explicit_local_task_split_success_and_queued_cancel(async_client, task_case, auth_headers, tmp_path):
    case, packets = task_case, []
    headers = auth_headers(case["author"].username)

    async def send(path, method="GET", body=None):
        response = await async_client.request(method, path, json=body, headers=headers)
        assert response.status_code == 200, response.text
        packets.append(
            dict(
                path=path, method=method, request=body, status=response.status_code, raw_utf8=response.text, bytes=len(response.content), sha256=c.text_digest(response.text), response=response.json()
            )
        )
        return response.json()["data"]

    feature = next(v for v in await send("/api/ai/features") if v["key"] == "infection_cluster")
    await send(ROOT + "/snapshots")
    await send(ROOT + f"/snapshots/{case['meta']['snapshot_id']}/parts/public")
    await send(ROOT + "/scenarios")
    await send(ROOT + f"/scenarios/{case['scenario'].scenario_id}")
    await send(ROOT + "/context", "POST", case["task_request"])
    queued = await send(ROOT + "/tasks", "POST", case["task_request"])
    rid = queued["run_id"]
    await send(ROOT + f"/tasks/{rid}")
    sessions = sessionmaker(bind=case["db"].get_bind(), expire_on_commit=False, autoflush=False)
    case["db"].rollback()
    await local.execute_run(sessions, rid)
    metadata = await send(ROOT + f"/tasks/{rid}")
    assert metadata["status"] == "succeeded" and metadata["profile_id"] == feature["local_profile_id"]
    for part in ["task", "source", "result"]:
        await send(ROOT + f"/tasks/{rid}/parts/{part}")
    await send(f"/api/ai/admin/runs/{rid}")
    cancel = await send(ROOT + "/tasks", "POST", case["task_request"])
    before_cancel = await send(ROOT + f"/tasks/{cancel['run_id']}")
    assert before_cancel["status"] == "queued" and before_cancel["usage"] is None
    cancelled = await send(ROOT + f"/tasks/{cancel['run_id']}/cancel", "POST", {})
    assert cancelled == dict(run_id=cancel["run_id"], feature_key="infection_cluster", status="cancelled", result_available=False)
    stopped_metadata = await send(ROOT + f"/tasks/{cancel['run_id']}")
    assert stopped_metadata["usage"]["calculation_attempted"] is False
    await send(ROOT + "/tasks")
    assert all("mapping_key" not in p["raw_utf8"] for p in packets)
    (tmp_path / "actual-infection-local-assistant-main-http.json").write_text(
        json.dumps(
            dict(
                scope="Actual same-case Main JWT/ASGI, published synthetic Source and local Profile, real local CPU and precise SQL receipts; no external model or clinical validation", packets=packets
            ),
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )
