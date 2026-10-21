"""Actual synthetic SQL task anchors, leases, specific receipts and rollback.

No shared runtime dispatch or provider HTTP call is claimed by these tests.
"""

import datetime as dt
import hashlib
import json
import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import event, inspect, text
from sqlalchemy.exc import IntegrityError

from app.ai.catalog import CATALOG_VERSION, FEATURE_BY_KEY
from app.ai.context import context_metadata
from app.ai.models import AIAuditEvent, AIFeatureConfig, AIProvider, AIRun
from app.ai.runtime import provider_snapshot
from app.ai.satisfaction_artifact_models import AISatisfactionRunArtifact
from app.ai.satisfaction_context import satisfaction_context
from app.ai.satisfaction_draft import MAX_BYTES, canonical_json, source_hash
from app.ai.satisfaction_prompt import SATISFACTION_SYSTEM_PROMPT, SATISFACTION_TASK_PROMPT
from app.ai.satisfaction_result import result_for_draft
from app.ai.satisfaction_sources import revoke_case, utcnow
from app.ai.satisfaction_storage import RECEIPT_ACTION, authorize_run_scope, bounded_result, expand_result, is_satisfaction_run, load_snapshot, stage_anchor, stage_result
from app.models import Review, User
from tests.test_ai_satisfaction_sources import BASIS, published
from tests.test_ai_satisfaction_sources import satisfaction_case as satisfaction_case  # noqa: F401


def configured_run(db, case, *, kind="chat", themes=1, actor=None):
    actor = actor or case["admin_user"]
    made = published(db, case)
    provider = AIProvider(
        name="synthetic-satisfaction-" + str(uuid.uuid4()),
        kind=kind,
        api_base="http://synthetic-satisfaction.invalid/v1",
        model="synthetic-reviewed-theme-model",
        enabled=1,
        allows_patient_data=1,
        max_output_tokens=16000,
        temperature=0.2,
        supported_features_json=canonical_json(["feedback_analysis"]),
        validation_report="隔离合成工程验证，不代表真实医院部署、统计代表性或专业验证。",
        created_by=case["super_admin_user"].user_id,
    )
    db.add(provider)
    db.flush()
    config = db.get(AIFeatureConfig, "feedback_analysis")
    if config is None:
        config = AIFeatureConfig(feature_key="feedback_analysis", revision=1)
    else:
        config.revision += 1
    config.enabled = 1
    config.provider_id = provider.provider_id
    config.allowed_roles_json = canonical_json(list(FEATURE_BY_KEY["feedback_analysis"].default_roles))
    config.validation_status = "validated"
    config.validation_note = "仅隔离合成完整记录和逐字引文工程验证，不代表医院真实验证。"
    config.validated_by = case["super_admin_user"].user_id
    config.validated_at = utcnow()
    config.active_prompt_id = None
    config.updated_by = case["super_admin_user"].user_id
    db.add(config)
    db.commit()
    values = {"satisfaction_case_id": made["case_id"], "question": "请提出仍需人工核实的原摘录主题。"}
    bundle = satisfaction_context(db, actor, values)
    frozen_provider = provider_snapshot(provider)
    validation = {
        "status": config.validation_status,
        "note": config.validation_note,
        "validated_by": config.validated_by,
        "validated_at": str(config.validated_at),
        "feature_revision": config.revision,
    }
    snapshot = {
        "catalog_version": CATALOG_VERSION,
        "system_prompt": SATISFACTION_SYSTEM_PROMPT,
        "task_prompt": SATISFACTION_TASK_PROMPT,
        "payload": {"input": values, "context": bundle.data, "tools": {}, "evidence": bundle.evidence},
        "provider_snapshot": frozen_provider,
        "feature_validation": validation,
    }
    metadata = {
        **context_metadata(bundle),
        "feature_revision": config.revision,
        "validation_status": config.validation_status,
        "tool_fingerprint": source_hash({}),
        "instructions_digest": hashlib.sha256((SATISFACTION_SYSTEM_PROMPT + "\n\n" + SATISFACTION_TASK_PROMPT).encode()).hexdigest(),
        "model_version": provider.model,
    }
    run = AIRun(
        run_id=str(uuid.uuid4()),
        feature_key="feedback_analysis",
        provider_id=provider.provider_id,
        provider_revision=provider.revision,
        prompt_version=0,
        prompt_hash=source_hash([SATISFACTION_SYSTEM_PROMPT, SATISFACTION_TASK_PROMPT]),
        context_digest=source_hash(bundle.data),
        requested_by=actor.user_id,
        status="queued",
        preview=0,
        input_json=canonical_json(snapshot),
        evidence_json=canonical_json(bundle.evidence),
        context_metadata_json=canonical_json(metadata),
        result_json="{}",
    )
    db.add(run)
    db.flush()
    stage_anchor(db, run)
    db.commit()
    run.status, run.lease_token, run.start_time = "running", str(uuid.uuid4()), utcnow()
    db.commit()
    source = made["public_source"]
    excerpt = source["safe_snapshot"]["selected_excerpts"][0]
    draft = {
        "schema_version": "satisfaction_evidence_draft_v1",
        "satisfaction_source_id": source["source_id"],
        "safe_projection_hash": source["safe_projection_hash"],
        "coverage": "partial_themes_no_population_or_causality_claim",
        "themes": [
            {
                "title": f"合成候诊核对主题{i:03}",
                "observation": "这条人工摘录提及等候体验，主题解释需要人工核实。" * (60 if themes > 1 else 1),
                "clarification_question": "能否补充当次实际候诊顺序的可核实依据？" * (60 if themes > 1 else 1),
                "cited_excerpt_tokens": [excerpt["excerpt_token"]],
                "citations": [{"excerpt_token": excerpt["excerpt_token"], "text_hash": excerpt["text_hash"], "start": 0, "end": len(excerpt["text"]), "quote": excerpt["text"]}],
            }
            for i in range(themes)
        ],
    }
    result = result_for_draft(source, draft).model_dump(mode="json")
    return {**case, "made": made, "provider": provider, "config": config, "run": run, "bundle": bundle, "source": source, "result": result}


