"""Current provider/config reads and common locking order protect management writes."""

import importlib
import json
import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import event, text
from sqlalchemy.dialects import mysql

from app.ai.gateway import AIExecutionError
from app.ai.models import AIFeatureConfig, AIProvider
from app.ai.schemas import FeatureWrite, PromptActivate, PromptWrite, ProviderCheck, ProviderWrite
from app.routers import ai_admin
from tests.test_ai_admin_write_authority import PROBES, snapshot


def provider_case(db, seed):
    actor = seed["super_admin_user"]
    provider = AIProvider(name="consistency-" + uuid.uuid4().hex, api_base="http://localhost:11434/v1", model="synthetic", enabled=1, allows_patient_data=1, created_by=actor.user_id)
    config = db.get(AIFeatureConfig, "patient_summary")
    if config is None:
        config = AIFeatureConfig(feature_key="patient_summary", updated_by=actor.user_id)
        db.add(config)
    db.add(provider)
    db.flush()
    config.provider_id = provider.provider_id
    config.enabled = 1
    config.validation_status = "validated"
    db.commit()
    # Load all the initial identities to reproduce a JWT transaction with
    # already populated objects, then retain them across an external update.
    actor.user_role, provider.name, config.revision
    return actor, provider, config


def raw_committed_change(db, statement, parameters):
    db.execute(text(statement), parameters)
    old = db.expire_on_commit
    db.expire_on_commit = False
    try:
        db.commit()
    finally:
        db.expire_on_commit = old


@pytest.mark.parametrize("column", ("enabled", "allows_patient_data"))
def test_feature_activation_uses_current_provider_permissions(db_session, seed_data, column):
    actor, provider, config = provider_case(db_session, seed_data)
    original = getattr(provider, column)
    raw_committed_change(db_session, f"UPDATE hoimsystem_ai_provider SET {column}=0 WHERE provider_id=:pk", {"pk": provider.provider_id})
    assert getattr(provider, column) == original == 1
    before = snapshot(db_session)
    req = FeatureWrite(expected_revision=config.revision, provider_id=provider.provider_id, enabled=True)
    try:
        with pytest.raises(HTTPException) as error:
            ai_admin.update_feature(config.feature_key, req, db_session, actor)
        assert error.value.status_code == 422
        assert snapshot(db_session) == before
    finally:
        db_session.rollback()


def test_cached_deleted_provider_cannot_be_selected(db_session, seed_data):
    actor, provider, config = provider_case(db_session, seed_data)
    provider_id, revision = provider.provider_id, config.revision
    # Detach this pre-existing config so deletion is valid with FK checks on.
    raw_committed_change(db_session, "UPDATE hoimsystem_ai_feature_config SET provider_id=NULL WHERE feature_key=:key", {"key": config.feature_key})
    raw_committed_change(db_session, "DELETE FROM hoimsystem_ai_provider WHERE provider_id=:pk", {"pk": provider_id})
    assert provider.provider_id == provider_id
    before = snapshot(db_session)
    try:
        with pytest.raises(HTTPException) as error:
            ai_admin.update_feature(config.feature_key, FeatureWrite(expected_revision=revision, provider_id=provider_id, enabled=False), db_session, actor)
        assert error.value.status_code == 404
        assert snapshot(db_session) == before
    finally:
        db_session.rollback()


@pytest.mark.parametrize("action", ("feature", "prompt_create", "prompt_activate", "provider"))
def test_locking_reads_do_not_accept_cached_stale_revisions(db_session, seed_data, action):
    actor, provider, config = provider_case(db_session, seed_data)
    if action == "provider":
        original = provider.revision
        raw_committed_change(db_session, "UPDATE hoimsystem_ai_provider SET revision=revision+1 WHERE provider_id=:pk", {"pk": provider.provider_id})
        req = ProviderWrite(name=provider.name, api_base=provider.api_base, model=provider.model, expected_revision=original)
        def invoke():
            return ai_admin.update_provider(provider.provider_id, req, db_session, actor)
        assert provider.revision == original
    else:
        original = config.revision
        raw_committed_change(db_session, "UPDATE hoimsystem_ai_feature_config SET revision=revision+1 WHERE feature_key=:key", {"key": config.feature_key})
        assert config.revision == original
        if action == "feature":
            def invoke():
                return ai_admin.update_feature(config.feature_key, FeatureWrite(expected_revision=original, daily_limit=89), db_session, actor)
        elif action == "prompt_create":
            req = PromptWrite(expected_revision=original, task_prompt="只整理已提供的资料，保留证据和不确定性，交由医生复核，不添加未提供的事实。" * 2, change_note="合成版本冲突测试")
            def invoke():
                return ai_admin.create_prompt(config.feature_key, req, db_session, actor)
        else:
            def invoke():
                return ai_admin.activate_prompt(config.feature_key, PromptActivate(expected_revision=original), db_session, actor)
    before = snapshot(db_session)
    try:
        with pytest.raises(HTTPException) as error:
            invoke()
        assert error.value.status_code == 409
        assert snapshot(db_session) == before
    finally:
        db_session.rollback()


