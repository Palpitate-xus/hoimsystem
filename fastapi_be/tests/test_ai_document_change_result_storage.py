"""Complete actual SQL acceptance/receipts, without provider or worker execution."""

import copy
import datetime as dt
import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import text

from app.ai import document_change_contract as c
from app.ai import document_change_result_storage as result_store
from app.ai import document_change_sources as sources
from app.ai import document_change_storage as storage
from app.ai.document_change_draft import build_draft
from app.ai.document_change_result import result_for_draft
from app.ai.document_change_run_models import AIDocumentChangeRunArtifact, AIDocumentChangeRunResult
from app.ai.models import AIAuditEvent, AIRun
from tests.test_ai_document_change_sources import change_case as change_case  # noqa: F401
from tests.test_ai_document_change_storage import remove_prior_tasks as remove_prior_tasks  # noqa: F401
from tests.test_ai_document_change_storage import task
from tests.test_ai_document_evidence_contract import NOTE, NOW
from tests.test_ai_document_evidence_sources import cas

KNOWN = {"input_tokens": 11, "output_tokens": 13, "complete": True, "model_call_attempted": True}
ZERO = {"input_tokens": 0, "output_tokens": 0, "complete": True, "model_call_attempted": False}


def executing(case):
    result = task(case)
    run = result["run"]
    run.status, run.lease_token, run.start_time = "running", str(uuid.uuid4()), run.create_time.replace(microsecond=0)
    case[0].commit()
    draft = build_draft({"changes": []}, result["source"], result["metadata"]["instructions_digest"])
    result["result"] = result_for_draft(draft, result["source"], result["metadata"]["instructions_digest"])
    return result


def accepted(case):
    value = executing(case)
    run = value["run"]
    reference = result_store.stage_result(case[0], case[1], run, run.lease_token, value["result"], KNOWN, latency_ms=17)
    case[0].commit()
    value["reference"] = reference
    return value


def test_actual_complete_acceptance_blob_short_pointer_independent_usage_and_audit(change_case):
    db, actor, *_ = change_case
    case = accepted(change_case)
    run = case["run"]
    artifact = db.get(AIDocumentChangeRunArtifact, run.run_id)
    blob = db.get(AIDocumentChangeRunResult, run.run_id)
    assert run.status == "succeeded" and run.input_tokens == 11 and run.output_tokens == 13
    assert blob.result_json == c.e.canonical_json(case["result"]) and blob.result_bytes == len(c.e.utf8(blob.result_json))
    assert artifact.usage_event_id != blob.accept_audit_event_id
    assert c.e.canonical_json(case["reference"]) == run.result_json and len(c.e.utf8(run.result_json)) < 65535
    assert result_store.usage_receipt(db, run).model_dump(mode="json") == KNOWN
    assert result_store.expand_result(db, actor, run) == case["result"]
    assert db.get(AIAuditEvent, artifact.usage_event_id).action == result_store.USAGE
    assert db.get(AIAuditEvent, blob.accept_audit_event_id).action == result_store.ACCEPT


@pytest.mark.parametrize("change", ["cancel_won", "lease", "raw_result", "provider", "config", "prompt", "role", "scope"])
def test_untrusted_or_changed_acceptance_rolls_back_every_blob_pointer_receipt(change_case, change):
    db, actor, *_ = change_case
    case = executing(change_case)
    run, lease, value = case["run"], case["run"].lease_token, case["result"].model_dump(mode="json")
    if change == "cancel_won":
        run.status = "cancelled"
    elif change == "lease":
        lease = str(uuid.uuid4())
    elif change == "raw_result":
        value["summary"] = "伪造已确认影响"
    elif change == "provider":
        case["provider"].revision += 1
    elif change == "config":
        from app.ai.models import AIFeatureConfig

        db.get(AIFeatureConfig, storage.FEATURE_KEY).revision += 1
    elif change == "prompt":
        from app.ai.models import AIPromptVersion

        db.query(AIPromptVersion).filter_by(feature_key=storage.FEATURE_KEY).one().task_prompt += "changed"
    elif change == "role":
        actor.user_role = "admin"
    else:
        sources.revoke_scope(db, actor, case["scope"].snapshot.scope_id, {**cas(case["scope"]), "basis_note": NOTE})
    db.commit()
    audit_count = db.query(AIAuditEvent).count()
    with pytest.raises(HTTPException):
        result_store.stage_result(db, actor, run, lease, value, KNOWN, latency_ms=17)
    assert db.query(AIDocumentChangeRunResult).count() == 0
    artifact = db.get(AIDocumentChangeRunArtifact, run.run_id)
    assert artifact.usage_event_id is None
    assert db.get(AIRun, run.run_id).result_json == "{}" and db.query(AIAuditEvent).count() == audit_count


