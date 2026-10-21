"""Actual complete result blob/pointer/accept/usage atomic SQL and split reads."""

import copy

import pytest
from fastapi import HTTPException
from sqlalchemy import text, update

from app.ai import operations_support_attempts as attempts
from app.ai import operations_support_contract as c
from app.ai import operations_support_receipts as receipts
from app.ai import operations_support_registry as registry
from app.ai import operations_support_result_storage as results
from app.ai import operations_support_storage as storage
from app.ai.models import AIAuditEvent, AIRun
from app.ai.operations_support_models import AIOperationsOriginal
from app.ai.operations_support_run_models import AIOperationsRunArtifact, AIOperationsRunResult
from app.ai.operations_support_usage_contract import usage
from tests.test_ai_operations_support_receipts import actors as actors
from tests.test_ai_operations_support_receipts import claimed as claimed
from tests.test_ai_operations_support_receipts import configured as configured
from tests.test_ai_operations_support_receipts import queued as queued
from tests.test_ai_operations_support_receipts import source as source
from tests.test_ai_operations_support_registry import request
from tests.test_ai_operations_support_storage import no_body


@pytest.fixture
def dispatched(claimed):
    configured, claim = claimed
    db = configured[0][0]
    user = configured[0][-1]
    dispatch = attempts.stage_dispatch(db, user, claim)
    source = storage.load_artifact(db, user, claim.run_id)[2]
    document = source.documents[0]
    quote = dict(source_id=document.source_id, start_codepoint=4, end_codepoint=8, quote=document.text[4:8])
    result = dict(
        schema_version="operations_support_draft_v1",
        source_id=source.source_id,
        source_sha256=c.content_hash(source),
        objective="explain_observations",
        status="unverified_operations_draft",
        environment_status="not_observed_by_this_task",
        compatibility_status="not_verified_from_reviewed_text",
        observations=[dict(title="明确受审材料片段", explanation="只解释已提供字面材料，环境和根因未核实", evidence=[quote])],
        hypotheses=[],
        manual_checks=[],
        gaps=[dict(kind="missing_reviewed_runbook", explanation="没有审核手册，未生成检查指令")],
    )
    return configured, claim, dispatch, result


def accept(value, reported=usage(11, 13, True)):
    configured, claim, dispatch, result = value
    return results.stage_result(configured[0][0], configured[0][-1], claim, result, dispatch_event_id=dispatch.dispatch_event_id, usage=reported, latency_ms=81)


@pytest.mark.parametrize("reported", [usage(11, 13, True), usage(11, None, True), usage(None, 13, True), usage(None, None, True)])
def test_actual_complete_acceptance_independent_nullable_paid_use_five_distinct_pks_and_exact_quote(dispatched, reported):
    configured, claim, dispatch, result = dispatched
    db = configured[0][0]
    user = configured[0][-1]
    before = db.query(AIAuditEvent).count()
    accepted = accept(dispatched, reported)
    assert accepted.model_dump() == result and results.load_result(db, user, claim.run_id) == accepted
    actual = attempts.technical_attempt(db, claim)
    receipt = receipts.read_receipt(db, actual)
    blob = db.get(AIOperationsRunResult, claim.run_id)
    assert receipt.usage.model_dump() == reported and receipt.status == "succeeded"
    assert receipt.usage.complete == reported["complete"] and actual.header["output_tokens"] == (reported["output_tokens"] if reported["output_tokens"] is not None else 0)
    assert len({claim.created_audit_event_id, claim.claim_event_id, dispatch.dispatch_event_id, blob.accept_audit_event_id, actual.artifact["usage_event_id"]}) == 5
    assert db.query(AIAuditEvent).count() == before + 2 and blob.result_json == c.canonical_json(result)
    assert accepted.observations[0].evidence[0].quote == "😀\r\n\x00"
    assert db.get(AIRun, claim.run_id).result_json == receipts.result_reference({column.name: getattr(blob, column.name) for column in AIOperationsRunResult.__table__.columns})


