"""Actual staged SQL, source-first reads, specific creation audit and rollback."""

import datetime as dt
import json

import pytest
from fastapi import HTTPException
from sqlalchemy import event, text, update

from app.ai import operations_support_cases as cases
from app.ai import operations_support_contract as c
from app.ai import operations_support_registry as registry
from app.ai import operations_support_releases as releases
from app.ai import operations_support_storage as storage
from app.ai.models import AIAuditEvent, AIFeatureConfig, AIPromptVersion, AIProvider, AIRun
from app.ai.operations_support_models import AIOperationsOriginal
from app.ai.operations_support_run_models import AIOperationsRunArtifact
from app.ai.operations_support_task_prompt import TASK_PROMPT
from app.models import User
from tests.test_ai_operations_support_configuration import actors as actors
from tests.test_ai_operations_support_configuration import configured as configured
from tests.test_ai_operations_support_configuration import source as source
from tests.test_ai_operations_support_registry import request
from tests.test_ai_operations_support_releases import proposal, review


def selection(configured):
    return {"operations_case_id": configured[3]["case_id"], "objective": "explain_observations"}


def stage(configured, *, who=None, preview=False):
    return storage.stage_run(configured[0][0], configured[0][-1] if who is None else who, selection(configured), preview=preview)


def no_body(db, callback, status, *, include_source=True):
    returned = []

    def capture(conn, cursor, statement, params, context, many):
        if statement.lstrip().lower().startswith("select"):
            returned.extend(column[0].lower() for column in cursor.description or [])

    event.listen(db.bind, "after_cursor_execute", capture)
    try:
        with pytest.raises(HTTPException) as exc:
            callback()
        assert exc.value.status_code == status
    finally:
        event.remove(db.bind, "after_cursor_execute", capture)
    names = ["input_json", "evidence_json", "context_metadata_json", "result_json", "source_json", "prompt_snapshot_json", "execution_snapshot_json"]
    if include_source:
        names.extend(["identity_json", "content_text", "draft_json", "review_basis", "published_review_json", "private_json", "public_json"])
    assert not any(column == name or column.endswith("_" + name) for name in names for column in returned), returned


def test_stage_actual_original_25_fields_full_frames_raw3_and_specific_audit_never_commits(configured):
    actors, original, release, case, provider, config = configured
    db, registrar, creator, reviewer, admin = actors
    counts = db.query(AIRun).count(), db.query(AIAuditEvent).count()
    identifier = stage(configured)
    run, artifact, source, private, prompt, execution, chosen = storage.load_artifact(db, admin, identifier, execution=True)
    assert run.status == "queued" and run.lease_token is None and run.patient_id is None and run.encounter_ref is None
    assert source.source_id == case["case_id"] and private.collection_id == case["case_id"]
    assert artifact.source_json == c.canonical_json(source) and artifact.source_projection_hash == case["public_hash"]
    assert prompt["task_prompt"] == TASK_PROMPT and prompt["prompt_id"] is None and artifact.prompt_version == 0
    assert all(len(getattr(run, key).encode()) < 65535 for key in storage.RAW_FIELDS)
    assert all(getattr(artifact, key) is None for key in ["claim_event_id", "dispatch_event_id", "usage_event_id"])
    event_row = db.get(AIAuditEvent, artifact.created_audit_event_id)
    receipt = json.loads(event_row.detail_json)
    assert event_row.action == storage.CREATION_ACTION and event_row.target == identifier
    assert set(receipt["original_run_header"]) == {column.name for column in AIRun.__table__.columns}
    assert len(receipt["original_run_header"]) == 25 and c.content_hash(receipt["original_run_header"]) == artifact.run_header_hash
    db.rollback()
    assert db.get(AIRun, identifier) is None and db.get(AIOperationsRunArtifact, identifier) is None
    assert (db.query(AIRun).count(), db.query(AIAuditEvent).count()) == counts


@pytest.mark.parametrize("microseconds", [0, 123456, 654321, 999999])
def test_new_artifact_utc6_and_explicit_legacy_seconds_are_both_exact(configured, monkeypatch, microseconds):
    clock = (cases.case_header(configured[0][0], configured[0][-1], configured[3]["case_id"])["assembled_at"] + dt.timedelta(seconds=1)).replace(microsecond=microseconds)
    monkeypatch.setattr(registry, "utcnow", lambda: clock)
    identifier = stage(configured)
    db = configured[0][0]
    artifact = db.get(AIOperationsRunArtifact, identifier)
    run = db.get(AIRun, identifier)
    audit = db.get(AIAuditEvent, artifact.created_audit_event_id)
    assert artifact.recorded_at == clock and run.create_time == audit.create_time == clock.replace(microsecond=0)
    assert json.loads(audit.detail_json)["artifact"]["recorded_at"] == registry.utc_text(clock)
    assert storage.load_artifact(db, configured[0][-1], identifier, execution=True)[1].recorded_at == clock