@pytest.mark.parametrize("usage", [{**KNOWN, "input_tokens": True}, {**KNOWN, "input_tokens": -1}, {**KNOWN, "model_call_attempted": False}])
def test_success_never_substitutes_invalid_usage(change_case, usage):
    db, actor, *_ = change_case
    case = executing(change_case)
    run = case["run"]
    with pytest.raises(HTTPException):
        result_store.stage_result(db, actor, run, run.lease_token, case["result"], usage, latency_ms=0)
    assert db.query(AIDocumentChangeRunResult).count() == 0 and db.get(AIDocumentChangeRunArtifact, run.run_id).usage_event_id is None


def test_success_preserves_independent_unknown_usage_without_fabricating_a_complete_receipt(change_case):
    db, actor, *_ = change_case
    case = executing(change_case)
    run = case["run"]
    unknown = {**KNOWN, "input_tokens": None, "complete": False}
    result_store.stage_result(db, actor, run, run.lease_token, case["result"], unknown, latency_ms=0)
    db.commit()
    assert run.status == "succeeded"
    assert result_store.usage_receipt(db, run).model_dump(mode="json") == unknown
    assert result_store.usage_receipt(db, run).input_tokens is None
    assert result_store.usage_receipt(db, run).complete is False


def test_queue_cancel_proves_no_call_and_never_reads_live_source(change_case):
    db, actor, *_ = change_case
    case = task(change_case)
    run = case["run"]
    assert result_store.usage_receipt(db, run).input_tokens is None
    # A queued technical cancellation does not need to wait on revoked Source.
    sources.revoke_scope(db, actor, case["scope"].snapshot.scope_id, {**cas(case["scope"]), "basis_note": NOTE})
    db.commit()
    event_id = result_store.stage_terminal(db, run, None, status="cancelled", usage=ZERO, latency_ms=0, queued_no_call=True, actor_id=actor.user_id)
    db.commit()
    assert run.status == "cancelled" and run.lease_token is None
    assert result_store.usage_receipt(db, run).model_dump(mode="json") == ZERO
    assert db.get(AIDocumentChangeRunArtifact, run.run_id).usage_event_id == event_id
    assert result_store.expand_result(db, actor, run, current=False) is None


def test_failed_lease_preserves_partial_actual_usage_after_role_loss(change_case):
    db, actor, *_ = change_case
    case = executing(change_case)
    run = case["run"]
    actor.user_role = "admin"
    db.commit()
    usage = {"input_tokens": 11, "output_tokens": None, "complete": False, "model_call_attempted": True}
    result_store.stage_terminal(db, run, run.lease_token, status="failed", usage=usage, latency_ms=9, error_code="CURRENT_SCOPE_LOST")
    db.commit()
    assert run.status == "failed" and run.input_tokens == 11 and run.output_tokens == 0
    assert result_store.usage_receipt(db, run).model_dump(mode="json") == usage
    with pytest.raises(HTTPException):
        result_store.expand_result(db, actor, run, current=False)


