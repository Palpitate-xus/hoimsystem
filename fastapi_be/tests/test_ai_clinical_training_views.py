"""Whole owned parts, technical Super state and generic audit redaction."""

import datetime as dt
import json

import pytest
from fastapi import HTTPException
from sqlalchemy import event, text

from app.ai import clinical_training_attempts as a
from app.ai import clinical_training_cancellation as cancellation
from app.ai import clinical_training_receipts as receipts
from app.ai import clinical_training_result_storage as results
from app.ai import clinical_training_reviews as reviews
from app.ai import clinical_training_storage as storage
from app.ai import clinical_training_views as views
from app.ai.clinical_training_usage_contract import usage
from app.ai.models import AIAuditEvent
from app.routers import ai_admin
from tests.test_ai_clinical_training_configuration import configured as configured
from tests.test_ai_clinical_training_practice import practice_case as practice_case
from tests.test_ai_clinical_training_reference_sql import reference_case as reference_case
from tests.test_ai_clinical_training_registry import observe_bodies
from tests.test_ai_clinical_training_reviews import reviewed_case as reviewed_case
from tests.test_ai_clinical_training_storage import assert_zero_bodies
from tests.test_ai_clinical_training_storage import stored as stored
from tests.test_ai_clinical_training_task_contract import draft


def state(stored, mode):
    case, key = stored
    db = case["db"]
    if mode == "cancelled":
        cancellation.stage_cancel(db, case["author"], key)
    elif mode != "queued":
        claim = a.stage_claim(db, case["actor"], key)
        if mode in {"succeeded", "failed", "cancel_pending"}:
            dispatch = a.stage_dispatch(db, case["actor"], claim)
            if mode == "succeeded":
                source = storage.load_artifact(db, case["actor"], key)[2]
                results.stage_result(db, case["actor"], claim, draft(source.model_dump(mode="json")), dispatch_event_id=dispatch.dispatch_event_id, usage=usage(11, None, True), latency_ms=1)
            elif mode == "failed":
                receipts.stage_terminal(db, claim, dispatch_event_id=dispatch.dispatch_event_id, usage=usage(None, None, True), status="failed", error_code="PROVIDER_HTTP_ERROR", latency_ms=1)
            else:
                cancellation.stage_cancel(db, case["author"], key)
    db.commit()
    return case, key


@pytest.mark.parametrize("mode", ["queued", "running", "succeeded", "failed", "cancelled", "cancel_pending"])
def test_all_actual_owned_task_states_four_whole_parts_and_no_fake_accepted_result(stored, mode):
    case, key = state(stored, mode)
    db = case["db"]
    meta = views.describe_task(db, case["actor"], key)
    assert meta.parts_state == "available" and meta.binding.clinical_training_submission_id == case["submission"]["submission_id"]
    assert meta.status == ("cancelled" if mode == "cancel_pending" else mode)
    assert meta.receipt_pending is (mode == "cancel_pending")
    source = views.read_part(db, case["actor"], key, "source")
    task = views.read_part(db, case["actor"], key, "task")
    binding = views.read_part(db, case["actor"], key, "binding")
    result = views.read_part(db, case["actor"], key, "result")
    assert source.source_id == meta.binding.clinical_training_submission_id and task.binding == binding.binding == meta.binding
    assert task.raw.input_json and task.prompt_snapshot_json and task.execution_snapshot_json
    assert json.loads(task.raw.input_json)["clinical_training_submission_id"] == source.source_id
    if mode == "succeeded":
        assert result.source_id == source.source_id and meta.usage.input_tokens == 11 and meta.usage.output_tokens is None
    else:
        assert result is None
    trace = views.split_trace(db, case["actor"], key)
    assert set(trace["parts"]) == set(views.PARTS) and trace["parts_require_independent_current_reads"] is True