def test_provider_invalidation_preserves_current_dependent_config_revision(db_session, seed_data):
    actor, provider, config = provider_case(db_session, seed_data)
    original = config.revision
    raw_committed_change(db_session, "UPDATE hoimsystem_ai_feature_config SET revision=revision+1,daily_limit=91 WHERE feature_key=:key", {"key": config.feature_key})
    assert config.revision == original
    req = ProviderWrite(name=provider.name, api_base=provider.api_base, model=provider.model, expected_revision=provider.revision)
    assert ai_admin.update_provider(provider.provider_id, req, db_session, actor)["code"] == 200
    db_session.refresh(config)
    assert config.revision == original + 2
    assert config.daily_limit == 91
    assert config.enabled == 0 and config.validation_status == "unreviewed"


def test_provider_write_locks_sorted_dependent_configs_before_provider(db_session, seed_data):
    actor, provider, config = provider_case(db_session, seed_data)
    req = ProviderWrite(name=provider.name, api_base=provider.api_base, model=provider.model, expected_revision=provider.revision)
    queries = []

    def observe(state):
        if state.is_select:
            queries.append(str(state.statement.compile(dialect=mysql.dialect())))

    event.listen(db_session, "do_orm_execute", observe)
    try:
        assert ai_admin.update_provider(provider.provider_id, req, db_session, actor)["code"] == 200
    finally:
        event.remove(db_session, "do_orm_execute", observe)
    config_locks = [index for index, sql in enumerate(queries) if "FROM hoimsystem_ai_feature_config" in sql and sql.rstrip().endswith("FOR UPDATE")]
    provider_locks = [index for index, sql in enumerate(queries) if "FROM hoimsystem_ai_provider" in sql and sql.rstrip().endswith("FOR UPDATE")]
    assert config_locks and provider_locks and max(config_locks) < min(provider_locks)
    assert all("ORDER BY hoimsystem_ai_feature_config.feature_key" in queries[index] for index in config_locks)


@pytest.mark.asyncio
@pytest.mark.parametrize("probe", PROBES, ids=lambda item: item[0])
@pytest.mark.parametrize("change", ("revision", "features"))
async def test_metadata_probe_checks_current_registration_before_network(db_session, seed_data, monkeypatch, probe, change):
    route, key, module, inspector = probe
    actor = seed_data["super_admin_user"]
    provider = AIProvider(name="probe-current-" + uuid.uuid4().hex, kind="specialist", api_base="http://localhost:11434/v1", model="synthetic", supported_features_json=json.dumps([key]), created_by=actor.user_id)
    db_session.add(provider)
    db_session.commit()
    provider_id, revision = provider.provider_id, provider.revision
    actor.user_role
    assignment = "revision=revision+1" if change == "revision" else "supported_features_json='[]'"
    raw_committed_change(db_session, f"UPDATE hoimsystem_ai_provider SET {assignment} WHERE provider_id=:pk", {"pk": provider_id})
    assert provider.revision == revision and json.loads(provider.supported_features_json) == [key]
    before = snapshot(db_session)
    calls = []

    async def inspect_provider(detached):
        calls.append(detached.provider_id)
        raise AIExecutionError("synthetic_probe_failure", "合成能力检测失败")

    name = f"inspect_{inspector}_capabilities"
    monkeypatch.setattr(importlib.import_module(f"app.ai.{module}_probe"), name, inspect_provider)
    if hasattr(ai_admin, name):
        monkeypatch.setattr(ai_admin, name, inspect_provider)
    with pytest.raises(HTTPException) as error:
        await getattr(ai_admin, f"check_{route}_provider")(provider_id, ProviderCheck(expected_revision=revision), db_session, actor)
    assert error.value.status_code == (409 if change == "revision" else 422)
    assert calls == []
    assert snapshot(db_session) == before
