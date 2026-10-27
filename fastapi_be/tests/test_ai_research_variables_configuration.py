"""Actual current configuration SQL, independent of Source/task execution."""

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import event, text

from app.ai.catalog import FEATURE_BY_KEY
from app.ai.models import AIFeatureConfig, AIPromptVersion, AIProvider
from app.ai.research_variables_configuration import current_configuration
from app.ai.research_variables_prompt import SYSTEM_PROMPT
from app.ai.research_variables_task_contract import FEATURE_KEY, canonical


@pytest.fixture
def configured(db_session, seed_data):
    user = seed_data["super_admin_user"]
    provider = AIProvider(
        name="variable-config-" + uuid.uuid4().hex,
        kind="chat",
        api_base="http://localhost/v1",
        model="synthetic-no-call",
        enabled=1,
        allows_patient_data=1,
        created_by=user.user_id,
        revision=1,
    )
    db_session.add(provider)
    db_session.flush()
    row = db_session.get(AIFeatureConfig, FEATURE_KEY)
    if row is None:
        row = AIFeatureConfig(feature_key=FEATURE_KEY)
        db_session.add(row)
    row.enabled, row.provider_id, row.allowed_roles_json, row.validation_status = 1, provider.provider_id, canonical(["super_admin", "admin"]), "unreviewed"
    row.validation_note, row.validated_by, row.validated_at, row.active_prompt_id, row.updated_by, row.revision = "independent status not changed by preview", None, None, None, user.user_id, 1
    db_session.commit()
    return seed_data, row, provider


def test_actual_default_uses_entire_catalog_task_and_fixed_system_without_inventing_validation(db_session, configured):
    case, row, provider = configured
    value = current_configuration(db_session, case["admin_user"], preview=False)
    assert value.system_prompt == SYSTEM_PROMPT and value.task_prompt == FEATURE_BY_KEY[FEATURE_KEY].task_prompt
    assert value.prompt_origin.model_dump() == {"prompt_id": None, "prompt_version": 0}
    assert value.validation_snapshot.status == "unreviewed" and row.validation_status == "unreviewed"
    assert value.provider_snapshot.provider_id == provider.provider_id
    assert value.provider_snapshot.max_attempts == 3
    assert set(value.provider_snapshot.model_dump()) == {
        "provider_id",
        "revision",
        "name",
        "kind",
        "api_base",
        "model",
        "timeout_seconds",
        "max_attempts",
        "max_output_tokens",
        "validation_report",
        "temperature",
        "allows_patient_data",
        "effective_output_limit",
    }


def test_actual_uuid_custom_prompt_does_not_become_int_or_receive_validation_from_super_preview(db_session, configured):
    case, row, _ = configured
    prompt = AIPromptVersion(
        prompt_id=str(uuid.uuid4()), feature_key=FEATURE_KEY, version=7, task_prompt="\ufeff原样问题\r\n🧪e\u0301", change_note="synthetic", created_by=case["super_admin_user"].user_id
    )
    db_session.add(prompt)
    db_session.flush()
    row.active_prompt_id, row.enabled = prompt.prompt_id, 0
    db_session.commit()
    value = current_configuration(db_session, case["super_admin_user"], preview=True)
    assert value.task_prompt == prompt.task_prompt and value.prompt_origin.prompt_id == prompt.prompt_id and value.prompt_origin.prompt_version == 7
    assert value.validation_snapshot.status == "unreviewed" and row.enabled == 0
    for user, preview, status in ((case["super_admin_user"], False, 409), (case["admin_user"], True, 403)):
        with pytest.raises(HTTPException) as error:
            current_configuration(db_session, user, preview=preview)
        assert error.value.status_code == status


@pytest.mark.parametrize("axis", ["role", "epoch"])
def test_current_actor_recheck_saves_loaded_epoch_before_refresh_and_never_reads_prompt(db_session, configured, axis):
    case, _, _ = configured
    user = case["super_admin_user"]
    identifier, old_role, old_epoch = user.user_id, user.user_role, user.token_invalid_before
    field, value = ("user_role", "admin") if axis == "role" else ("token_invalid_before", "2099-01-01 00:00:00.000000")
    db_session.execute(text("UPDATE hoimsystem_users SET " + field + "=:value WHERE user_id=:id"), {"value": value, "id": identifier})
    assert user.__dict__["user_role"] == old_role and user.__dict__["token_invalid_before"] == old_epoch
    statements = []

    def seen(conn, cursor, sql, params, ctx, many):
        statements.append(sql)

    event.listen(db_session.bind, "before_cursor_execute", seen)
    try:
        with pytest.raises(HTTPException) as error:
            current_configuration(db_session, user, preview=True)
        assert error.value.status_code == 403
    finally:
        event.remove(db_session.bind, "before_cursor_execute", seen)
        db_session.rollback()
    assert not any("hoimsystem_ai_prompt_version.task_prompt" in sql for sql in statements)


@pytest.mark.parametrize("axis", ["pd", "kind", "disabled", "bad_roles", "bad_prompt_uuid", "foreign_prompt"])
def test_current_config_cannot_fall_back_to_another_model_prompt_or_role(db_session, configured, axis):
    case, row, provider = configured
    if axis == "pd":
        provider.allows_patient_data = 0
    elif axis == "kind":
        provider.kind = "specialist"
    elif axis == "disabled":
        provider.enabled = 0
    elif axis == "bad_roles":
        row.allowed_roles_json = '["super_admin","super_admin"]'
    elif axis == "bad_prompt_uuid":
        row.active_prompt_id = "77"
    else:
        prompt = AIPromptVersion(
            prompt_id=str(uuid.uuid4()), feature_key="clinical_training", version=99, task_prompt="not this task", change_note="synthetic", created_by=case["super_admin_user"].user_id
        )
        db_session.add(prompt)
        row.active_prompt_id = prompt.prompt_id
    db_session.commit()
    with pytest.raises(HTTPException) as error:
        current_configuration(db_session, case["super_admin_user"], preview=True)
    assert error.value.status_code == 409


def test_configured_role_does_not_expand_fixed_source_or_catalog_role(db_session, configured):
    case, row, _ = configured
    row.allowed_roles_json = canonical(["nurse", "doctor"])
    db_session.commit()
    for user in (case["nurse_user"], case["admin_user"]):
        with pytest.raises(HTTPException) as error:
            current_configuration(db_session, user, preview=False)
        assert error.value.status_code == 403


@pytest.mark.parametrize(
    "address", ["http://secret:credential@localhost/v1", "http://localhost/v1?key=not-a-real-key", "http://localhost/v1#not-an-endpoint", "https://unapproved-synthetic.invalid/v1"]
)
def test_current_saved_endpoint_still_requires_server_egress_policy_before_freezing_any_url(db_session, configured, address):
    case, _, provider = configured
    provider.api_base = address
    db_session.commit()
    with pytest.raises(HTTPException) as error:
        current_configuration(db_session, case["super_admin_user"], preview=True)
    assert error.value.status_code == 409
