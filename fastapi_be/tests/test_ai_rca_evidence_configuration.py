"""Actual Source/config/Prompt SQL before Task execution, no worker or HTTP."""

import datetime as dt
import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import Select, event, inspect, text

from app.ai import rca_evidence_configuration as configuration
from app.ai import rca_evidence_grants as grants
from app.ai import rca_evidence_storage as storage
from app.ai.catalog import FEATURE_BY_KEY
from app.ai.models import AIFeatureConfig, AIPromptVersion, AIProvider, AIRun
from app.ai.rca_evidence_task_prompt import SYSTEM_PROMPT, TASK_PROMPT
from app.config import settings
from app.database import Base
from app.models import User
from tests.test_ai_rca_evidence_context import prepared
from tests.test_ai_rca_evidence_grants import NOW, cas
from tests.test_ai_rca_evidence_grants import grant_case as grant_case
from tests.test_ai_rca_evidence_storage import no_task_text


def configured(case, *, preview=True, enabled=0, kind="chat"):
    db = case["db"]
    Base.metadata.create_all(db.get_bind())
    actor = User(username="rca_config_" + uuid.uuid4().hex[:12], password="synthetic-unused", user_role="super_admin")
    db.add(actor)
    db.commit()
    case["actor"] = actor
    value, _ = prepared(case)
    provider = AIProvider(
        name="synthetic-rca-config-" + uuid.uuid4().hex[:8],
        kind=kind,
        api_base="https://synthetic.invalid/v1",
        model="synthetic-current-model",
        enabled=1,
        allows_patient_data=1,
        timeout_seconds=3,
        max_output_tokens=4096,
        temperature=0.2,
        revision=1,
        created_by=case["actor"].user_id,
    )
    db.add(provider)
    db.flush()
    config = db.get(AIFeatureConfig, "incident_rca")
    if config is None:
        config = AIFeatureConfig(feature_key="incident_rca")
        db.add(config)
    config.provider_id, config.enabled, config.allowed_roles_json = provider.provider_id, enabled, '["super_admin"]'
    config.validation_status, config.validation_note, config.validated_by, config.validated_at = "unreviewed", "", None, None
    config.active_prompt_id, config.daily_limit, config.revision, config.updated_by = None, 100, 1, actor.user_id
    db.commit()
    current = configuration.for_context(db, case["actor"], value, preview, writing=True)
    snapshot = configuration.snapshot_for_context(value, current)
    run = AIRun(run_id=str(uuid.uuid4()), preview=int(preview), prompt_version=current.prompt_version)
    stored = storage.stage_run(db, case["actor"], run, value, snapshot)
    db.commit()
    return stored, value, current


@pytest.mark.parametrize("kind", ["chat", "responses"])
def test_actual_configuration_freezes_complete_catalog_default_prompt_and_provider12_validation5(kind, grant_case):
    case, db = grant_case, grant_case["db"]
    stored, value, _ = configured(case, kind=kind)
    identifier = inspect(stored.run).identity[0]
    loaded, current = configuration.for_execution(db, case["actor"], identifier)
    assert loaded.source == value.source and current.prompt_version == 0
    assert current.task_prompt == FEATURE_BY_KEY["incident_rca"].task_prompt and current.task_prompt != TASK_PROMPT
    assert current.task_prompt.endswith(TASK_PROMPT) and loaded.snapshot.system_prompt == SYSTEM_PROMPT
    assert len(type(current.frozen_provider).model_fields) == 12 and len(type(current.frozen_validation).model_fields) == 5
    assert current.provider.kind == kind and loaded.snapshot.provider_snapshot == current.frozen_provider
    assert loaded.snapshot.actor_epoch.token_invalid_before is None
    assert configuration.current_daily_count(db, case["actor"].user_id, NOW) == 1


@pytest.mark.parametrize("change", ["provider_model", "provider_revision", "provider_limits", "provider_temperature", "feature_revision", "validation_note", "prompt"])
def test_actual_current_provider_complete_validation_and_prompt_changes_reject_the_old_frozen_task(grant_case, change):
    case, db = grant_case, grant_case["db"]
    stored, _, current = configured(case)
    identifier = inspect(stored.run).identity[0]
    if change == "provider_model":
        current.provider.model = "changed-without-revision"
    elif change == "provider_revision":
        current.provider.revision += 1
    elif change == "provider_limits":
        current.provider.max_output_tokens -= 1
    elif change == "provider_temperature":
        current.provider.temperature = 0.3
    elif change == "feature_revision":
        current.config.revision += 1
    elif change == "validation_note":
        current.config.validation_note = "actual changed validation declaration"
    else:
        prompt = AIPromptVersion(feature_key="incident_rca", version=1, task_prompt="明确保存的新版本，不自动替换旧任务", change_note="synthetic", created_by=case["actor"].user_id)
        db.add(prompt)
        db.flush()
        current.config.active_prompt_id = prompt.prompt_id
    db.commit()
    with pytest.raises(HTTPException) as failure:
        configuration.for_execution(db, case["actor"], identifier)
    assert failure.value.status_code == 409