@pytest.fixture
def satisfaction_run(db_session, satisfaction_case):
    return configured_run(db_session, satisfaction_case)


def finish(db, case, result=None):
    run = case["run"]
    run.result_json = stage_result(db, run, run.lease_token, result or case["result"])
    run.status, run.finish_time = "succeeded", utcnow()
    db.commit()
    return json.loads(run.result_json)


def test_actual_anchor_then_large_complete_result_stores_short_reference_and_exact_specific_audit(db_session, satisfaction_case):
    db = db_session
    case = configured_run(db, satisfaction_case, themes=64)
    run = case["run"]
    assert len(run.input_json.encode()) < 65535 and "satisfaction_source" not in json.loads(run.input_json)["payload"]["context"]
    assert load_snapshot(db, run)[0]["payload"]["context"] == case["bundle"].data
    before_review = db.query(Review).count()
    reference = finish(db, case)
    artifact = db.query(AISatisfactionRunArtifact).filter_by(run_id=run.run_id).one()
    receipt = db.get(AIAuditEvent, reference["receipt_event_id"])
    assert len(run.result_json.encode()) < 1000
    assert 65535 < artifact.result_bytes == len(artifact.result_json.encode()) < MAX_BYTES
    assert source_hash(json.loads(artifact.result_json)) == artifact.result_hash == reference["content_hash"]
    assert receipt.event_id == artifact.receipt_event_id and receipt.action == RECEIPT_ACTION and receipt.target == run.run_id
    assert expand_result(db, run, user=case["admin_user"]) == case["result"]
    assert db.query(Review).count() == before_review
    assert case["review"].comment not in artifact.result_json and "identity_secret" not in artifact.result_json


