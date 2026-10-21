"""Actual Main/JWT submitted-practice task routes, whole parts and human review."""

import hashlib
import json

import httpx
import pytest
from sqlalchemy import event, func

from app.ai import clinical_training_attempts as attempts
from app.ai import clinical_training_contract as c
from app.ai import clinical_training_execution as execution
from app.ai import clinical_training_receipts as receipts
from app.ai import clinical_training_reviews as reviews
from app.ai import clinical_training_runtime as runtime
from app.ai import clinical_training_views as views
from app.ai.models import AIAuditEvent, AIFeatureConfig, AIFeedback
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
from tests.test_ai_clinical_training_views import state

BASE = "/api/ai/clinical-training"


@pytest.fixture
def committed_configuration(configured):
    # These actual HTTP/worker cases deliberately cross real commits. The
    # base configured fixture only rolls back, so release its unique config
    # explicitly just as the existing stored Task fixture does.
    try:
        yield configured
    finally:
        db = configured["db"]
        db.rollback()
        db.query(AIFeatureConfig).filter_by(feature_key="clinical_training").delete()
        db.commit()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["chat", "responses"])
@pytest.mark.parametrize("known", [False, True])
async def test_actual_main_committed_native_task_both_protocols_whole_parts_human_feedback_and_technical_super(committed_configuration, async_client, auth_headers, kind, known, tmp_path):
    case, db = committed_configuration, committed_configuration["db"]
    case["provider"].kind = kind
    case["provider"].api_key_env = ""
    owner, supervisor = auth_headers(case["actor"].username), auth_headers(case["author"].username)
    selection = selected(case)
    db.commit()
    packets = []

    async def call(method, path, *, headers=owner, body=None, status=200):
        response = await async_client.request(method, path, headers=headers, **({"json": body} if body is not None else {}))
        assert response.status_code == status, response.text
        packets.append(dict(method=method, path=path, status=response.status_code, request=body, body=response.text))
        return response

    response = await call("GET", BASE + "/task-descriptor")
    assert response.json()["data"]["grade_policy"] == "server_score_unchanged"
    response = await call("POST", BASE + "/tasks", body=selection)
    metadata = response.json()["data"]
    key = metadata["run_id"]
    assert metadata["status"] == "queued" and metadata["binding"]["clinical_training_submission_id"] == selection["clinical_training_submission_id"]
    response = await call("GET", BASE + f"/tasks/{key}/parts/result")
    assert response.content == b"null"
    source = views.read_part(db, case["actor"], key, "source")
    db.commit()
    lease = runtime.claim_training_run(db, key)
    assert lease is not None
    factory, active, _ = sessions(db)
    db.commit()
    calls = []

    async def handler(request):
        assert not active and not db.in_transaction()
        calls.append(request)
        packet = json.loads(request.content)
        wire = json.loads(packet["messages"][1]["content"] if kind == "chat" else packet["input"])
        assert wire["source"] == source.model_dump(mode="json")
        counters = {"prompt_tokens" if kind == "chat" else "input_tokens": 11} if known else {}
        return httpx.Response(200, json=envelope(kind, draft(source.model_dump(mode="json")), counters))

    await execution.execute_training_claimed(key, lease, session_factory=factory, transport=httpx.MockTransport(handler))
    assert len(calls) == 1 and not active
    parts = {}
    for name in views.PARTS:
        response = await call("GET", BASE + f"/tasks/{key}/parts/{name}")
        assert response.headers["X-AI-Parts-Wire"] == "canonical_json_body_no_envelope"
        assert response.content == c.whole(response.json()).encode()
        parts[name] = response.json()
    assert parts["result"]["grade_policy"] == "server_score_unchanged"
    assert parts["source"]["feedback"] == source.feedback.model_dump(mode="json")
    assert parts["task"]["binding"]["prompt_snapshot_hash"] == hashlib.sha256(parts["task"]["prompt_snapshot_json"].encode()).hexdigest()
    actual = attempts.technical_header(db, key)
    receipt = receipts.read_receipt(db, actual)
    accepted = receipts._accepted_header(db, actual, receipt)
    original_ids = [actual.artifact[name] for name in ("created_audit_event_id", "claim_event_id", "dispatch_event_id", "usage_event_id")] + [accepted["accept_audit_event_id"]]
    assert len(set(original_ids)) == 5
    db.commit()
    response = await call("POST", BASE + f"/tasks/{key}/feedback", body=dict(outcome="accepted", comment="合成教学草稿人工复核，不变更练习成绩"))
    feedback_id = response.json()["data"]["feedback_id"]
    event_row = db.query(AIAuditEvent).filter_by(action="training.task.feedback", target=key).one()
    detail = json.loads(event_row.detail_json)
    assert detail["accept_audit_event_id"] == accepted["accept_audit_event_id"] and detail["grade_policy"] == "server_score_unchanged"
    assert detail["feedback_id"] == feedback_id and event_row.event_id not in original_ids
    assert db.get(AIFeedback, feedback_id).outcome == "accepted"
    db.commit()
    response = await call("GET", BASE + "/tasks?submission_id=" + selection["clinical_training_submission_id"])
    assert any(item["run_id"] == key and item["parts_state"] == "available" for item in response.json()["data"]["items"])
    response = await call("GET", BASE + "/tasks", headers=supervisor)
    item = next(item for item in response.json()["data"]["items"] if item["run_id"] == key)
    assert item["binding"] is None and item["usage"]["input_tokens"] == (11 if known else None) and item["usage"]["output_tokens"] is None
    response = await call("GET", BASE + f"/tasks/{key}/trace", headers=supervisor)
    assert response.json()["data"]["parts"] == {}
    await call("GET", BASE + f"/tasks/{key}/parts/source", headers=supervisor, status=403)
    await call("GET", BASE + "/tasks?submission_id=" + selection["clinical_training_submission_id"], headers=supervisor, status=403)
    (tmp_path / "actual-main-training-task-packets.json").write_text(json.dumps(packets, ensure_ascii=False, indent=2))


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["queued", "running", "succeeded", "failed", "cancelled", "cancel_pending"])
async def test_actual_main_all_states_null_result_and_withdrawn_current_owner_denied_before_body(stored, async_client, auth_headers, mode):
    case, key = state(stored, mode)
    db = case["db"]
    owner = auth_headers(case["actor"].username)
    supervisor = auth_headers(case["author"].username)
    response = await async_client.get(BASE + f"/tasks/{key}/parts/result", headers=owner)
    assert response.status_code == 200, response.text
    assert (response.json() is None) is (mode != "succeeded")
    reviews.revoke_review(db, case["author"], case["review"]["review_id"], dict(revision=1, reason="实际课程教学范围撤回"))
    db.commit()
    columns, observer = observe_bodies(db)
    try:
        for suffix in ("", "/parts/source", "/parts/task", "/parts/binding", "/parts/result"):
            response = await async_client.get(BASE + f"/tasks/{key}" + suffix, headers=owner)
            assert response.status_code == 403, response.text
        response = await async_client.get(BASE + f"/tasks/{key}", headers=supervisor)
        assert response.status_code == 200 and response.json()["data"]["binding"] is None
    finally:
        event.remove(db.get_bind(), "after_cursor_execute", observer)
    assert_zero_bodies(columns)