@pytest.mark.parametrize("fault", ["source_withdraw", "origin_role", "origin_epoch", "audit_pk", "artifact_owner", "run_feature", "run_context"])
def test_current_source_original_epoch_or_concrete_identity_precedes_all_body(configured, fault):
    actors, original, release, case, provider, config = configured
    db, registrar, creator, reviewer, admin = actors
    identifier = stage(configured)
    if fault == "source_withdraw":
        registry.revoke_original(db, registrar, original["original_id"], {"revision": 1, "reason": "原材料撤回"})
    elif fault == "origin_role":
        db.execute(update(User).where(User.user_id == admin.user_id).values(user_role="doctor").execution_options(synchronize_session=False))
    elif fault == "origin_epoch":
        db.execute(update(User).where(User.user_id == admin.user_id).values(token_invalid_before=registry.utcnow()).execution_options(synchronize_session=False))
    elif fault == "audit_pk":
        other = AIAuditEvent(actor_id=admin.user_id, action="different_action", target=identifier, detail_json="{}")
        db.add(other)
        db.flush()
        db.execute(update(AIOperationsRunArtifact).where(AIOperationsRunArtifact.run_id == identifier).values(created_audit_event_id=other.event_id).execution_options(synchronize_session=False))
    elif fault == "artifact_owner":
        db.execute(update(AIOperationsRunArtifact).where(AIOperationsRunArtifact.run_id == identifier).values(requested_by=registrar.user_id).execution_options(synchronize_session=False))
    elif fault == "run_feature":
        db.execute(update(AIRun).where(AIRun.run_id == identifier).values(feature_key="patient_summary").execution_options(synchronize_session=False))
    else:
        db.execute(update(AIRun).where(AIRun.run_id == identifier).values(context_digest="0" * 64).execution_options(synchronize_session=False))
    # Current Super has its own valid source authority but cannot resurrect the
    # original task creator's changed role/epoch or substitute a receipt.
    no_body(db, lambda: storage.load_artifact(db, registrar, identifier), 403 if fault in {"source_withdraw", "origin_role", "origin_epoch"} else 409)


def test_rehashed_prompt_body_cannot_replace_the_specific_original_create_receipt(configured):
    db = configured[0][0]
    identifier = stage(configured)
    artifact = db.get(AIOperationsRunArtifact, identifier)
    prompt = json.loads(artifact.prompt_snapshot_json)
    prompt["task_prompt"] = "篡改而重新计算SHA"
    digest = registry.raw_sha(prompt["system_prompt"] + "\n\n" + prompt["task_prompt"])
    prompt["instructions_digest"] = digest
    db.execute(
        update(AIOperationsRunArtifact)
        .where(AIOperationsRunArtifact.run_id == identifier)
        .values(prompt_snapshot_json=c.canonical_json(prompt), prompt_snapshot_hash=c.content_hash(prompt), instructions_digest=digest)
        .execution_options(synchronize_session=False)
    )
    no_body(db, lambda: storage.load_artifact(db, configured[0][-1], identifier), 409)


@pytest.mark.parametrize("field", list(storage.RAW_FIELDS))
def test_actual_raw3_bytes_cannot_be_reformatted_or_replaced(configured, field):
    db = configured[0][0]
    identifier = stage(configured)
    run = db.get(AIRun, identifier)
    value = getattr(run, field)
    db.execute(update(AIRun).where(AIRun.run_id == identifier).values(**{field: " " + value}).execution_options(synchronize_session=False))
    with pytest.raises(HTTPException) as exc:
        storage.load_artifact(db, configured[0][-1], identifier)
    assert exc.value.status_code == 409


def test_disabled_provider_stops_execution_before_body_but_authorized_frozen_read_is_retained(configured):
    actors, original, release, case, provider, config = configured
    db = actors[0]
    identifier = stage(configured)
    provider.enabled = 0
    db.flush()
    no_body(db, lambda: storage.load_artifact(db, actors[-1], identifier, execution=True), 409)
    assert storage.load_artifact(db, actors[-1], identifier)[0].run_id == identifier
    config.allowed_roles_json = '["doctor"]'
    db.flush()
    no_body(db, lambda: storage.load_artifact(db, actors[-1], identifier), 403)


