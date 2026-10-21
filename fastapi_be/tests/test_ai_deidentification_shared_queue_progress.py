"""Actual native75 queue progress and current request identities, synthetic only."""

import datetime as dt
import uuid
from types import SimpleNamespace

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy import event, text

from app.ai import runtime
from app.ai.deidentification_dispatch import DeidentificationClaim
from app.ai.deidentification_receipts import usage_receipt
from app.ai.deidentification_run_models import AIDeidentificationRunResult, AIDeidentificationRunSource
from app.ai.deidentification_runtime import cancel_deidentification_run, create_deidentification_run
from app.ai.models import AIFeatureConfig, AIRun
from app.models import User
from tests.test_ai_deidentification_runtime import queue
from tests.test_ai_deidentification_storage import task_case as task_case
from tests.test_ai_research_cohort_sources import research_case as research_case


def observe(db):
    selected = []

    def columns(conn, cursor, statement, params, context, many):
        if statement.lstrip().lower().startswith("select") and cursor.description:
            selected.extend(column[0] for column in cursor.description)

    event.listen(db.bind, "after_cursor_execute", columns)
    return selected, lambda: event.remove(db.bind, "after_cursor_execute", columns)


def no_task_text(selected):
    private = ("input_json", "evidence_json", "context_metadata_json", "source_json", "result_json")
    assert not any(column == field or column.endswith("_" + field) for column in selected for field in private), selected


@pytest.mark.parametrize("field,changed", [("user_role", "patient"), ("token_invalid_before", "2030-01-01 00:00:00")])
def test_loaded_request_epoch_change_denies_before_task_or_source_text(task_case, field, changed):
    case, db = task_case, task_case["db"]
    identifier = queue(case)
    actor = db.get(User, case["actor"].user_id)
    old = getattr(actor, field)
    actor_id = actor.user_id
    assert "user_role" in actor.__dict__ and "token_invalid_before" in actor.__dict__
    db.execute(text("UPDATE hoimsystem_users SET " + field + "=:value WHERE user_id=:id"), {"id": actor.user_id, "value": changed})
    db.flush()
    # Actual raw SQL changed the row, while the loaded request object retains
    # its old epoch. The current SQL read must reject before either body.
    assert actor.__dict__[field] == old
    selected, close = observe(db)
    try:
        with pytest.raises(HTTPException) as rejected:
            runtime.authorize_run(db, actor, SimpleNamespace(run_id=identifier))
        assert rejected.value.status_code == 403
    finally:
        close()
        db.rollback()
        db.execute(text("UPDATE hoimsystem_users SET " + field + "=:value WHERE user_id=:id"), {"id": actor_id, "value": old})
        db.commit()
        # A denied read intentionally leaves its real queued Task intact.
        # Stop this test's own task via the actual API before the next FIFO
        # case; never forge terminal fields merely to isolate the fixture.
        cancel_deidentification_run(db, SimpleNamespace(user_id=actor_id), identifier)
    no_task_text(selected)


@pytest.mark.asyncio
async def test_real_patient_role_demotion_still_claims_then_records_actual_precall_zero(task_case):
    case, db = task_case, task_case["db"]
    identifier = queue(case)
    actor_id = case["actor"].user_id
    db.execute(text("UPDATE hoimsystem_users SET user_role='patient' WHERE user_id=:id"), {"id": actor_id})
    db.commit()
    calls = []
    try:
        claimed = runtime.claim_next_run(db)
        assert isinstance(claimed, DeidentificationClaim) and claimed.run_id == identifier
        db.rollback()
        await runtime.execute_claimed(identifier, claimed.lease_token, deidentification_claim_event_id=claimed.claim_event_id, transport=httpx.MockTransport(lambda request: calls.append(request)))
        db.expire_all()
        run = db.get(AIRun, identifier)
        assert run.status == "failed" and calls == []
        assert usage_receipt(db, run) == {"input_tokens": 0, "output_tokens": 0, "complete": True, "model_call_attempted": False}
        assert db.get(AIDeidentificationRunResult, identifier).dispatch_event_id is None
    finally:
        db.rollback()
        db.execute(text("UPDATE hoimsystem_users SET user_role='admin' WHERE user_id=:id"), {"id": actor_id})
        db.commit()


def test_128_unknown_platform_role_orphans_do_not_block_valid_native_job(task_case):
    case, db = task_case, task_case["db"]
    identifier = queue(case)
    valid = db.get(AIRun, identifier)
    user = User(username="synthetic-unknown-owner-" + uuid.uuid4().hex, user_role="patient")
    db.add(user)
    db.flush()
    user_id = user.user_id
    old_clock = valid.create_time - dt.timedelta(days=1)
    orphan_ids = []
    for _ in range(128):
        orphan = AIRun(
            feature_key="deidentification",
            requested_by=user_id,
            provider_id=valid.provider_id,
            prompt_hash="1" * 64,
            context_digest="2" * 64,
            input_json="{}",
            evidence_json="[]",
            context_metadata_json="{}",
            result_json="{}",
            create_time=old_clock,
        )
        db.add(orphan)
        db.flush()
        orphan_ids.append(orphan.run_id)
    db.execute(text("UPDATE hoimsystem_users SET user_role='unknown_synthetic_role' WHERE user_id=:id"), {"id": user_id})
    db.commit()
    selected, close = observe(db)
    try:
        claimed = runtime.claim_next_run(db)
    finally:
        close()
    assert isinstance(claimed, DeidentificationClaim) and claimed.run_id == identifier
    no_task_text(selected)
    assert db.query(AIRun).filter(AIRun.run_id.in_(orphan_ids), AIRun.status == "queued").count() == 128
    assert db.query(AIDeidentificationRunResult).filter(AIDeidentificationRunResult.run_id.in_(orphan_ids)).count() == 0


def test_128_real_artifacts_with_erased_feature_are_retained_without_two_poll_starvation(task_case):
    case, db = task_case, task_case["db"]
    config = db.get(AIFeatureConfig, "deidentification")
    config.daily_limit = 1000
    db.commit()
    invalid = []
    # Each retained bad head began as a fully authorized real native Task.
    # We do not clone JSON, Artifact rows, claims or usage evidence.
    for _ in range(128):
        run = create_deidentification_run(db, case["actor"], case["input"])
        invalid.append(run.run_id)
    first, second = queue(case), queue(case)
    ids = {"id" + str(index): identifier for index, identifier in enumerate(invalid)}
    placeholders = ",".join(":" + key for key in ids)
    db.execute(text("UPDATE hoimsystem_ai_run SET feature_key='erased',create_time='2000-01-01 00:00:00' WHERE run_id IN (" + placeholders + ")"), ids)
    db.commit()
    selected, close = observe(db)
    try:
        claims = [runtime.claim_next_run(db), runtime.claim_next_run(db)]
    finally:
        close()
    assert all(isinstance(value, DeidentificationClaim) for value in claims)
    assert {value.run_id for value in claims} == {first, second}
    no_task_text(selected)
    assert db.query(AIRun).filter(AIRun.run_id.in_(invalid), AIRun.status == "queued").count() == 128
    assert db.query(AIDeidentificationRunSource).filter(AIDeidentificationRunSource.run_id.in_(invalid)).count() == 128
    assert (
        db.query(AIDeidentificationRunResult)
        .filter(
            AIDeidentificationRunResult.run_id.in_(invalid),
            AIDeidentificationRunResult.claim_event_id.is_(None),
            AIDeidentificationRunResult.dispatch_event_id.is_(None),
            AIDeidentificationRunResult.usage_event_id.is_(None),
        )
        .count()
        == 128
    )