def test_complete_result_larger_than_legacy_text_is_preserved_in_blob_with_only_short_pointer(dispatched):
    configured, claim, dispatch, result = dispatched
    db = configured[0][0]
    finding = result["observations"][0]
    result["observations"] = [{**copy.deepcopy(finding), "explanation": "合成完整说明" * 600} for _ in range(64)]
    expected = c.canonical_json(result)
    assert len(expected.encode()) > 65535
    actual = accept(dispatched)
    assert c.canonical_json(actual) == expected and db.get(AIOperationsRunResult, claim.run_id).result_bytes == len(expected.encode())
    assert len(db.get(AIRun, claim.run_id).result_json.encode()) < 1024
    assert c.canonical_json(results.load_result(db, configured[0][-1], claim.run_id)) == expected


@pytest.mark.parametrize("fault", ["foreign_source", "invented_quote", "verified_environment", "extra_command", "wrong_objective"])
def test_invalid_claimed_result_cannot_create_blob_pointer_or_accept_usage_audits(dispatched, fault):
    configured, claim, dispatch, result = dispatched
    db = configured[0][0]
    if fault == "foreign_source":
        result["source_sha256"] = "0" * 64
    elif fault == "invented_quote":
        result["observations"][0]["evidence"][0]["quote"] = "invented"
    elif fault == "verified_environment":
        result["environment_status"] = "observed"
    elif fault == "extra_command":
        result["commands"] = ["invented"]
    else:
        result["objective"] = "prepare_reviewed_checks"
    before = db.query(AIAuditEvent).count()
    with pytest.raises(HTTPException) as exc:
        accept(dispatched)
    assert exc.value.status_code == 409 and db.query(AIAuditEvent).count() == before
    assert db.get(AIOperationsRunResult, claim.run_id) is None and db.get(AIRun, claim.run_id).result_json == "{}"


def test_current_source_withdrawal_denies_before_any_body_and_preserves_original_delivery_for_paid_settlement(dispatched):
    configured, claim, dispatch, result = dispatched
    actors, original, release, case, provider, config = configured
    db, registrar, creator, reviewer, admin = actors
    registry.revoke_original(db, registrar, original["original_id"], {"revision": 1, "reason": "模型返回时资料已撤回"})
    before = db.query(AIAuditEvent).count()
    no_body(db, lambda: accept(dispatched, usage(11, None, True)), 403)
    assert db.query(AIAuditEvent).count() == before and db.get(AIOperationsRunResult, claim.run_id) is None
    value = receipts.stage_terminal(db, claim, dispatch_event_id=dispatch.dispatch_event_id, usage=usage(11, None, True), status="failed", error_code="SOURCE_NOT_CURRENT", latency_ms=81)
    assert value.usage.model_dump() == usage(11, None, True)
    no_body(db, lambda: results.load_result(db, registrar, claim.run_id), 403)


def test_cancelled_owner_never_accepts_result_but_still_records_actual_partial_paid_use(dispatched):
    configured, claim, dispatch, result = dispatched
    db = configured[0][0]
    # Direct state fixture; actual public cancellation is a later feature.
    db.execute(update(AIRun).where(AIRun.run_id == claim.run_id).values(status="cancelled").execution_options(synchronize_session=False))
    assert accept(dispatched, usage(11, None, True)) is None and db.get(AIOperationsRunResult, claim.run_id) is None
    value = receipts.stage_terminal(db, claim, dispatch_event_id=dispatch.dispatch_event_id, usage=usage(11, None, True), status="cancelled", error_code="TASK_CANCELLED", latency_ms=81)
    assert value.status == "cancelled" and value.usage.input_tokens == 11 and value.usage.output_tokens is None


def test_wrong_delivery_dispatch_is_inert_and_duplicate_completed_result_never_replays(dispatched):
    configured, claim, dispatch, result = dispatched
    db = configured[0][0]
    before = db.query(AIAuditEvent).count()
    assert results.stage_result(db, configured[0][-1], claim, result, dispatch_event_id=dispatch.dispatch_event_id + 1000, usage=usage(11, 13, True), latency_ms=81) is None
    assert db.query(AIAuditEvent).count() == before
    assert accept(dispatched) is not None
    before = db.query(AIAuditEvent).count()
    assert accept(dispatched) is None and db.query(AIAuditEvent).count() == before


