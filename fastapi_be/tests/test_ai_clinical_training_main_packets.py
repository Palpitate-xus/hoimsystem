"""One actual Main case supplies Source/practice and every native UI task state."""

import asyncio
import json

import httpx
import pytest

from app.ai import clinical_training_views as views
from app.ai import runtime as shared
from tests.test_ai_clinical_training_configuration import configured as configured
from tests.test_ai_clinical_training_contract import submission
from tests.test_ai_clinical_training_gateway import envelope
from tests.test_ai_clinical_training_practice import practice_case as practice_case
from tests.test_ai_clinical_training_reference_sql import reference_case as reference_case
from tests.test_ai_clinical_training_reviews import reviewed_case as reviewed_case
from tests.test_ai_clinical_training_runtime import sessions
from tests.test_ai_clinical_training_storage import stored as stored
from tests.test_ai_clinical_training_task_contract import draft

BASE = "/api/ai/clinical-training"


@pytest.mark.asyncio
async def test_actual_same_main_source_submission_shared_tasks_seven_states_and_withdrawal(stored, async_client, auth_headers, monkeypatch, tmp_path):
    from app import database
    from app.ai import clinical_training_runtime as native

    case, original_key = stored
    db = case["db"]
    headers = {who: auth_headers(case[key].username) for who, key in (("learner", "actor"), ("author", "author"), ("reviewer", "reviewer"))}
    review_id, lesson_id = case["review"]["review_id"], case["lesson"]["lesson_id"]
    native.cancel_training_run(db, case["author"], original_key)
    packets, groups = [], {}
    factory, active, _ = sessions(db)
    monkeypatch.setattr(database, "SessionLocal", factory)

    async def call(method, path, who="learner", body=None, status=200):
        response = await async_client.request(method, path, headers=headers[who], **({"json": body} if body is not None else {}))
        assert response.status_code == status, (path, response.status_code, response.text)
        packets.append(dict(method=method, path=path, actor=who, request=body, status=response.status_code, body=response.text, wire_headers={key: value for key, value in response.headers.items() if key.lower().startswith("x-ai-")}))
        return response

    await call("GET", BASE + f"/lessons/{lesson_id}", "author")
    for name in ("private", "public", "references"):
        await call("GET", BASE + f"/lessons/{lesson_id}/parts/{name}", "author")
    await call("GET", BASE + f"/reviews/{review_id}", "reviewer")
    await call("GET", BASE + f"/reviews/{review_id}/body", "reviewer")
    await call("GET", BASE + "/published-lessons")
    await call("GET", BASE + f"/published-lessons/{review_id}")
    response = await call("POST", BASE + "/submissions", body=dict(review_id=review_id, submission=submission(case["private"])))
    source_id = response.json()["data"]["submission_id"]
    await call("GET", BASE + f"/submissions/{source_id}")
    for name in ("submission", "feedback", "references"):
        await call("GET", BASE + f"/submissions/{source_id}/parts/{name}")
    await call("GET", BASE + "/task-descriptor")

    async def create():
        response = await call("POST", "/api/ai/runs", body=dict(feature_key="clinical_training", input=dict(clinical_training_submission_id=source_id, objective="explain_practice_feedback")))
        return response.json()["data"]["run_id"]

    async def capture(label, key):
        first = len(packets)
        response = await call("GET", "/api/ai/runs/" + key)
        metadata = response.json()["data"]
        for name in views.PARTS:
            await call("GET", BASE + f"/tasks/{key}/parts/{name}")
        groups[label] = dict(run_id=key, packets=list(range(first, len(packets))), metadata=metadata)

    def claim(key):
        with factory() as worker:
            value = shared.claim_next_run(worker)
        assert value is not None and value[0] == key and not active
        return value

    key = await create()
    await capture("queued", key)
    claimed = claim(key)
    await capture("running", key)
    source = (await call("GET", BASE + f"/tasks/{key}/parts/source")).json()

    def success(request):
        assert not active and not db.in_transaction()
        return httpx.Response(200, json=envelope("chat", draft(source), {"prompt_tokens": 11}))

    await shared.execute_claimed(*claimed, transport=httpx.MockTransport(success))
    await capture("succeeded_partial_usage", key)
    await call("POST", "/api/ai/runs/" + key + "/feedback", body=dict(outcome="accepted", comment="同案真实教学反馈人工复核"))
    key = await create()
    await call("POST", "/api/ai/runs/" + key + "/cancel", "author")
    await capture("cancelled_unattempted", key)
    key = await create()
    claimed = claim(key)
    await shared.execute_claimed(*claimed, transport=httpx.MockTransport(lambda request: httpx.Response(503)))
    await capture("failed_attempted_unknown", key)
    key = await create()
    claimed = claim(key)
    arrived, release = asyncio.Event(), asyncio.Event()

    async def held(request):
        assert not active and not db.in_transaction()
        arrived.set()
        await release.wait()
        assert not active
        return httpx.Response(200, json=envelope("chat", draft(source), {"prompt_tokens": 11}))

    work = asyncio.create_task(shared.execute_claimed(*claimed, transport=httpx.MockTransport(held)))
    try:
        await asyncio.wait_for(arrived.wait(), timeout=5)
        await call("POST", "/api/ai/runs/" + key + "/cancel", "author")
        await capture("cancelled_inflight_pending", key)
    finally:
        release.set()
        await work
    await capture("cancelled_inflight_paid_partial", key)
    await call("GET", "/api/ai/admin/runs", "author")
    await call("GET", "/api/ai/admin/runs/" + key, "author")
    await call("GET", BASE + f"/tasks/{key}/parts/source", "author", status=403)
    await call("POST", BASE + f"/reviews/{review_id}/revoke", "author", dict(revision=1, reason="同案实际复核撤回"))
    await call("GET", "/api/ai/runs/" + key, status=403)
    await call("GET", "/api/ai/runs/" + key, "author")
    assert len(groups) == 7 and groups["succeeded_partial_usage"]["metadata"]["usage"]["output_tokens"] is None
    assert groups["cancelled_inflight_pending"]["metadata"]["receipt_pending"] is True
    assert groups["cancelled_inflight_paid_partial"]["metadata"]["usage"]["input_tokens"] == 11
    path = tmp_path / "actual-same-case-main-training-source-practice-task-packets.json"
    path.write_text(json.dumps(dict(scope="One actual Main/JWT case and one new actual Main practice submission; real shared claim/worker with injected HTTP, seven actual native task snapshots, no cross-case packet splicing or real model/clinical validation.", clinical_training_submission_id=source_id, groups=groups, packets=packets), ensure_ascii=False, indent=2))
