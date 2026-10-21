"""Actual SQL Artifact closure; no worker/network/real MySQL claim."""

import copy
import json
import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import event, text

from app.ai import document_change_contract as c
from app.ai import document_change_sources as sources
from app.ai import document_change_storage as storage
from app.ai import document_evidence_sources as originals
from app.ai.catalog import CATALOG_VERSION
from app.ai.context import context_metadata
from app.ai.document_change_context import prepare_context
from app.ai.document_change_draft import SYSTEM_PROMPT, TASK_PROMPT
from app.ai.document_change_run_models import AIDocumentChangeRunArtifact, AIDocumentChangeRunResult
from app.ai.models import AIAuditEvent, AIFeatureConfig, AIPromptVersion, AIProvider, AIRun
from app.models import User
from tests.test_ai_document_change_sources import change_case as change_case  # noqa: F401
from tests.test_ai_document_change_sources import link_request, published_scope
from tests.test_ai_document_evidence_contract import NOTE, NOW
from tests.test_ai_document_evidence_sources import cas


@pytest.fixture(autouse=True)
def remove_prior_tasks(db_session):
    db_session.query(AIDocumentChangeRunResult).delete(synchronize_session=False)
    db_session.query(AIDocumentChangeRunArtifact).delete(synchronize_session=False)
    db_session.query(AIRun).filter_by(feature_key=storage.FEATURE_KEY).delete(synchronize_session=False)
    db_session.query(AIFeatureConfig).filter_by(feature_key=storage.FEATURE_KEY).delete(synchronize_session=False)
    db_session.query(AIPromptVersion).filter_by(feature_key=storage.FEATURE_KEY).delete(synchronize_session=False)
    db_session.commit()


def task(case, *, stage=True, kind="chat"):
    db, actor, *_ = case
    scope = published_scope(case)
    values = {"document_change_scope_id": scope.snapshot.scope_id, "question": "\ufeff原样问题\r\n😀e\u0301"}
    bundle, record, source = prepare_context(db, actor, values)
    provider = AIProvider(
        name="change storage " + str(uuid.uuid4()),
        kind=kind,
        api_base="https://synthetic.invalid/v1",
        model="synthetic-version-question-model",
        enabled=1,
        allows_patient_data=1,
        max_output_tokens=2000,
        temperature=0.0,
        created_by=actor.user_id,
        validation_report=NOTE,
    )
    prompt = AIPromptVersion(feature_key=storage.FEATURE_KEY, version=1, task_prompt=TASK_PROMPT, change_note=NOTE, created_by=actor.user_id)
    db.add_all([provider, prompt])
    db.flush()
    provider_snapshot = {
        "provider_id": provider.provider_id,
        "revision": provider.revision,
        "name": provider.name,
        "kind": kind,
        "api_base": provider.api_base,
        "model": provider.model,
        "timeout_seconds": provider.timeout_seconds,
        "max_output_tokens": provider.max_output_tokens,
        "temperature": 0.0,
        "validation_report": NOTE,
        "allows_patient_data": True,
        "effective_output_limit": 2000,
    }
    validation = {"feature_revision": 3, "status": "pilot", "note": NOTE, "validated_by": actor.user_id, "validated_at": str(c.e.clock(NOW))}
    db.add(
        AIFeatureConfig(
            feature_key=storage.FEATURE_KEY,
            enabled=1,
            provider_id=provider.provider_id,
            allowed_roles_json='["super_admin"]',
            validation_status="pilot",
            validation_note=NOTE,
            validated_by=actor.user_id,
            validated_at=c.e.clock(NOW),
            active_prompt_id=prompt.prompt_id,
            updated_by=actor.user_id,
            revision=3,
        )
    )
    db.commit()
    metadata = {
        **context_metadata(bundle),
        "feature_revision": 3,
        "validation_status": "pilot",
        "tool_fingerprint": c.e.digest({}),
        "instructions_digest": c.e.bytes_hash(SYSTEM_PROMPT + "\n\n" + TASK_PROMPT),
        "model_version": provider.model,
    }
    snapshot = {
        "catalog_version": CATALOG_VERSION,
        "system_prompt": SYSTEM_PROMPT,
        "task_prompt": TASK_PROMPT,
        "payload": {"input": values, "context": bundle.data, "tools": {}, "evidence": bundle.evidence},
        "provider_snapshot": provider_snapshot,
        "feature_validation": validation,
    }
    run = AIRun(
        run_id=str(uuid.uuid4()),
        feature_key=storage.FEATURE_KEY,
        provider_id=provider.provider_id,
        provider_revision=provider.revision,
        prompt_version=1,
        prompt_hash=c.e.digest([SYSTEM_PROMPT, TASK_PROMPT]),
        context_digest=c.e.digest(bundle.data),
        requested_by=actor.user_id,
        status="queued",
        preview=1,
        input_json=c.e.canonical_json(snapshot),
        evidence_json=c.e.canonical_json(bundle.evidence),
        context_metadata_json=c.e.canonical_json(metadata),
        create_time=c.e.clock(NOW),
    )
    db.add(run)
    db.flush()
    if stage:
        storage.stage_artifact(db, actor, run)
        db.commit()
    return {"run": run, "scope": scope, "source": source, "context": bundle.data, "metadata": metadata, "snapshot": snapshot, "record": record, "provider": provider}