@pytest.mark.parametrize("change", ["provider_disabled", "patient_data", "wrong_protocol", "feature_disabled", "active_prompt_wrong_feature", "invalid_role_json"])
def test_current_unsuitable_configuration_rejects_before_any_task_text(grant_case, change):
    case, db = grant_case, grant_case["db"]
    stored, _, current = configured(case, preview=False, enabled=1)
    identifier = inspect(stored.run).identity[0]
    if change == "provider_disabled":
        current.provider.enabled = 0
    elif change == "patient_data":
        current.provider.allows_patient_data = 0
    elif change == "wrong_protocol":
        current.provider.kind = "specialist"
    elif change == "feature_disabled":
        current.config.enabled = 0
    elif change == "active_prompt_wrong_feature":
        prompt = AIPromptVersion(feature_key="patient_summary", version=1, task_prompt="其它功能Prompt", change_note="synthetic", created_by=case["actor"].user_id)
        db.add(prompt)
        db.flush()
        current.config.active_prompt_id = prompt.prompt_id
    else:
        current.config.allowed_roles_json = '["super_admin","super_admin"]'
    db.commit()

    def attempt():
        with pytest.raises(HTTPException) as failure:
            configuration.for_execution(db, case["actor"], identifier)
        assert failure.value.status_code == 409

    _, columns = no_task_text(db, attempt)
    assert not columns


def test_source_purpose_and_original_epoch_are_checked_before_task_and_before_config_lock_when_purpose_lost(grant_case):
    case, db = grant_case, grant_case["db"]
    stored, value, _ = configured(case)
    identifier = inspect(stored.run).identity[0]
    grant = grants.grant_detail(db, case["actor"], value.binding.event_grant.grant_id)
    grants.revoke_grant(db, case["actor"], grant.identity.grant_id, cas(grant))
    db.commit()
    tables = []

    def record(state):
        if state.is_select and isinstance(state.statement, Select):
            tables.extend(table.name for table in state.statement.get_final_froms() if hasattr(table, "name"))

    def attempt():
        with pytest.raises(HTTPException) as failure:
            configuration.for_execution(db, case["actor"], identifier)
        assert failure.value.status_code == 403

    event.listen(db, "do_orm_execute", record)
    try:
        _, columns = no_task_text(db, attempt)
    finally:
        event.remove(db, "do_orm_execute", record)
    assert not columns and "hoimsystem_ai_feature_config" not in tables


@pytest.mark.parametrize("loss", ["epoch", "future_clock", "overdue"])
def test_original_epoch_and_actual_task_age_never_get_refreshed_as_a_new_task(grant_case, monkeypatch, loss):
    case, db = grant_case, grant_case["db"]
    stored, _, _ = configured(case)
    identifier = inspect(stored.run).identity[0]
    if loss == "epoch":
        db.execute(text("UPDATE hoimsystem_users SET token_invalid_before='2026-10-21 12:00:00.123456' WHERE user_id=:id"), {"id": inspect(case["actor"]).identity[0]})
        db.commit()
        db.refresh(case["actor"])
    else:
        delta = -1 if loss == "future_clock" else settings.AI_MAX_QUEUE_AGE_SECONDS + 1
        monkeypatch.setattr(grants, "utcnow", lambda: NOW + dt.timedelta(seconds=delta))
    with pytest.raises(HTTPException) as failure:
        configuration.for_execution(db, case["actor"], identifier)
    assert failure.value.status_code == (403 if loss == "epoch" else 409)


def test_invalid_current_source_clock_rejects_as_a_closed_conflict_before_task_body(grant_case, monkeypatch):
    case, db = grant_case, grant_case["db"]
    stored, _, _ = configured(case)
    identifier = inspect(stored.run).identity[0]
    monkeypatch.setattr(grants, "utcnow", lambda: NOW - dt.timedelta(microseconds=1))

    def attempt():
        with pytest.raises(HTTPException) as failure:
            storage.load_task(db, case["actor"], identifier)
        assert failure.value.status_code == 409

    _, columns = no_task_text(db, attempt)
    assert not columns
