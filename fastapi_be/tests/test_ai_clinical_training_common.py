"""Actual shared Main/queue/worker/history/feedback uses the full native course."""

import json

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy import event, inspect

from app.ai import clinical_training_attempts as attempts
from app.ai import clinical_training_contract as c
from app.ai import clinical_training_receipts as receipts
from app.ai import clinical_training_reviews as reviews
from app.ai import clinical_training_runtime as native
from app.ai import clinical_training_storage as storage
from app.ai import clinical_training_views as views
from app.ai import runtime as shared
from app.ai.catalog import FEATURE_BY_KEY
from app.ai.clinical_training_run_models import AITrainingRunArtifact
from app.ai.models import AIRun
from app.ai.operational_sources import operational_context, operational_options
from tests.test_ai_clinical_training_configuration import configured as configured
from tests.test_ai_clinical_training_configuration import selected
from tests.test_ai_clinical_training_gateway import envelope
from tests.test_ai_clinical_training_practice import practice_case as practice_case
from tests.test_ai_clinical_training_reference_sql import reference_case as reference_case
from tests.test_ai_clinical_training_registry import observe_bodies
from tests.test_ai_clinical_training_reviews import reviewed_case as reviewed_case
from tests.test_ai_clinical_training_runtime import sessions
from tests.test_ai_clinical_training_storage import assert_zero_bodies
from tests.test_ai_clinical_training_storage import stored as stored
from tests.test_ai_clinical_training_task_contract import draft


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["chat", "responses"])
@pytest.mark.parametrize("mode", ["both", "input", "output", "unknown"])
async def test_actual_common_create_exact_native_claim_closed_sql_worker_history_and_feedback(stored, async_client, auth_headers, monkeypatch, kind, mode, tmp_path):
    from app import database

    case, old_key = stored
    db = case["db"]
    owner, supervisor = auth_headers(case["actor"].username), auth_headers(case["author"].username)
    native.cancel_training_run(db, case["author"], old_key)
    case["provider"].kind = kind
    case["provider"].revision += 1
    db.commit()
    packets = []

    async def call(method, path, *, headers=owner, body=None, status=200):
        response = await async_client.request(method, path, headers=headers, **({"json": body} if body is not None else {}))
        assert response.status_code == status, response.text
        packets.append(dict(method=method, path=path, request=body, status=response.status_code, body=response.text))
        return response

    response = await call("POST", "/api/ai/runs", body=dict(feature_key="clinical_training", input=selected(case)))
    meta = response.json()["data"]
    key = meta["run_id"]
    assert meta["status"] == "queued" and meta["binding"]["clinical_training_submission_id"] == case["submission"]["submission_id"]
    source = views.read_part(db, case["actor"], key, "source")
    db.commit()
    factory, active, _ = sessions(db)
    monkeypatch.setattr(database, "SessionLocal", factory)
    with factory() as worker:
        claim = shared.claim_next_run(worker)
    assert claim is not None and claim[0] == key and not active
    with factory() as worker:
        assert shared.claim_next_run(worker) is None
    inputs, outputs = (11 if mode in {"both", "input"} else None), (7 if mode in {"both", "output"} else None)
    ikey, okey = ("prompt_tokens", "completion_tokens") if kind == "chat" else ("input_tokens", "output_tokens")
    calls = []

    async def handler(request):
        assert not active and not db.in_transaction()
        calls.append(request)
        packet = json.loads(request.content)
        visible = json.loads(packet["messages"][1]["content"] if kind == "chat" else packet["input"])
        assert visible["source"] == source.model_dump(mode="json")
        counters = {name: value for name, value in ((ikey, inputs), (okey, outputs)) if value is not None}
        return httpx.Response(200, json=envelope(kind, draft(source.model_dump(mode="json")), counters))

    transport = httpx.MockTransport(handler)
    await shared.execute_claimed(*claim, transport=transport)
    await shared.execute_claimed(*claim, transport=transport)
    assert len(calls) == 1 and not active
    actual = attempts.technical_header(db, key)
    receipt = receipts.read_receipt(db, actual)
    assert receipt.status == "succeeded" and (receipt.usage.input_tokens, receipt.usage.output_tokens) == (inputs, outputs)
    db.commit()
    response = await call("GET", "/api/ai/runs/" + key)
    assert response.json()["data"]["usage"]["input_tokens"] == inputs
    response = await call("GET", "/api/ai/runs?feature_key=clinical_training")
    assert any(item["run_id"] == key for item in response.json()["data"])
    await call("POST", "/api/ai/runs/" + key + "/feedback", body=dict(outcome="accepted", comment="实际共享入口教学草稿复核"))
    for suffix in ("?feature_key=clinical_training", ""):
        response = await call("GET", "/api/ai/admin/runs" + suffix, headers=supervisor)
        item = next(item for item in response.json()["data"] if item["run_id"] == key)
        assert item["binding"] is None and item["usage"]["input_tokens"] == inputs and item["usage"]["output_tokens"] == outputs
        assert source.source_id not in c.canonical_json(item)
    response = await call("GET", "/api/ai/admin/runs/" + key, headers=supervisor)
    assert response.json()["data"]["parts"] == {} and response.json()["data"]["run"]["binding"] is None
    reviews.revoke_review(db, case["author"], case["review"]["review_id"], dict(revision=1, reason="共享入口实际课程范围撤回"))
    db.commit()
    columns, observer = observe_bodies(db)
    try:
        await call("GET", "/api/ai/runs/" + key, status=403)
        await call("POST", "/api/ai/runs/" + key + "/feedback", body=dict(outcome="accepted"), status=403)
        response = await call("GET", "/api/ai/runs/" + key, headers=supervisor)
        assert response.json()["data"]["binding"] is None
    finally:
        event.remove(db.get_bind(), "after_cursor_execute", observer)
    assert_zero_bodies(columns)
    (tmp_path / "actual-common-training-packets.json").write_text(json.dumps(packets, ensure_ascii=False, indent=2))