@pytest.mark.parametrize("kind", ["chat", "responses"])
def test_actual_artifact_short_run_raw_anchor_and_all_split_packets(change_case, kind):
    db, actor, *_ = change_case
    case = task(change_case, kind=kind)
    run = case["run"]
    loaded = storage.load_snapshot(db, run, user=actor)
    snapshot, metadata, evidence, bound, row, source = loaded
    assert source == case["source"] and metadata == case["metadata"] and evidence == snapshot["payload"]["evidence"]
    assert row.source_digest == c.e.bytes_hash(row.source_json) and row.source_bytes == len(c.e.utf8(row.source_json))
    assert row.usage_event_id is None and run.result_json == "{}"
    assert row.input_hash == c.e.bytes_hash(run.input_json)
    assert source.baseline.text not in run.input_json
    assert storage.artifact_record(db, actor, run).usage_event_id is None
    assert storage.expanded_source(db, actor, run).document_change_source == source
    private = storage.expanded_private_scope(db, actor, run)
    assert private.scope_snapshot == case["scope"].snapshot and private.currentness == "not_asserted_by_frozen_packet"
    assert private.document_change_binding == bound
    assert storage.is_document_change_run(db, run)


@pytest.mark.parametrize("change", ["question", "prompt", "provider", "validation", "evidence", "metadata", "prompt_version", "preview"])
def test_rehashed_short_json_cannot_replace_independent_sql_anchors(change_case, change):
    db, actor, *_ = change_case
    case = task(change_case)
    run = case["run"]
    snapshot, metadata = copy.deepcopy(case["snapshot"]), copy.deepcopy(case["metadata"])
    if change == "question":
        snapshot["payload"]["input"]["question"] += "forged"
    elif change == "prompt":
        snapshot["task_prompt"] += "forged"
        run.prompt_hash = c.e.digest([SYSTEM_PROMPT, snapshot["task_prompt"]])
        metadata["instructions_digest"] = c.e.bytes_hash(SYSTEM_PROMPT + "\n\n" + snapshot["task_prompt"])
    elif change == "provider":
        snapshot["provider_snapshot"]["model"] += "changed"
        metadata["model_version"] = snapshot["provider_snapshot"]["model"]
    elif change == "validation":
        snapshot["feature_validation"]["note"] += "changed"
    elif change == "prompt_version":
        run.prompt_version += 1
    elif change == "preview":
        run.preview = 0
    elif change == "evidence":
        snapshot["payload"]["evidence"][0]["inventory_hash"] = "a" * 64
        run.evidence_json = c.e.canonical_json(snapshot["payload"]["evidence"])
    else:
        metadata["source_count"] = True
    run.input_json = c.e.canonical_json(snapshot)
    run.context_metadata_json = c.e.canonical_json(metadata)
    db.commit()
    with pytest.raises(HTTPException) as error:
        storage.load_snapshot(db, run, user=actor)
    assert error.value.status_code == 409