def test_stage_anchor_and_result_never_commit_and_outer_rollback_removes_the_complete_tuple(db_session, satisfaction_run):
    db, case = db_session, satisfaction_run
    calls = []
    event.listen(db, "after_commit", lambda session: calls.append(True))
    ref = stage_result(db, case["run"], case["run"].lease_token, case["result"])
    assert json.loads(ref)["receipt_event_id"] > 0 and calls == []
    db.rollback()
    row = db.query(AISatisfactionRunArtifact).filter_by(run_id=case["run"].run_id).one()
    assert row.result_json is row.receipt_event_id is row.accepted_lease is row.accepted_at is None
    assert db.query(AIAuditEvent).filter_by(action=RECEIPT_ACTION, target=case["run"].run_id).count() == 0


@pytest.mark.parametrize("mutation", ["source", "role", "provider", "validation", "scope_role", "lease"])
def test_current_changes_before_acceptance_never_write_an_artifact_result(db_session, satisfaction_run, mutation):
    db, case = db_session, satisfaction_run
    run = case["run"]
    if mutation == "source":
        db.add(Review(doctor_id=case["doctor"].doctor_id, score=1, review_time=dt.datetime(2026, 10, 20)))
    elif mutation == "role":
        case["admin_user"].user_role = "patient"
    elif mutation == "provider":
        case["provider"].max_output_tokens = 2048
    elif mutation == "validation":
        case["config"].validation_note += "已改变"
    elif mutation == "scope_role":
        case["config"].allowed_roles_json = '["director"]'
    else:
        run.lease_token = str(uuid.uuid4())
    lease = run.lease_token if mutation != "lease" else str(uuid.uuid4())
    db.commit()
    with pytest.raises(HTTPException):
        stage_result(db, run, lease, case["result"])
    assert db.query(AISatisfactionRunArtifact).filter_by(run_id=run.run_id).one().result_json is None
    assert db.query(AIAuditEvent).filter_by(action=RECEIPT_ACTION, target=run.run_id).count() == 0


@pytest.mark.parametrize("mutation", ["source", "actor", "lease", "configuration", "provider", "audit_body", "artifact", "audit_abort"])
def test_actual_sql_postwrite_faults_rollback_source_actor_result_and_specific_receipt(db_session, satisfaction_run, mutation):
    db, case = db_session, satisfaction_run
    run = case["run"]
    rid, uid, provider_id = case["review"].review_id, case["admin_user"].user_id, case["provider"].provider_id
    original_comment = case["review"].comment
    if mutation == "audit_abort":
        sql = f"CREATE TRIGGER synthetic_satisfaction_fault BEFORE INSERT ON hoimsystem_ai_audit_event WHEN NEW.action='{RECEIPT_ACTION}' BEGIN SELECT RAISE(ABORT,'synthetic acceptance audit refusal'); END"
    elif mutation == "audit_body":
        sql = f"CREATE TRIGGER synthetic_satisfaction_fault AFTER INSERT ON hoimsystem_ai_audit_event WHEN NEW.action='{RECEIPT_ACTION}' BEGIN UPDATE hoimsystem_ai_audit_event SET detail_json='{{}}' WHERE event_id=NEW.event_id; END"
    else:
        body = {
            "source": f"UPDATE hoimsystem_review SET comment='synthetic same-transaction source changed' WHERE review_id={rid};",
            "actor": f"UPDATE hoimsystem_users SET user_role='patient' WHERE user_id={uid};",
            "lease": f"UPDATE hoimsystem_ai_run SET lease_token='{uuid.uuid4()}' WHERE run_id=NEW.run_id;",
            "configuration": "UPDATE hoimsystem_ai_feature_config SET validation_note='synthetic changed validation' WHERE feature_key='feedback_analysis';",
            "provider": f"UPDATE hoimsystem_ai_provider SET max_output_tokens=1024 WHERE provider_id={provider_id};",
            "artifact": "UPDATE hoimsystem_ai_satisfaction_run_artifact SET source_binding_hash='" + "f" * 64 + "' WHERE run_id=NEW.run_id;",
        }[mutation]
        sql = "CREATE TRIGGER synthetic_satisfaction_fault AFTER UPDATE OF result_json ON hoimsystem_ai_satisfaction_run_artifact WHEN NEW.result_json IS NOT NULL BEGIN " + body + " END"
    db.execute(text(sql))
    db.commit()
    lease = run.lease_token
    with pytest.raises((HTTPException, IntegrityError)):
        stage_result(db, run, lease, case["result"])
    db.rollback()
    artifact = db.query(AISatisfactionRunArtifact).filter_by(run_id=run.run_id).one()
    assert artifact.result_json is artifact.receipt_event_id is artifact.accepted_lease is artifact.accepted_at is None
    assert db.query(AIAuditEvent).filter_by(action=RECEIPT_ACTION, target=run.run_id).count() == 0
    assert db.get(Review, rid).comment == original_comment
    assert case["admin_user"].user_role == "admin" and run.lease_token == lease
    db.execute(text("DROP TRIGGER synthetic_satisfaction_fault"))
    db.commit()