@pytest.mark.asyncio
@pytest.mark.parametrize("claimed", [False, True])
async def test_actual_common_cancel_is_current_super_technical_and_known_unattempted(stored, async_client, auth_headers, claimed):
    case, key = stored
    db = case["db"]
    if claimed:
        assert shared.claim_next_run(db)[0] == key
    owner, supervisor = auth_headers(case["actor"].username), auth_headers(case["author"].username)
    response = await async_client.post("/api/ai/runs/" + key + "/cancel", headers=owner)
    assert response.status_code == 403
    response = await async_client.post("/api/ai/runs/" + key + "/cancel", headers=supervisor)
    assert response.status_code == 200, response.text
    actual = receipts.read_receipt(db, attempts.technical_header(db, key))
    assert actual.status == "cancelled" and actual.usage.model_call_attempted is False
    assert actual.usage.input_tokens == actual.usage.output_tokens == 0


def test_actual_bad_training_creation_proof_does_not_starve_later_valid_native_task(stored):
    case, bad_key = stored
    db = case["db"]
    db.get(AITrainingRunArtifact, bad_key).source_projection_hash = "a" * 64
    db.commit()
    good_key = native.create_training_run(db, case["actor"], selected(case))
    claimed = shared.claim_next_run(db)
    assert claimed is not None and claimed[0] == good_key != bad_key
    assert storage.run_header(db, bad_key)["status"] == "queued"


def test_erased_feature_and_expired_orm_never_refresh_training_task_before_source(stored):
    case, key = stored
    db = case["db"]
    run = db.get(AIRun, key)
    db.get(AITrainingRunArtifact, key)
    assert inspect(run).identity[0] == key
    db.execute(AIRun.__table__.update().where(AIRun.run_id == key).values(feature_key="operations_qa"))
    db.commit()
    db.expire(run)
    columns, observer = observe_bodies(db)
    try:
        with pytest.raises(HTTPException) as error:
            shared.authorize_run(db, case["actor"], run)
        assert error.value.status_code == 409
    finally:
        event.remove(db.get_bind(), "after_cursor_execute", observer)
    assert_zero_bodies(columns)


@pytest.mark.parametrize("value", [None, "00000000-0000-4000-8000-000000000001"])
def test_foreign_training_marker_and_native_options_reject_before_any_source_sql(value):
    with pytest.raises(HTTPException) as error:
        operational_context(object(), object(), FEATURE_BY_KEY["operations_qa"], dict(clinical_training_submission_id=value))
    assert error.value.status_code == 422
    with pytest.raises(HTTPException) as error:
        operational_options(object(), object(), FEATURE_BY_KEY["clinical_training"])
    assert error.value.status_code == 422


@pytest.mark.asyncio
async def test_actual_main_generic_training_preview_and_uuid_or_null_foreign_marker_refused(stored, async_client, auth_headers):
    case, _ = stored
    headers = auth_headers(case["author"].username)
    response = await async_client.get("/api/ai/service-options?feature_key=clinical_training", headers=headers)
    assert response.status_code == 422
    response = await async_client.post("/api/ai/operational-context", headers=headers, json=dict(feature_key="clinical_training", input={}))
    assert response.status_code == 422
    for value in (None, case["submission"]["submission_id"]):
        response = await async_client.post("/api/ai/operational-context", headers=headers, json=dict(feature_key="operations_qa", input=dict(clinical_training_submission_id=value)))
        assert response.status_code == 422, response.text