@pytest.mark.parametrize("field", ["source_json", "source_bytes", "source_digest", "scope_governance_json", "input_hash", "created_audit_event_id"])
def test_actual_sql_artifact_tamper_rejected(change_case, field):
    db, actor, *_ = change_case
    case = task(change_case)
    run = case["run"]
    row = db.get(AIDocumentChangeRunArtifact, run.run_id)
    if field == "source_json":
        value = json.loads(row.source_json)
        value["relationship_kind"] = "declared_successor"
        row.source_json = c.e.canonical_json(value)
        row.source_bytes = len(c.e.utf8(row.source_json))
    elif field == "source_bytes":
        row.source_bytes += 1
    elif field == "created_audit_event_id":
        row.created_audit_event_id = row.scope_created_audit_event_id
    elif field == "scope_governance_json":
        value = json.loads(row.scope_governance_json)
        value["review_basis_note"] += "changed"
        row.scope_governance_json = c.e.canonical_json(value)
    else:
        setattr(row, field, "f" * 64)
    db.commit()
    with pytest.raises(HTTPException) as error:
        storage.load_snapshot(db, run, user=actor)
    assert error.value.status_code == 409


@pytest.mark.parametrize("change", ["target", "losing_link", "scope", "original"])
def test_current_invalidates_but_super_explicit_frozen_packets_retain_full_original(change_case, change):
    db, actor, first, *_ = change_case
    case = task(change_case)
    run, prior = case["run"], case["source"]
    if change == "target":
        change_case[4].steps = "legitimate current changed target"
        change_case[4].source_revision += 1
    elif change == "losing_link":
        sources.create_link(db, actor, link_request(change_case))
    elif change == "scope":
        sources.revoke_scope(db, actor, case["scope"].snapshot.scope_id, {**cas(case["scope"]), "basis_note": NOTE})
    else:
        originals.revoke_original(db, actor, first.snapshot.original_id, {**cas(first), "basis_note": NOTE})
    db.commit()
    with pytest.raises(HTTPException):
        storage.authorize_run(db, actor, run, current=True)
    assert storage.expanded_source(db, actor, run, current=False).document_change_source == prior
    assert storage.expanded_private_scope(db, actor, run, current=False).published_governance.status == "published"


def test_role_loss_rejects_even_frozen_read_but_another_current_super_can_audit(change_case):
    db, actor, *_ = change_case
    case = task(change_case)
    actor.user_role = "admin"
    db.commit()
    with pytest.raises(HTTPException) as error:
        storage.load_snapshot(db, case["run"], user=actor, current=False)
    assert error.value.status_code == 403
    auditor = User(username="separate-current-super", password="unused", user_role="super_admin")
    db.add(auditor)
    db.commit()
    assert storage.expanded_source(db, auditor, case["run"], current=False).document_change_source == case["source"]


def test_actual_audit_insert_failure_rolls_back_run_artifact_and_audit(change_case):
    db, actor, *_ = change_case
    case = task(change_case, stage=False)
    identifier = case["run"].run_id
    before = db.query(AIAuditEvent).count()
    db.execute(
        text(
            "CREATE TRIGGER reject_change_artifact_audit BEFORE INSERT ON hoimsystem_ai_audit_event WHEN NEW.action='document_change.run_artifact_created' BEGIN SELECT RAISE(ABORT,'actual synthetic audit rejection'); END"
        )
    )
    with pytest.raises(HTTPException):
        storage.stage_artifact(db, actor, case["run"])
    assert db.get(AIRun, identifier) is None
    assert db.query(AIDocumentChangeRunArtifact).count() == 0 and db.query(AIAuditEvent).count() == before
    db.execute(text("DROP TRIGGER IF EXISTS reject_change_artifact_audit"))
    db.commit()


def test_durable_dispatch_never_takes_artifact_or_original_locks(change_case):
    db, actor, *_ = change_case
    case = task(change_case)
    run = case["run"]
    run.feature_key = "patient_summary"
    run.input_json = c.e.canonical_json({"payload": {"input": {}, "context": {}}})
    db.commit()
    statements = []
    engine = db.get_bind()

    def observed(connection, cursor, statement, parameters, context, many):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", observed)
    try:
        assert storage.is_document_change_run(db, run)
    finally:
        event.remove(engine, "before_cursor_execute", observed)
    assert len(statements) >= 1 and not any("FOR UPDATE" in statement.upper() or "FOR SHARE" in statement.upper() for statement in statements)
    with pytest.raises(HTTPException):
        storage.load_snapshot(db, run, user=actor, current=False)