@pytest.mark.parametrize("trigger", ["usage_audit", "accept_audit", "blob", "run_update", "artifact_usage", "accepted_clock"])
def test_actual_sql_failures_or_postflush_mutations_roll_back_complete_acceptance(change_case, trigger):
    db, actor, *_ = change_case
    case = executing(change_case)
    run = case["run"]
    prior = db.query(AIAuditEvent).count()
    sql = {
        "usage_audit": "BEFORE INSERT ON hoimsystem_ai_audit_event WHEN NEW.action='run.document_change.usage' BEGIN SELECT RAISE(ABORT,'reject usage'); END",
        "accept_audit": "BEFORE INSERT ON hoimsystem_ai_audit_event WHEN NEW.action='run.document_change.accept' BEGIN SELECT RAISE(ABORT,'reject accept'); END",
        "blob": "AFTER INSERT ON hoimsystem_ai_document_change_run_result BEGIN UPDATE hoimsystem_ai_document_change_run_result SET result_json='{}' WHERE run_id=NEW.run_id; END",
        "run_update": "AFTER UPDATE ON hoimsystem_ai_run WHEN NEW.status='succeeded' BEGIN UPDATE hoimsystem_ai_run SET input_tokens=999 WHERE run_id=NEW.run_id; END",
        "artifact_usage": "AFTER UPDATE ON hoimsystem_ai_document_change_run_artifact WHEN NEW.usage_event_id IS NOT NULL BEGIN UPDATE hoimsystem_ai_document_change_run_artifact SET usage_event_id=NEW.created_audit_event_id WHERE run_id=NEW.run_id; END",
        "accepted_clock": "AFTER INSERT ON hoimsystem_ai_document_change_run_result BEGIN UPDATE hoimsystem_ai_document_change_run_result SET accepted_at='"
        + str(c.e.clock(NOW) + dt.timedelta(microseconds=1))
        + "' WHERE run_id=NEW.run_id; END",
    }[trigger]
    db.execute(text("CREATE TRIGGER break_change_accept " + sql))
    db.commit()
    with pytest.raises(HTTPException):
        result_store.stage_result(db, actor, run, run.lease_token, case["result"], KNOWN, latency_ms=17)
    assert db.query(AIDocumentChangeRunResult).count() == 0
    assert db.get(AIDocumentChangeRunArtifact, run.run_id).usage_event_id is None
    assert db.get(AIRun, run.run_id).status == "running" and db.get(AIRun, run.run_id).result_json == "{}"
    assert db.query(AIAuditEvent).count() == prior
    db.execute(text("DROP TRIGGER IF EXISTS break_change_accept"))
    db.commit()


def test_result_read_recomputes_fixed_explanation_not_matching_mutated_hashes(change_case):
    db, actor, *_ = change_case
    case = accepted(change_case)
    run = case["run"]
    blob = db.get(AIDocumentChangeRunResult, run.run_id)
    value = copy.deepcopy(case["result"].model_dump(mode="json"))
    value["summary"] = "伪造语义结论"
    blob.result_json = c.e.canonical_json(value)
    blob.content_hash = c.e.bytes_hash(blob.result_json)
    blob.result_bytes = len(c.e.utf8(blob.result_json))
    reference = copy.deepcopy(case["reference"].model_dump(mode="json"))
    reference.update(content_hash=blob.content_hash, result_bytes=blob.result_bytes)
    run.result_json = c.e.canonical_json(reference)
    db.commit()
    with pytest.raises(HTTPException):
        result_store.expand_result(db, actor, run)


def test_current_provider_changes_do_not_rewrite_successful_frozen_history(change_case):
    db, actor, *_ = change_case
    case = accepted(change_case)
    case["provider"].enabled = 0
    case["provider"].model += "changed"
    case["provider"].revision += 1
    db.commit()
    assert storage.expand_result(db, actor, case["run"], current=True) == case["result"]


def test_successful_proof_after_source_revoke_requires_explicit_frozen_read(change_case):
    db, actor, *_ = change_case
    case = accepted(change_case)
    sources.revoke_scope(db, actor, case["scope"].snapshot.scope_id, {**cas(case["scope"]), "basis_note": NOTE})
    db.commit()
    with pytest.raises(HTTPException):
        storage.expand_result(db, actor, case["run"], current=True)
    assert storage.expand_result(db, actor, case["run"], current=False) == case["result"]