@pytest.mark.parametrize("fault", ["provider_revision", "config_revision", "active_prompt"])
def test_current_prompt_or_provider_revision_change_stops_old_frozen_execution(configured, fault):
    db = configured[0][0]
    identifier = stage(configured)
    if fault == "provider_revision":
        configured[-2].revision += 1
    elif fault == "config_revision":
        configured[-1].revision += 1
    else:
        prompt = AIPromptVersion(feature_key="operations_support", version=1, task_prompt="实际新Prompt版本", change_note="合成更新", created_by=configured[0][1].user_id)
        db.add(prompt)
        db.flush()
        configured[-1].active_prompt_id = prompt.prompt_id
    db.flush()
    no_body(db, lambda: storage.load_artifact(db, configured[0][-1], identifier, execution=True), 409)
    assert storage.load_artifact(db, configured[0][-1], identifier)[1].provider_revision == 1


def test_super_preview_uses_actual_original_preview_and_keeps_all_source_authority(configured):
    actors, original, release, case, provider, config = configured
    db, registrar, creator, reviewer, admin = actors
    config.enabled = 0
    config.validation_status = "unreviewed"
    db.flush()
    identifier = stage(configured, who=registrar, preview=True)
    actual = storage.load_artifact(db, registrar, identifier, execution=True)
    assert actual[0].preview == 1 and actual[5]["preview"] is True
    registry.revoke_original(db, registrar, original["original_id"], {"revision": 1, "reason": "预览也不可恢复此原件"})
    no_body(db, lambda: storage.load_artifact(db, registrar, identifier, execution=True), 403)


def test_actual_current_daily_count_includes_staged_task_and_quota_failure_adds_nothing(configured):
    actors, original, release, case, provider, config = configured
    db = actors[0]
    clock = registry.utcnow()
    today = dt.datetime.combine(clock.date(), dt.time.min)
    used = db.query(AIRun).filter(AIRun.feature_key == "operations_support", AIRun.requested_by == actors[-1].user_id, AIRun.create_time >= today).count()
    config.daily_limit = used + 1
    db.flush()
    identifier = stage(configured)
    before = db.query(AIRun).count(), db.query(AIAuditEvent).count()
    with pytest.raises(HTTPException) as exc:
        stage(configured)
    assert exc.value.status_code == 429 and (db.query(AIRun).count(), db.query(AIAuditEvent).count()) == before
    assert db.get(AIOperationsRunArtifact, identifier).claim_event_id is None


def test_complete_large_source_is_stored_outside_legacy_raw3_without_clipping(configured):
    actors, original, release, case, provider, config = configured
    db, registrar, creator, reviewer, admin = actors
    body = "大😀\ufeff\r\n\x00  " * 5000 + "secret=合成令牌"
    original = registry.register_original(db, registrar, {**request(), "content_text": body})
    release = releases.create_release(db, creator, proposal(original, body))
    releases.review_release(db, reviewer, release["release_id"], review(model_processing_allowed=True))
    case = cases.create_case(db, admin, {"release_ids": [release["release_id"]]})
    identifier = storage.stage_run(db, admin, {"operations_case_id": case["case_id"], "objective": "explain_observations"})
    actual = storage.load_artifact(db, admin, identifier, execution=True)
    assert actual[1].source_bytes > 65535 and actual[2].documents[0].text == body.replace("secret=合成令牌", c.MASK_TEXT)
    assert all(len(getattr(actual[0], field).encode()) < 4096 for field in storage.RAW_FIELDS)