@pytest.mark.parametrize("field", ["system_prompt", "provider_snapshot", "feature_validation", "context", "metadata", "evidence", "patient_id"])
def test_retained_task_cannot_be_changed_by_recomputing_only_its_local_hashes(db_session, satisfaction_run, field):
    db, case = db_session, satisfaction_run
    run = case["run"]
    snapshot = json.loads(run.input_json)
    if field == "system_prompt":
        snapshot["system_prompt"] = "forged unsupported System text"
    elif field == "provider_snapshot":
        del snapshot[field]["effective_output_limit"]
    elif field == "feature_validation":
        del snapshot[field]["validated_at"]
    elif field == "context":
        snapshot["payload"]["context"]["satisfaction_binding"]["safe_projection_hash"] = "f" * 64
    elif field == "metadata":
        value = json.loads(run.context_metadata_json)
        value["source_count"] = True
        run.context_metadata_json = canonical_json(value)
    elif field == "evidence":
        run.evidence_json = "[]"
    else:
        run.patient_id = case["patient"].patient_id
    run.input_json = canonical_json(snapshot)
    db.commit()
    with pytest.raises(HTTPException) as error:
        load_snapshot(db, run)
    assert error.value.status_code == 409


def test_result_all_hashes_and_specific_audit_recomputed_still_cannot_forge_server_summary(db_session, satisfaction_run):
    db, case = db_session, satisfaction_run
    reference = finish(db, case)
    run = case["run"]
    row = db.query(AISatisfactionRunArtifact).filter_by(run_id=run.run_id).one()
    value = json.loads(row.result_json)
    value["summary"] = "伪造全院总体满意结论，不能因重新计算哈希成为合法结果。"
    row.result_json, row.result_hash, row.result_bytes = bounded_result(value)
    reference.update(content_hash=row.result_hash, result_bytes=row.result_bytes)
    run.result_json = canonical_json(reference)
    audit = db.get(AIAuditEvent, row.receipt_event_id)
    detail = json.loads(audit.detail_json)
    detail.update(content_hash=row.result_hash, result_bytes=row.result_bytes)
    audit.detail_json = canonical_json(detail)
    db.commit()
    with pytest.raises(HTTPException) as error:
        expand_result(db, run)
    assert error.value.status_code == 409


def test_ordinary_result_rechecks_revocation_and_internal_frozen_read_remains_safe(db_session, satisfaction_run):
    db, case = db_session, satisfaction_run
    finish(db, case)
    revoke_case(db, case["super_admin_user"], case["made"]["case_id"], {"expected_revision": 2, "basis_note": BASIS})
    with pytest.raises(HTTPException) as error:
        expand_result(db, case["run"], user=case["admin_user"])
    assert error.value.status_code == 409
    assert expand_result(db, case["run"]) == case["result"]


def test_immutable_artifact_routing_survives_erased_markers_and_foreign_feature(db_session, satisfaction_run):
    db, case = db_session, satisfaction_run
    run = case["run"]
    run.feature_key, run.input_json, run.result_json = "nonexistent_legacy_feature", "{}", "{}"
    db.commit()
    assert is_satisfaction_run(db, run)
    with pytest.raises(HTTPException):
        load_snapshot(db, run)
    legacy = AIRun(feature_key="nursing_record", input_json="{}", result_json=None)
    assert inspect(legacy).transient and not is_satisfaction_run(db, legacy)