def test_actual_queue_cancel_authorizes_current_super_without_source_reads(change_case):
    from sqlalchemy import event

    db, actor, *_ = change_case
    case = task(change_case)
    statements = []
    engine = db.get_bind()

    def observed(connection, cursor, statement, parameters, context, many):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", observed)
    try:
        storage.cancel_unclaimed(db, actor, case["run"])
        db.commit()
    finally:
        event.remove(engine, "before_cursor_execute", observed)
    assert not any("FROM hoimsystem_ai_document_change_scope" in sql or "FROM hoimsystem_ai_document_original" in sql for sql in statements)
    assert storage.usage_receipt(db, case["run"]).model_dump(mode="json") == ZERO


def test_queue_cancel_rejects_current_role_loss_and_claimed_sql_trace(change_case):
    db, actor, *_ = change_case
    case = task(change_case)
    actor.user_role = "admin"
    db.commit()
    with pytest.raises(HTTPException) as error:
        storage.cancel_unclaimed(db, actor, case["run"])
    assert error.value.status_code == 403
    assert db.get(AIDocumentChangeRunArtifact, case["run"].run_id).usage_event_id is None


def test_terminal_receipt_cannot_overwrite_or_forge_cached_lease(change_case):
    db, _, *_ = change_case
    case = executing(change_case)
    run = case["run"]
    lease = run.lease_token
    run.lease_token = None
    with pytest.raises(HTTPException):
        storage.stage_terminal(db, run, lease, status="failed", usage=KNOWN, latency_ms=5, error_code="ACTUAL_REJECTED")
    db.refresh(run)
    storage.stage_terminal(db, run, run.lease_token, status="failed", usage=KNOWN, latency_ms=5, error_code="ACTUAL_REJECTED")
    db.commit()
    event_id = db.get(AIDocumentChangeRunArtifact, run.run_id).usage_event_id
    with pytest.raises(HTTPException):
        storage.stage_terminal(db, run, run.lease_token, status="failed", usage=KNOWN, latency_ms=5, error_code="ACTUAL_REJECTED")
    assert db.get(AIDocumentChangeRunArtifact, run.run_id).usage_event_id == event_id


def test_failed_usage_postflush_cannot_change_actual_immutable_artifact(change_case):
    db, _, *_ = change_case
    case = executing(change_case)
    run = case["run"]
    prior = db.query(AIAuditEvent).count()
    db.execute(
        text(
            "CREATE TRIGGER corrupt_terminal_anchor AFTER INSERT ON hoimsystem_ai_audit_event WHEN NEW.action='run.document_change.usage' BEGIN UPDATE hoimsystem_ai_document_change_run_artifact SET input_hash='ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff' WHERE run_id=NEW.target; END"
        )
    )
    db.commit()
    try:
        with pytest.raises(HTTPException):
            storage.stage_terminal(db, run, run.lease_token, status="failed", usage=KNOWN, latency_ms=5, error_code="ACTUAL_PROVIDER_REJECTED")
        assert db.get(AIRun, run.run_id).status == "running"
        assert db.get(AIDocumentChangeRunArtifact, run.run_id).usage_event_id is None
        assert db.query(AIAuditEvent).count() == prior
    finally:
        db.rollback()
        db.execute(text("DROP TRIGGER IF EXISTS corrupt_terminal_anchor"))
        db.commit()


def test_actual_packaged_baseline_prompt_version_zero_can_accept(change_case):
    from app.ai.catalog import FEATURE_BY_KEY
    from app.ai.document_change_draft import SYSTEM_PROMPT
    from app.ai.models import AIFeatureConfig

    db, actor, *_ = change_case
    case = task(change_case, stage=False)
    run = case["run"]
    db.get(AIFeatureConfig, storage.FEATURE_KEY).active_prompt_id = None
    run.prompt_version = 0
    packaged_prompt = FEATURE_BY_KEY[storage.FEATURE_KEY].task_prompt
    case["snapshot"]["task_prompt"] = packaged_prompt
    case["metadata"]["instructions_digest"] = c.e.bytes_hash(SYSTEM_PROMPT + "\n\n" + packaged_prompt)
    run.input_json = c.e.canonical_json(case["snapshot"])
    run.context_metadata_json = c.e.canonical_json(case["metadata"])
    run.prompt_hash = c.e.digest([SYSTEM_PROMPT, packaged_prompt])
    storage.stage_artifact(db, actor, run)
    db.commit()
    run.status, run.lease_token, run.start_time = "running", str(uuid.uuid4()), run.create_time.replace(microsecond=0)
    db.commit()
    draft = build_draft({"changes": []}, case["source"], case["metadata"]["instructions_digest"])
    value = result_for_draft(draft, case["source"], case["metadata"]["instructions_digest"])
    assert case["snapshot"]["task_prompt"] == packaged_prompt
    storage.stage_result(db, actor, run, run.lease_token, value, KNOWN, latency_ms=5)
    db.commit()
    assert storage.expand_result(db, actor, run) == value


