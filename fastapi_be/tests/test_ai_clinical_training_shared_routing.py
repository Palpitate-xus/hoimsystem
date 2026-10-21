"""Opaque durable dispatch identity grants no course, answer or model access."""

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import event, select, text

from app.ai import clinical_training_shared as shared
from app.ai import clinical_training_storage as storage
from app.ai.models import AIRun
from app.ai.native_task_routing import _STAGED, locate_native_task
from tests.test_ai_clinical_training_configuration import configured as configured
from tests.test_ai_clinical_training_configuration import selected
from tests.test_ai_clinical_training_practice import practice_case as practice_case
from tests.test_ai_clinical_training_reference_sql import reference_case as reference_case
from tests.test_ai_clinical_training_registry import observe_bodies
from tests.test_ai_clinical_training_reviews import reviewed_case as reviewed_case
from tests.test_ai_clinical_training_storage import assert_zero_bodies, counts
from tests.test_ai_clinical_training_storage import stored as stored


def test_actual_same_session_uncommitted_identity_is_found_without_hint_or_orm_instance(stored):
    case, old_key = stored
    db = case["db"]
    key = storage.stage_run(db, case["actor"], selected(case))
    db.info.pop(_STAGED, None)
    db.expunge_all()
    columns, observer = observe_bodies(db)
    try:
        identity = locate_native_task(db, key)
        assert identity.domain == "clinical_training" and identity.run_id == key != old_key
        assert identity.source_id == case["submission"]["submission_id"]
        assert shared.is_located_training_task(db, key) is True
    finally:
        event.remove(db.get_bind(), "after_cursor_execute", observer)
    assert_zero_bodies(columns)
    db.rollback()
    assert locate_native_task(db, key) is None and shared.is_located_training_task(db, key) is False


def test_source_classifier_positive_does_not_restore_changed_requester_role_or_any_task_body(stored):
    case, key = stored
    db = case["db"]
    db.execute(text("UPDATE hoimsystem_users SET user_role='admin' WHERE user_id=:key"), dict(key=case["actor"].user_id))
    columns, observer = observe_bodies(db)
    try:
        assert shared.is_located_training_task(db, key) is True and shared.is_training_task(db, key) is True
        with pytest.raises(HTTPException) as error:
            shared.guard_training_task(db, case["actor"], key)
        assert error.value.status_code == 403
    finally:
        event.remove(db.get_bind(), "after_cursor_execute", observer)
    assert_zero_bodies(columns)


@pytest.mark.parametrize("field", ["feature_key", "input_json", "context_metadata_json"])
def test_remaining_actual_native_marker_identifies_orphan_only_without_loading_raw_json(stored, field):
    case, key = stored
    db = case["db"]
    values = dict(feature_key="operations_qa", input_json="{}", context_metadata_json="{}")
    values[field] = {"feature_key": "clinical_training", "input_json": '{"clinical_training_submission_id":null}', "context_metadata_json": '{"schema_version":"clinical_training_task_metadata_v1"}'}[field]
    run = AIRun(run_id=str(uuid.uuid4()), requested_by=case["actor"].user_id, prompt_hash="a" * 64, context_digest="b" * 64, **values)
    db.add(run)
    db.flush()
    identifier = run.run_id
    columns, observer = observe_bodies(db)
    try:
        assert locate_native_task(db, identifier) is None and shared.is_located_training_task(db, identifier) is False
        assert shared.is_training_task(db, identifier) is True
        with pytest.raises(HTTPException) as error:
            shared.guard_training_task(db, case["actor"], identifier)
        assert error.value.status_code == 409
    finally:
        event.remove(db.get_bind(), "after_cursor_execute", observer)
    assert_zero_bodies(columns)


def test_actual_orphan_quarantine_is_bodyless_and_does_not_fabricate_model_billing_or_source(stored):
    case, key = stored
    db = case["db"]
    run = AIRun(feature_key="clinical_training", requested_by=case["actor"].user_id, prompt_hash="a" * 64, context_digest="b" * 64)
    db.add(run)
    db.flush()
    identifier = run.run_id
    db.commit()
    columns, observer = observe_bodies(db)
    try:
        assert shared.quarantine_orphan(db, identifier) is True
    finally:
        event.remove(db.get_bind(), "after_cursor_execute", observer)
    assert_zero_bodies(columns)
    header = storage.run_header(db, identifier)
    assert header["status"] == "failed" and header["error_code"] == "NATIVE_ARTIFACT_REQUIRED"
    assert locate_native_task(db, identifier) is None
    assert shared.quarantine_orphan(db, identifier) is False


def test_sql_queue_condition_preserves_later_valid_task_without_executing_an_orphan(stored):
    case, key = stored
    db = case["db"]
    orphan = AIRun(feature_key="clinical_training", requested_by=case["actor"].user_id, prompt_hash="a" * 64, context_digest="b" * 64)
    db.add(orphan)
    db.flush()
    # This condition is only candidate filtering. It grants no task body or
    # permission, and the shared queue must still invoke exact native claim.
    selected_ids = list(db.scalars(select(AIRun.run_id).where(AIRun.status == "queued", shared.queue_candidate_condition(db))))
    assert key in selected_ids
    before = counts(db)
    assert shared.is_training_task(db, orphan.run_id) is True
    assert counts(db) == before
