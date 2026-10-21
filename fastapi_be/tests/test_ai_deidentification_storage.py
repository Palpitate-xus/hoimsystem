"""Actual synthetic current research authority before private task bodies."""

import copy
import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import event

from app.ai import deidentification_sources as sources
from app.ai import deidentification_storage as storage
from app.ai.deidentification_spans import canonical, digest
from app.ai.deidentification_task_access import is_deidentification_run, opaque_locator, safe_task_metadata
from app.ai.models import AIAuditEvent, AIFeatureConfig, AIPromptVersion, AIProvider, AIRun
from app.ai.research_cohort_registry import review_registry_original
from tests.test_ai_deidentification_reviews import published_source
from tests.test_ai_deidentification_sources import deid_case as source_fixture
from tests.test_ai_research_cohort_contract import BASIS
from tests.test_ai_research_cohort_sources import research_case as research_case  # noqa: F401


@pytest.fixture
def task_case(db_session, research_case):
    db = db_session
    research_case["scope_request"]["external_model_use"] = "recorded_permitted"
    values = source_fixture.__wrapped__(db, research_case)
    source = published_source(db, values)
    provider = AIProvider(
        name="deid-task-" + source["case_id"],
        api_base="http://localhost:11434/v1",
        kind="chat",
        model="synthetic75",
        enabled=1,
        allows_patient_data=1,
        created_by=values[0]["super_admin_user"].user_id,
    )
    db.add(provider)
    db.flush()
    config = db.get(AIFeatureConfig, "deidentification")
    if config is not None:
        db.delete(config)
        db.flush()
    config = AIFeatureConfig(
        feature_key="deidentification",
        provider_id=provider.provider_id,
        enabled=1,
        allowed_roles_json=canonical(sorted(sources.SOURCE_ROLES)),
        validation_status="pilot",
        validation_note="仅合成工程配置，不作匿名认证",
        revision=1,
        updated_by=values[0]["super_admin_user"].user_id,
    )
    db.add(config)
    db.commit()
    return {
        "db": db,
        "values": values,
        "users": values[0],
        "actor": values[0]["admin_user"],
        "source": source,
        "provider": provider,
        "config": config,
        "input": {"deidentification_case_id": source["case_id"], "question": "\u3000"},
    }


def staged(case):
    db = case["db"]
    actor, _, provider, body, task, _, _, raw = storage.prepare(db, case["actor"], case["input"])
    run = AIRun(
        feature_key="deidentification",
        requested_by=actor.user_id,
        provider_id=provider.provider_id,
        provider_revision=provider.revision,
        patient_id=case["values"][0]["patient"].patient_id,
        encounter_ref=None,
        prompt_version=body["prompt"]["version"],
        prompt_hash=body["prompt"]["prompt_hash"],
        context_digest=digest(task["context"]),
        status="queued",
        preview=0,
        **raw,
    )
    db.add(run)
    db.flush()
    audit = AIAuditEvent(actor_id=actor.user_id, action="deidentification.task.create", target=run.run_id, detail_json=canonical(storage.create_detail(run, body)))
    db.add(audit)
    db.flush()
    artifact = storage.stage_source(db, run, body, audit.event_id)
    return run, artifact, body


def body_sql(statements):
    return [
        sql
        for sql in statements
        if sql.lstrip().upper().startswith("SELECT")
        and any(
            field in sql
            for field in (
                "hoimsystem_ai_run.input_json",
                "hoimsystem_ai_run.evidence_json",
                "hoimsystem_ai_run.context_metadata_json",
                "hoimsystem_ai_deidentification_run_source.source_json",
                "hoimsystem_ai_deidentification_run_result.result_json",
            )
        )
    ]


def test_actual_uncommitted_opaque_fk_and_full_source_task_prompt_proof(task_case):
    case, db = task_case, task_case["db"]
    run, artifact, body = staged(case)
    assert opaque_locator(db, run.run_id)["case_id"] == case["source"]["case_id"]
    assert is_deidentification_run(db, run)
    checked = storage.load_snapshot(db, case["actor"], run.run_id, execution=True)
    assert checked[3] == body and checked[4]["input"]["question"] == "\u3000"
    assert json.loads(run.input_json)["prompt"]["version"] == 0 and artifact.prompt_version_id is None
    assert "张三" not in run.input_json + run.evidence_json + run.context_metadata_json
    assert body["public_source"]["documents"][0]["text"].startswith("\ufeff张三\r\n😀")
    assert storage.load_result(db, case["actor"], run.run_id)[1] is None


@pytest.mark.parametrize("audit_only", [False, True])
def test_patient_authority_withdrawal_denies_even_super_before_any_task_text(task_case, audit_only):
    case, db = task_case, task_case["db"]
    run, _, _ = staged(case)
    db.commit()
    identifier = run.run_id
    auth = case["values"][3]
    review_registry_original(db, case["users"]["super_admin_user"], "authorization", auth["source_record_id"], {"expected_revision": 2, "basis_note": BASIS}, revoke=True)
    statements = []

    def observe(conn, cursor, sql, args, context, many):
        statements.append(sql)

    event.listen(db.bind, "before_cursor_execute", observe)
    try:
        with pytest.raises(HTTPException):
            storage.load_snapshot(db, case["users"]["super_admin_user"] if audit_only else case["actor"], identifier, audit_only=audit_only)
    finally:
        event.remove(db.bind, "before_cursor_execute", observe)
    assert body_sql(statements) == []
    assert safe_task_metadata(db, case["users"]["super_admin_user"], identifier)["source"] is None