def test_actual_token_invalidation_after_capture_blocks_new_acceptance(change_case):
    db, actor, *_ = change_case
    case = executing(change_case)
    run = case["run"]
    actor.token_invalid_before = db.get(AIDocumentChangeRunArtifact, run.run_id).recorded_at
    db.commit()
    with pytest.raises(HTTPException):
        storage.load_snapshot(db, run, user=actor, execution=True)
    with pytest.raises(HTTPException):
        storage.stage_result(db, actor, run, run.lease_token, case["result"], KNOWN, latency_ms=5)
    assert db.query(AIDocumentChangeRunResult).count() == 0 and db.get(AIDocumentChangeRunArtifact, run.run_id).usage_event_id is None


def test_prior_same_second_token_reset_uses_exact_artifact_clock_not_run_floor(change_case):
    import datetime as dt

    db, actor, *_ = change_case
    case = executing(change_case)
    run = case["run"]
    clock = db.get(AIDocumentChangeRunArtifact, run.run_id).recorded_at
    assert clock.microsecond > 0
    actor.token_invalid_before = clock - dt.timedelta(microseconds=1)
    run.create_time = clock.replace(microsecond=0)
    db.commit()
    assert actor.token_invalid_before > run.create_time
    storage.load_snapshot(db, run, user=actor, execution=True)
    storage.stage_result(db, actor, run, run.lease_token, case["result"], KNOWN, latency_ms=5)
    db.commit()
    assert storage.expand_result(db, actor, run) == case["result"]


def test_read_verifies_full_utc6_acceptance_clock_not_only_legacy_audit_second(change_case):
    db, actor, *_ = change_case
    case = accepted(change_case)
    blob = db.get(AIDocumentChangeRunResult, case["run"].run_id)
    original_clock = blob.accepted_at
    blob.accepted_at += dt.timedelta(microseconds=1)
    assert blob.accepted_at.replace(microsecond=0) == original_clock.replace(microsecond=0)
    db.commit()
    with pytest.raises(HTTPException):
        result_store.expand_result(db, actor, case["run"], current=False)


def test_unknown_attempt_is_not_a_normal_technical_failure_receipt(change_case):
    db, _, *_ = change_case
    case = executing(change_case)
    run = case["run"]
    with pytest.raises(HTTPException):
        storage.stage_terminal(
            db,
            run,
            run.lease_token,
            status="failed",
            usage={"input_tokens": None, "output_tokens": None, "complete": False, "model_call_attempted": None},
            latency_ms=0,
            error_code="NORMAL_FAILURE_WITHOUT_FACTS",
        )
    db.refresh(run)
    assert run.status == "running" and db.get(AIDocumentChangeRunArtifact, run.run_id).usage_event_id is None


@pytest.mark.parametrize("field", ["finish_time", "start_time", "latency_ms", "error_message"])
def test_accepted_mutable_run_state_tamper_cannot_pass_frozen_result_proof(change_case, field):
    db, actor, *_ = change_case
    case = accepted(change_case)
    run = case["run"]
    value = getattr(run, field)
    setattr(run, field, value + dt.timedelta(microseconds=1) if field.endswith("time") else value + 1 if field == "latency_ms" else "UNBOUND_PRIVATE_ERROR")
    db.commit()
    with pytest.raises(HTTPException):
        storage.expand_result(db, actor, run, current=False)