@pytest.mark.parametrize("mode", ["queued", "succeeded", "failed", "cancel_pending"])
def test_other_super_technical_management_has_no_source_feedback_binding_hash_or_parts(stored, mode):
    case, key = state(stored, mode)
    db = case["db"]
    columns, observer = observe_bodies(db)
    try:
        meta = views.describe_task(db, case["author"], key)
        trace = views.split_trace(db, case["author"], key)
    finally:
        event.remove(db.get_bind(), "after_cursor_execute", observer)
    assert_zero_bodies(columns)
    assert meta.binding is None and meta.parts_state == "current_parts_unavailable"
    assert trace["parts"] == {} and trace["run"]["binding"] is None
    raw = storage.c.canonical_json(trace)
    assert all(field not in raw for field in ("submission_hash", "feedback_hash", "source_projection_hash", "source_binding_hash", "correct_option_ids", "selected_option_ids", "matching_count", "raw"))
    if mode == "succeeded":
        assert meta.usage.input_tokens == 11 and meta.usage.output_tokens is None
    for part in views.PARTS:
        with pytest.raises(HTTPException) as error:
            views.read_part(db, case["author"], key, part)
        assert error.value.status_code == 403


def test_withdrawn_source_stays_bodyless_in_super_state_and_forbidden_to_ordinary_owner(stored):
    case, key = stored
    db = case["db"]
    reviews.revoke_review(db, case["author"], case["review"]["review_id"], dict(revision=1, reason="明确撤回本次课程模型处理来源"))
    columns, observer = observe_bodies(db)
    try:
        assert views.describe_task(db, case["author"], key).binding is None
        with pytest.raises(HTTPException) as error:
            views.describe_task(db, case["actor"], key)
        assert error.value.status_code == 403
    finally:
        event.remove(db.get_bind(), "after_cursor_execute", observer)
    assert_zero_bodies(columns)


@pytest.mark.asyncio
async def test_actual_main_super_generic_audit_masks_learner_selections_counts_and_hashes_but_preserves_original_receipts(stored, async_client, auth_headers):
    case, key = stored
    db = case["db"]
    headers = auth_headers(case["author"].username)
    actor_id = case["author"].user_id
    original = db.get(AIAuditEvent, storage.artifact_header(db, key)["created_audit_event_id"])
    original_id, original_raw = original.event_id, original.detail_json
    # Nontraining configuration audits retain their original decimal JSON.
    ordinary = AIAuditEvent(actor_id=actor_id, action="synthetic.ordinary.provider.update", target="synthetic", detail_json='{"temperature":0.125}')
    db.add(ordinary)
    db.commit()
    ordinary_id = ordinary.event_id
    db.commit()
    response = await async_client.get("/api/ai/admin/audit", headers=headers)
    assert response.status_code == 200, response.text
    items = {item["event_id"]: item for item in response.json()["data"]}
    assert items[original_id]["detail"] == dict(schema_version="clinical_training_technical_audit_v1", detail_scope="technical_event_only", current_owner_source_read_required=True)
    assert items[ordinary_id]["detail"] == {"temperature": 0.125}
    for item in items.values():
        if item["action"] == "training_practice_submit" or item["action"].startswith("training.task."):
            assert item["detail"]["detail_scope"] == "technical_event_only"
    assert db.get(AIAuditEvent, original_id).detail_json == original_raw
    db.commit()


@pytest.mark.parametrize("fault", ["role", "epoch"])
def test_generic_super_audit_captures_authenticated_epoch_and_refuses_before_audit_details(stored, fault):
    case, key = stored
    db, actor = case["db"], case["author"]
    assert actor.user_role == "super_admin" and actor.token_invalid_before is None
    update = "user_role='admin'" if fault == "role" else "token_invalid_before=:clock"
    db.execute(text("UPDATE hoimsystem_users SET " + update + " WHERE user_id=:key"), dict(key=actor.user_id, clock=dt.datetime.now(dt.UTC).replace(tzinfo=None)))
    columns, observer = observe_bodies(db)
    try:
        with pytest.raises(HTTPException) as error:
            ai_admin.list_audit(db=db, user=actor, limit=100)
        assert error.value.status_code == 403
    finally:
        event.remove(db.get_bind(), "after_cursor_execute", observer)
    assert "detail_json" not in columns
    assert_zero_bodies(columns)