@pytest.mark.parametrize("change", ["roles_removed", "roles_broken", "role", "epoch"])
def test_current_role_and_token_gate_and_frozen_execution_epoch(task_case, change):
    import datetime as dt

    case, db = task_case, task_case["db"]
    run, _, _ = staged(case)
    db.commit()
    identifier = run.run_id
    if change == "roles_removed":
        case["config"].allowed_roles_json = '["super_admin"]'
    elif change == "roles_broken":
        case["config"].allowed_roles_json = "{}"
    elif change == "role":
        case["actor"].user_role = "doctor"  # Still in fixed/configured role set.
    else:
        case["actor"].token_invalid_before = dt.datetime.now(dt.UTC).replace(tzinfo=None)
    db.commit()
    statements = []

    def observe(conn, cursor, sql, args, context, many):
        statements.append(sql)

    event.listen(db.bind, "before_cursor_execute", observe)
    try:
        with pytest.raises(HTTPException):
            storage.load_snapshot(db, SimpleNamespace(user_id=case["actor"].user_id), identifier, execution=True)
    finally:
        event.remove(db.bind, "before_cursor_execute", observe)
    if change.startswith("roles_"):
        assert body_sql(statements) == []


def test_source_revocation_current_denial_and_authorized_super_frozen_are_distinct(task_case):
    case, db = task_case, task_case["db"]
    run, _, body = staged(case)
    db.commit()
    sources.review_case(
        db, case["users"]["super_admin_user"], case["source"]["case_id"], {"expected_revision": 2, "expected_content_hash": case["source"]["content_hash"], "basis_note": BASIS}, revoke=True
    )
    with pytest.raises(HTTPException):
        storage.load_snapshot(db, case["actor"], run.run_id)
    frozen = storage.load_snapshot(db, case["users"]["super_admin_user"], run.run_id, audit_only=True)
    assert frozen[3] == body
    with pytest.raises(HTTPException):
        storage.load_snapshot(db, case["users"]["super_admin_user"], run.run_id, audit_only=True, execution=True)


def test_erased_all_run_markers_still_current_artifact_classified_and_expired_run_reads_no_text(task_case):
    case, db = task_case, task_case["db"]
    run, _, _ = staged(case)
    run.feature_key, run.input_json, run.result_json, run.evidence_json, run.context_metadata_json = "generic_legacy", "{}", "{}", "[]", "{}"
    db.commit()
    db.expire(run)
    statements = []

    def observe(conn, cursor, sql, args, context, many):
        statements.append(sql)

    event.listen(db.bind, "before_cursor_execute", observe)
    try:
        assert is_deidentification_run(db, run)
    finally:
        event.remove(db.bind, "before_cursor_execute", observe)
    assert body_sql(statements) == []
    with pytest.raises(HTTPException):
        storage.load_snapshot(db, case["actor"], run)
    assert not is_deidentification_run(db, SimpleNamespace(run_id="legacy-nonuuid", feature_key="generic"))


@pytest.mark.parametrize("field", ["input_json", "evidence_json", "context_metadata_json", "provider", "validation", "publication"])
def test_complete_task_missing_or_self_rehashed_body_does_not_pass(task_case, field):
    case, db = task_case, task_case["db"]
    run, artifact, body = staged(case)
    if field.endswith("json"):
        setattr(run, field, "{}")
    else:
        changed = copy.deepcopy(body)
        changed[field].pop(next(iter(changed[field])))
        artifact.source_json = canonical(changed)
        artifact.source_hash = storage.text_digest(artifact.source_json)
        artifact.source_bytes = len(artifact.source_json.encode())
    db.flush()
    with pytest.raises(HTTPException):
        storage.load_snapshot(db, case["actor"], run.run_id)


def test_real_saved_prompt_fk_full_record_is_rechecked_without_requiring_saved_prompt_for_version_zero(task_case):
    import uuid

    from app.ai.deidentification_prompt import TASK_PROMPT

    case, db = task_case, task_case["db"]
    prompt = AIPromptVersion(
        prompt_id=str(uuid.uuid4()),
        feature_key="deidentification",
        version=1,
        task_prompt="明确保存的完整合成任务\n\n" + TASK_PROMPT,
        change_note="仅工程版本快照",
        created_by=case["users"]["super_admin_user"].user_id,
    )
    db.add(prompt)
    db.flush()
    case["config"].active_prompt_id = prompt.prompt_id
    db.commit()
    run, artifact, _ = staged(case)
    assert artifact.prompt_version_id == prompt.prompt_id and artifact.prompt_version == 1
    assert storage.load_snapshot(db, case["actor"], run.run_id, execution=True)[3]["prompt"]["database_snapshot"]["task_prompt"] == prompt.task_prompt
    # An original saved version is immutable by service contract. Direct SQL
    # drift cannot hide behind the still-valid FK or its frozen body's own SHA.
    prompt.task_prompt += "被直接篡改的同版本原行"
    db.flush()
    with pytest.raises(HTTPException):
        storage.load_snapshot(db, case["users"]["super_admin_user"], run.run_id, audit_only=True)