@pytest.mark.parametrize("fault", ["source", "origin_epoch", "config", "provider", "create_audit", "run_feature", "raw3"])
def test_real_post_artifact_insert_trigger_rejects_and_rolls_back_run_audit_artifact_and_source(configured, fault):
    actors, original, release, case, provider, config = configured
    db, registrar, creator, reviewer, admin = actors
    if fault == "source":
        command = "UPDATE hoimsystem_ai_operations_original SET content_text='changed' WHERE original_id='" + original["original_id"] + "';"
    elif fault == "origin_epoch":
        command = "UPDATE hoimsystem_users SET token_invalid_before='2026-10-23 00:00:00.123456' WHERE user_id=" + str(admin.user_id) + ";"
    elif fault == "config":
        command = "UPDATE hoimsystem_ai_feature_config SET revision=revision+1 WHERE feature_key='operations_support';"
    elif fault == "provider":
        command = "UPDATE hoimsystem_ai_provider SET revision=revision+1 WHERE provider_id=" + str(provider.provider_id) + ";"
    elif fault == "create_audit":
        command = "UPDATE hoimsystem_ai_audit_event SET action='different' WHERE event_id=NEW.created_audit_event_id;"
    elif fault == "run_feature":
        command = "UPDATE hoimsystem_ai_run SET feature_key='patient_summary' WHERE run_id=NEW.run_id;"
    else:
        command = "UPDATE hoimsystem_ai_run SET input_json='{}' WHERE run_id=NEW.run_id;"
    db.execute(text("CREATE TRIGGER ops_after_artifact AFTER INSERT ON hoimsystem_ai_operations_run_artifact BEGIN " + command + " END"))
    counts = db.query(AIRun).count(), db.query(AIAuditEvent).count(), db.query(AIOperationsRunArtifact).count()
    try:
        with pytest.raises(HTTPException), db.begin_nested():
            stage(configured)
        assert (db.query(AIRun).count(), db.query(AIAuditEvent).count(), db.query(AIOperationsRunArtifact).count()) == counts
        assert db.query(AIProvider.revision).filter_by(provider_id=provider.provider_id).scalar() == 1
        assert db.query(AIFeatureConfig.revision).filter_by(feature_key="operations_support").scalar() == 1
        assert db.query(User.token_invalid_before).filter_by(user_id=admin.user_id).scalar() is None
        assert db.query(AIOperationsOriginal.content_text).filter_by(original_id=original["original_id"]).scalar() == request()["content_text"]
    finally:
        # SQLite transactional DDL can restore a dropped trigger on the outer
        # fixture rollback. Persist explicit cleanup in this synthetic DB.
        db.rollback()
        db.execute(text("DROP TRIGGER IF EXISTS ops_after_artifact"))
        db.commit()
        assert db.execute(text("SELECT count(*) FROM sqlite_master WHERE type='trigger' AND name='ops_after_artifact'")).scalar_one() == 0


def test_backwards_clock_rejects_before_run_or_audit_insert(configured, monkeypatch):
    db = configured[0][0]
    header = cases.case_header(db, configured[0][-1], configured[3]["case_id"])
    monkeypatch.setattr(registry, "utcnow", lambda: header["assembled_at"] - dt.timedelta(microseconds=1))
    counts = db.query(AIRun).count(), db.query(AIAuditEvent).count()
    with pytest.raises(HTTPException) as exc:
        stage(configured)
    assert exc.value.status_code == 409 and (db.query(AIRun).count(), db.query(AIAuditEvent).count()) == counts


def test_actual_legal_case_can_exceed_nested_provider_wire_and_creates_no_task_or_receipt(configured):
    from app.ai.operations_support_gateway import OperationsCallError

    actors, original, release, case, provider, config = configured
    db, registrar, creator, reviewer, admin = actors
    body = "\\" * (2**21 - 1024)
    original = registry.register_original(db, registrar, {**request(), "content_text": body})
    release = releases.create_release(
        db,
        creator,
        dict(original_id=original["original_id"], original_full_sha256=original["content_hash"], released_title="完整合成字符预算资料", released_component=None, released_version=None, redactions=[]),
    )
    releases.review_release(db, reviewer, release["release_id"], review(model_processing_allowed=True))
    made = cases.create_case(db, admin, {"release_ids": [release["release_id"]]})
    source = cases.get_case_part(db, admin, made["case_id"], "source")
    private = cases.get_case_part(db, registrar, made["case_id"], "private")
    assert len(c.canonical_json(source).encode()) < c.MAX_WHOLE_BYTES and len(c.canonical_json(private).encode()) < c.MAX_WHOLE_BYTES
    before = db.query(AIRun).count(), db.query(AIOperationsRunArtifact).count(), db.query(AIAuditEvent).count()
    with pytest.raises(OperationsCallError) as exc:
        storage.stage_run(db, admin, {"operations_case_id": made["case_id"], "objective": "explain_observations"})
    assert exc.value.code == "OPERATIONS_REQUEST_LIMIT"
    assert (db.query(AIRun).count(), db.query(AIOperationsRunArtifact).count(), db.query(AIAuditEvent).count()) == before
