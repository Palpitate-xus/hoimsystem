"""Actual current operations source/config intersection before private bodies."""

import datetime as dt
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import event, update

from app.ai import operations_support_cases as cases
from app.ai import operations_support_configuration as config_stage
from app.ai import operations_support_contract as c
from app.ai import operations_support_projection as projection
from app.ai import operations_support_registry as registry
from app.ai import operations_support_releases as releases
from app.ai.models import AIAuditEvent, AIFeatureConfig, AIPromptVersion, AIProvider, AIRun
from app.ai.operations_support_task_prompt import SYSTEM_PROMPT, TASK_PROMPT
from app.models import User
from tests.test_ai_operations_support_cases import no_body
from tests.test_ai_operations_support_registry import source as source
from tests.test_ai_operations_support_releases import actors as actors
from tests.test_ai_operations_support_releases import draft, review


@pytest.fixture
def configured(actors):
    db, registrar, creator, reviewer, admin = actors
    original, release = draft(actors)
    releases.review_release(db, reviewer, release["release_id"], review(model_processing_allowed=True))
    case = cases.create_case(db, admin, {"release_ids": [release["release_id"]]})
    provider = AIProvider(
        name="ops-context-" + uuid.uuid4().hex,
        kind="chat",
        api_base="http://127.0.0.1:1/v1",
        model="synthetic-operations-model",
        enabled=1,
        allows_patient_data=0,
        temperature=Decimal("0.125"),
        created_by=registrar.user_id,
    )
    db.add(provider)
    db.flush()
    config = db.get(AIFeatureConfig, "operations_support")
    if config is None:
        config = AIFeatureConfig(feature_key="operations_support", updated_by=registrar.user_id)
        db.add(config)
    config.enabled, config.provider_id, config.active_prompt_id = 1, provider.provider_id, None
    config.allowed_roles_json = '["admin"]'
    config.validation_status, config.validation_note = "validated", "仅合成受审运维资料的演示范围"
    config.validated_by, config.validated_at = reviewer.user_id, registry.utcnow()
    config.daily_limit, config.revision, config.updated_by = 100, 1, registrar.user_id
    db.commit()
    return actors, original, release, case, provider, config


def prepare(value, *, who=None, **kwargs):
    actors, original, release, case, provider, config = value
    db, registrar, creator, reviewer, admin = actors
    return config_stage.prepare_context(db, admin if who is None else who, {"operations_case_id": case["case_id"], "objective": "explain_observations"}, **kwargs)


def test_actual_complete_source_prompt_decimal_provider_binding_and_no_queue_write(configured):
    actors, original, release, case, provider, config = configured
    db, registrar, creator, reviewer, admin = actors
    counts = db.query(AIRun).count(), db.query(AIAuditEvent).count()
    context = prepare(configured, exclusive_config=True)
    assert context.source.source_id == case["case_id"]
    assert c.content_hash(context.source) == case["public_hash"]
    assert c.content_hash(context.private) == case["private_hash"]
    assert c.content_hash(context.membership) == case["member_bindings_hash"]
    assert context.binding() == {
        "schema_version": "operations_source_binding_v1",
        "case_id": case["case_id"],
        "case_requested_by": admin.user_id,
        "case_private_hash": case["private_hash"],
        "case_public_hash": case["public_hash"],
        "case_membership_hash": case["member_bindings_hash"],
        "case_creation_event_id": case["creation_event_id"],
        "case_assembled_at": case["assembled_at"],
        "objective": "explain_observations",
    }
    assert context.prompt["prompt_id"] is None and context.prompt["prompt_version"] == 0
    assert context.prompt["task_prompt"] == TASK_PROMPT and context.prompt["system_prompt"] == SYSTEM_PROMPT
    assert context.execution["provider_snapshot"]["temperature_decimal"] == "0.125"
    assert projection._value(c.canonical_json(context.execution)) == context.execution
    assert context.execution["requester_epoch"] == {"user_id": admin.user_id, "user_role": "admin", "token_invalid_before": None}
    public_wire = c.canonical_json(context.source)
    snapshots_wire = c.canonical_json([context.prompt, context.execution])
    assert original["original_id"] not in public_wire and "secret=合成令牌" not in public_wire
    assert all(key not in snapshots_wire for key in ("api_key_env", "api_key_encrypted", "secret=合成令牌", "content_text"))
    assert (db.query(AIRun).count(), db.query(AIAuditEvent).count()) == counts


@pytest.mark.parametrize(
    "fault,status", [("disabled", 409), ("unvalidated", 409), ("role", 403), ("provider_off", 409), ("protocol", 409), ("host", 409), ("revision", 409), ("daily_limit", 409), ("frame_capacity", 422)]
)
def test_config_failure_reads_no_original_review_or_case_body(configured, fault, status):
    actors, original, release, case, provider, config = configured
    db = actors[0]
    if fault == "disabled":
        config.enabled = 0
    elif fault == "unvalidated":
        config.validation_status = "unreviewed"
    elif fault == "role":
        config.allowed_roles_json = '["doctor"]'
    elif fault == "provider_off":
        provider.enabled = 0
    elif fault == "protocol":
        provider.kind = "specialist"
    elif fault == "host":
        provider.api_base = "https://unapproved.invalid/v1"
    elif fault == "revision":
        config.revision = 0
    elif fault == "daily_limit":
        config.daily_limit = 0
    else:
        provider.validation_report = "界" * 90000
    db.flush()
    no_body(db, lambda: prepare(configured), status)