@pytest.mark.asyncio
@pytest.mark.parametrize("query", ["page=true", "size=51", "page=1&page=2", "patient_id=1", "submission_id=null"])
async def test_actual_task_directory_rejects_nonexact_or_foreign_scope_before_body(stored, async_client, auth_headers, query):
    case, _ = stored
    response = await async_client.get(BASE + "/tasks?" + query, headers=auth_headers(case["actor"].username))
    assert response.status_code == 422, response.text


@pytest.mark.asyncio
async def test_current_main_task_source_selection_and_preview_never_accepts_patient_free_text_or_other_learner(stored, async_client, auth_headers):
    case, key = stored
    owner, supervisor = auth_headers(case["actor"].username), auth_headers(case["author"].username)
    before = case["db"].scalar(func.count(AIFeedback.feedback_id))
    for fields in ({"patient_id": 1}, {"question": "不允许自由文本替代结构化作答"}, {"preview": True}):
        response = await async_client.post(BASE + "/tasks", headers=owner, json={**selected(case), **fields})
        assert response.status_code in {403, 422}, response.text
    response = await async_client.post(BASE + "/tasks", headers=supervisor, json={**selected(case), "preview": True})
    assert response.status_code == 403, response.text
    response = await async_client.post(BASE + f"/tasks/{key}/feedback", headers=owner, json=dict(outcome="accepted"))
    assert response.status_code == 409, response.text
    assert case["db"].scalar(func.count(AIFeedback.feedback_id)) == before