def test_exact_complete_result_byte_boundary_is_inclusive_and_never_truncated():
    value = {"text": "x" * (MAX_BYTES - len('{"text":""}'))}
    body, _, size = bounded_result(value)
    assert size == MAX_BYTES and json.loads(body) == value
    value["text"] += "x"
    with pytest.raises(HTTPException) as error:
        bounded_result(value)
    assert error.value.status_code == 422


def test_result_duplicate_or_different_lease_cannot_overwrite_the_original_acceptance(db_session, satisfaction_run):
    db, case = db_session, satisfaction_run
    run = case["run"]
    first = stage_result(db, run, run.lease_token, case["result"])
    db.commit()
    with pytest.raises(HTTPException):
        stage_result(db, run, run.lease_token, case["result"])
    assert json.loads(first)["receipt_event_id"] == db.query(AISatisfactionRunArtifact).filter_by(run_id=run.run_id).one().receipt_event_id
    assert db.query(AIAuditEvent).filter_by(action=RECEIPT_ACTION, target=run.run_id).count() == 1


def test_current_task_column_read_rejects_a_database_change_hidden_by_a_stale_orm_cache(db_session, satisfaction_run):
    db, case = db_session, satisfaction_run
    run = case["run"]
    original = run.input_json
    db.execute(text("UPDATE hoimsystem_ai_run SET input_json='{}' WHERE run_id=:id"), {"id": run.run_id})
    assert run.input_json == original  # Text SQL did not refresh the cached ORM body.
    with pytest.raises(HTTPException) as error:
        load_snapshot(db, run)
    assert error.value.status_code == 409
    db.rollback()


def test_current_result_header_cannot_be_replaced_with_an_old_cached_success_reference(db_session, satisfaction_run):
    db, case = db_session, satisfaction_run
    finish(db, case)
    run = case["run"]
    old = run.result_json
    db.execute(text("UPDATE hoimsystem_ai_run SET result_json='{}' WHERE run_id=:id"), {"id": run.run_id})
    assert run.result_json == old
    with pytest.raises(HTTPException) as error:
        expand_result(db, run)
    assert error.value.status_code == 409
    db.rollback()