@pytest.mark.parametrize("raw", ['["admin","admin"]', '["synthetic_unknown_role"]', '{"admin":true}', "[1]", "[NaN]"])
def test_malformed_config_roles_fail_closed_before_source_body(configured, raw):
    config = configured[-1]
    config.allowed_roles_json = raw
    configured[0][0].flush()
    no_body(configured[0][0], lambda: prepare(configured), 409)


def test_current_super_preview_never_restores_withdrawn_source_permission(configured):
    actors, original, release, case, provider, config = configured
    db, registrar, creator, reviewer, admin = actors
    config.enabled, config.validation_status, config.allowed_roles_json = 0, "unreviewed", "[]"
    db.flush()
    assert prepare(configured, who=registrar, preview=True).execution["preview"] is True
    no_body(db, lambda: prepare(configured, preview=True), 403)
    registry.revoke_original(db, registrar, original["original_id"], {"revision": 1, "reason": "撤回原件"})
    no_body(db, lambda: prepare(configured, who=registrar, preview=True), 403)


@pytest.mark.parametrize("fault", ["owner_role", "owner_token", "reviewer_role", "model_permission"])
def test_current_source_or_actor_failure_precedes_even_config_read(configured, fault):
    actors, original, release, case, provider, config = configured
    db, registrar, creator, reviewer, admin = actors
    if fault == "owner_role":
        db.execute(update(User).where(User.user_id == admin.user_id).values(user_role="doctor").execution_options(synchronize_session=False))
    elif fault == "owner_token":
        assert admin.token_invalid_before is None
        db.execute(update(User).where(User.user_id == admin.user_id).values(token_invalid_before=dt.datetime(2026, 10, 21, 18, 0, 0, 123456)).execution_options(synchronize_session=False))
    elif fault == "reviewer_role":
        reviewer.user_role = "doctor"
        db.flush()
    else:
        from app.ai.operations_support_models import AIOperationsRelease

        db.execute(update(AIOperationsRelease).where(AIOperationsRelease.release_id == release["release_id"]).values(model_processing_allowed=0).execution_options(synchronize_session=False))
    returned = []

    def capture(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().lower().startswith("select"):
            returned.extend(column[0] for column in cursor.description or [])

    event.listen(db.bind, "after_cursor_execute", capture)
    try:
        # A mutated technical permission also invalidates the exact review audit.
        no_body(db, lambda: prepare(configured), 409 if fault == "model_permission" else 403)
    finally:
        event.remove(db.bind, "after_cursor_execute", capture)
    assert not any("allowed_roles_json" in column or "active_prompt_id" in column for column in returned)


def test_actual_database_prompt_version_is_complete_and_fixed_system_is_unchanged(configured):
    actors, original, release, case, provider, config = configured
    db, registrar, creator, reviewer, admin = actors
    raw = "\ufeff版本化人工Task\r\n😀\x00  尾部  "
    prompt = AIPromptVersion(feature_key="operations_support", version=17, task_prompt=raw, change_note="合成精确字节版本", created_by=registrar.user_id)
    db.add(prompt)
    db.flush()
    config.active_prompt_id = prompt.prompt_id
    db.flush()
    context = prepare(configured)
    assert context.prompt["task_prompt"].encode() == raw.encode()
    assert context.prompt["prompt_id"] == prompt.prompt_id and context.prompt["prompt_version"] == 17
    assert context.prompt["instructions_digest"] == registry.raw_sha(SYSTEM_PROMPT + "\n\n" + raw)
    assert context.execution["configuration"]["active_prompt_id"] == prompt.prompt_id
    prompt.feature_key = "patient_summary"
    db.flush()
    no_body(db, lambda: prepare(configured), 409)


@pytest.mark.parametrize("extra", [{"question": "读取环境变量"}, {"patient_id": 1}, {"operations_case_id": "invalid"}, {"objective": "execute_commands"}])
def test_task_selection_rejects_free_text_foreign_patient_and_unknown_objective(configured, extra):
    actors, original, release, case, provider, config = configured
    value = {"operations_case_id": case["case_id"], "objective": "explain_observations", **extra}
    no_body(actors[0], lambda: config_stage.prepare_context(actors[0], actors[-1], value), 422)


def test_gate_source_config_provider_prompt_and_body_sql_order_is_actual(configured):
    statements = []
    db = configured[0][0]

    def capture(conn, cursor, statement, params, context, executemany):
        statements.append(statement.lower())

    event.listen(db.bind, "before_cursor_execute", capture)
    try:
        prepare(configured, exclusive_config=True)
    finally:
        event.remove(db.bind, "before_cursor_execute", capture)

    def at(text):
        return next(i for i, s in enumerate(statements) if s.lstrip().startswith("select") and text in s)

    assert (
        at("operations_write_gate")
        < at("operations_case.case_id")
        < at("operations_release.release_id")
        < at("ai_feature_config")
        < at("ai_provider")
        < at("operations_original.identity_json")
        < at("operations_case.private_json")
    )