@pytest.mark.parametrize("damage", ["source", "actor_role", "provider", "accept_audit", "blob_rehash", "result_audit_pk", "pointer", "usage_pk"])
def test_actual_result_or_terminal_sql_trigger_rolls_back_blob_pointer_both_audits_and_full_state(dispatched, damage):
    configured, claim, dispatch, result = dispatched
    actors, original, release, case, provider, config = configured
    db, registrar, creator, reviewer, admin = actors
    db.commit()
    if damage == "source":
        command = "UPDATE hoimsystem_ai_operations_original SET content_text='changed' WHERE original_id='" + original["original_id"] + "';"
    elif damage == "actor_role":
        command = "UPDATE hoimsystem_users SET user_role='doctor' WHERE user_id=" + str(admin.user_id) + ";"
    elif damage == "provider":
        command = "UPDATE hoimsystem_ai_provider SET revision=revision+1 WHERE provider_id=" + str(provider.provider_id) + ";"
    elif damage == "accept_audit":
        command = "UPDATE hoimsystem_ai_audit_event SET action='different' WHERE event_id=NEW.accept_audit_event_id;"
    elif damage == "blob_rehash":
        command = "UPDATE hoimsystem_ai_operations_run_result SET result_json='{}',result_bytes=2,result_hash='" + registry.raw_sha("{}") + "' WHERE run_id=NEW.run_id;"
    elif damage == "result_audit_pk":
        command = "UPDATE hoimsystem_ai_operations_run_result SET accept_audit_event_id=" + str(claim.claim_event_id) + " WHERE run_id=NEW.run_id;"
    elif damage == "pointer":
        command = "UPDATE hoimsystem_ai_run SET result_json='{}' WHERE run_id=NEW.run_id;"
    else:
        command = "UPDATE hoimsystem_ai_operations_run_artifact SET usage_event_id=" + str(dispatch.dispatch_event_id) + " WHERE run_id=NEW.run_id;"
    if damage == "pointer":
        trigger = "AFTER UPDATE OF result_json ON hoimsystem_ai_run WHEN NEW.status='succeeded'"
    elif damage == "usage_pk":
        # A distinct actual PK with wrong semantic action, while preserving the
        # physical pair-distinct CHECK: use the new accept audit, not dispatch.
        command = (
            "UPDATE hoimsystem_ai_operations_run_artifact SET usage_event_id=(SELECT accept_audit_event_id FROM hoimsystem_ai_operations_run_result WHERE run_id=NEW.run_id) WHERE run_id=NEW.run_id;"
        )
        trigger = "AFTER UPDATE OF usage_event_id ON hoimsystem_ai_operations_run_artifact WHEN NEW.usage_event_id IS NOT NULL AND OLD.usage_event_id IS NULL"
    else:
        trigger = "AFTER INSERT ON hoimsystem_ai_operations_run_result"
    db.execute(text("CREATE TRIGGER ops_after_accept " + trigger + " BEGIN " + command + " END"))
    before = db.query(AIAuditEvent).count()
    try:
        with pytest.raises(HTTPException), db.begin_nested():
            accept(dispatched)
        assert db.query(AIAuditEvent).count() == before and db.get(AIOperationsRunResult, claim.run_id) is None
        assert db.query(AIRun.status, AIRun.result_json).filter_by(run_id=claim.run_id).one() == ("running", "{}")
        assert db.query(AIOperationsRunArtifact.usage_event_id).filter_by(run_id=claim.run_id).scalar() is None
        assert db.query(AIOperationsOriginal.content_text).filter_by(original_id=original["original_id"]).scalar() == request()["content_text"]
    finally:
        db.rollback()
        db.execute(text("DROP TRIGGER IF EXISTS ops_after_accept"))
        db.commit()


def test_authorized_historical_result_does_not_require_provider_still_enabled(dispatched):
    configured, claim, dispatch, result = dispatched
    db = configured[0][0]
    accept(dispatched, usage(None, None, True))
    configured[-2].enabled = 0
    db.flush()
    assert results.load_result(db, configured[0][-1], claim.run_id).model_dump() == result
    configured[-1].allowed_roles_json = '["doctor"]'
    db.flush()
    no_body(db, lambda: results.load_result(db, configured[0][-1], claim.run_id), 403)