def test_denied_current_role_never_selects_the_artifact_result_body(db_session, satisfaction_run):
    db, case = db_session, satisfaction_run
    finish(db, case)
    actor = case["admin_user"]
    actor.user_role = "patient"
    db.commit()
    db.expire_all()
    statements = []

    def record(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(db.get_bind(), "before_cursor_execute", record)
    try:
        with pytest.raises(HTTPException) as error:
            expand_result(db, case["run"], user=actor)
        assert error.value.status_code == 403
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", record)
    assert not any("hoimsystem_ai_satisfaction_run_artifact" in row for row in statements)


def test_foreign_current_doctor_scope_is_checked_before_protected_case_and_full_result_body(db_session, satisfaction_case):
    db, original = db_session, satisfaction_case
    case = configured_run(db, original, actor=original["director_user"])
    finish(db, case)
    case["doctor"].department_id = None
    db.commit()
    db.expire_all()
    statements = []

    def record(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(db.get_bind(), "before_cursor_execute", record)
    try:
        with pytest.raises(HTTPException) as error:
            expand_result(db, case["run"], user=case["director_user"])
        assert error.value.status_code == 403
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", record)
    assert not any("hoimsystem_ai_satisfaction_run_artifact.result_json" in row for row in statements)
    assert not any("hoimsystem_ai_satisfaction_case.snapshot_json" in row for row in statements)


def test_only_current_super_explicit_internal_audit_scope_can_thaw_revoked_source(db_session, satisfaction_run):
    db, case = db_session, satisfaction_run
    finish(db, case)
    revoke_case(db, case["super_admin_user"], case["made"]["case_id"], {"expected_revision": 2, "basis_note": BASIS})
    with pytest.raises(HTTPException) as error:
        authorize_run_scope(db, case["admin_user"], case["run"], audit_only=True)
    assert error.value.status_code == 403

    actor, expanded = authorize_run_scope(db, case["super_admin_user"], case["run"], audit_only=True)
    assert actor.user_role == "super_admin" and expanded["satisfaction_case"]["snapshot"] is None
    assert expanded["satisfaction_case"]["status"] == "revoked"
    actor.user_role = "admin"
    db.commit()
    with pytest.raises(HTTPException) as error:
        authorize_run_scope(db, actor, case["run"], audit_only=True)
    assert error.value.status_code == 403


def test_nonowner_admin_cannot_read_task_json_even_though_the_same_case_scope_is_operationally_readable(db_session, satisfaction_run):
    db, case = db_session, satisfaction_run
    finish(db, case)
    foreign = User(username="synthetic-foreign-satisfaction-owner-" + uuid.uuid4().hex, user_role="admin")
    db.add(foreign)
    db.commit()
    db.expire(case["run"])
    statements = []

    def record(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(db.get_bind(), "before_cursor_execute", record)
    try:
        with pytest.raises(HTTPException) as error:
            expand_result(db, case["run"], user=foreign)
        assert error.value.status_code == 403
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", record)
    assert not any("hoimsystem_ai_run.input_json" in row for row in statements)
    assert not any("hoimsystem_ai_satisfaction_run_artifact" in row for row in statements)


def test_current_configured_role_removal_blocks_historical_result_before_blob_read(db_session, satisfaction_run):
    db, case = db_session, satisfaction_run
    finish(db, case)
    case["config"].allowed_roles_json = '["director"]'
    db.commit()
    db.expire_all()
    statements = []

    def record(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(db.get_bind(), "before_cursor_execute", record)
    try:
        with pytest.raises(HTTPException) as error:
            expand_result(db, case["run"], user=case["admin_user"])
        assert error.value.status_code == 403
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", record)
    assert not any("hoimsystem_ai_satisfaction_run_artifact.result_json" in row for row in statements)


@pytest.mark.parametrize("malformed", ["{", '{"admin":true}', '["admin",1]'])
def test_current_super_frozen_audit_survives_malformed_live_roles_ordinary_fails_before_blob(db_session, satisfaction_run, malformed):
    db, case = db_session, satisfaction_run
    finish(db, case)
    case["config"].allowed_roles_json = malformed
    db.commit()
    statements = []

    def seen(conn, cursor, statement, parameters, context, many):
        statements.append(statement)

    event.listen(db.bind, "before_cursor_execute", seen)
    try:
        with pytest.raises(HTTPException) as error:
            expand_result(db, case["run"], user=case["admin_user"])
        assert error.value.status_code == 409
    finally:
        event.remove(db.bind, "before_cursor_execute", seen)
    assert not any("satisfaction_run_artifact" in sql.lower() for sql in statements)
    db.rollback()
    revoke_case(db, case["super_admin_user"], case["made"]["case_id"], {"expected_revision": 2, "basis_note": BASIS})
    actor, expanded = authorize_run_scope(db, case["super_admin_user"], case["run"], audit_only=True)
    assert actor.user_role == "super_admin" and expanded["satisfaction_case"]["status"] == "revoked"
    assert expand_result(db, case["run"]) == case["result"]


def test_malformed_live_roles_still_rejects_new_result_acceptance_with_no_blob_or_receipt(db_session, satisfaction_run):
    db, case = db_session, satisfaction_run
    case["config"].allowed_roles_json = "{"
    db.commit()
    with pytest.raises(HTTPException) as error:
        stage_result(db, case["run"], case["run"].lease_token, case["result"])
    assert error.value.status_code == 409
    assert db.get(AISatisfactionRunArtifact, case["run"].run_id).result_json is None
    assert db.query(AIAuditEvent).filter_by(action=RECEIPT_ACTION, target=case["run"].run_id).count() == 0
