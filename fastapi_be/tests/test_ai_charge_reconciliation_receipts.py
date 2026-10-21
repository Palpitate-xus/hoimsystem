"""Real SQLite terminal blobs, exact audit PK and injected post-write faults."""

import json
import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import event, update

from app.ai import charge_reconciliation_receipts as receipts
from app.ai import charge_reconciliation_sources as sources
from app.ai.charge_reconciliation_draft import ChargeReconciliationDraft
from app.ai.charge_reconciliation_models import AIChargeCaseSnapshot
from app.ai.charge_reconciliation_result import result_for_draft
from app.ai.charge_reconciliation_run_models import AIChargeRunArtifact
from app.ai.models import AIAuditEvent, AIRun
from tests.test_ai_charge_reconciliation_sources import charge_case as _charge_case
from tests.test_ai_charge_reconciliation_storage import original_run

charge_case = _charge_case


def running(case):
    run, snapshot, _, source = original_run(case)
    db = case["db"]
    sources.current_actor(db, case["super_admin_user"])
    run = db.query(AIRun).filter_by(run_id=run.run_id).populate_existing().with_for_update().one()
    run.status, run.lease_token, run.start_time = "running", str(uuid.uuid4()), sources.utcnow()
    db.commit()
    return run, snapshot, source


def terminal(case, *, state="succeeded", inputs=13, outputs=7, attempted=True, claimed=True):
    db = case["db"]
    if claimed:
        run, _, source = running(case)
    else:
        run, _, _, source = original_run(case)
    sources.current_actor(db, case["super_admin_user"])
    run = db.query(AIRun).filter_by(run_id=run.run_id).populate_existing().with_for_update().one()
    run.status = state
    run.input_tokens, run.output_tokens = inputs if inputs is not None else 0, outputs if outputs is not None else 0
    run.latency_ms = 4
    run.finish_time = sources.utcnow()
    run.error_code, run.error_message = ("SYNTHETIC_PARTIAL", "合成原回执缺项") if state == "failed" else ("", "")
    draft = ChargeReconciliationDraft(
        schema_version="charge_reconciliation_draft_v1",
        source_id=source["source_id"],
        source_projection_hash=source["projection_hash"],
        coverage="partial_questions_no_completeness_or_correctness_claim",
        observations=[],
    )
    result = result_for_draft(source["public_source"], draft, source["projection_hash"]).model_dump(mode="json") if state == "succeeded" else None
    receipts.stage_terminal(db, run, receipts.usage(inputs, outputs, attempted), result)
    db.commit()
    return run, result


def test_pending_usage_is_unknown_and_success_binds_whole_blob_to_specific_audit(charge_case):
    case, db = charge_case, charge_case["db"]
    queued, _, _, _ = original_run(case)
    result, usage = receipts.load_terminal(db, queued)
    assert result is None and usage == {"input_tokens": None, "output_tokens": None, "complete": False, "model_call_attempted": None}
    run, expected = terminal(case)
    result, usage = receipts.load_terminal(db, run)
    assert result == expected and usage == {"input_tokens": 13, "output_tokens": 7, "complete": True, "model_call_attempted": True}
    row = db.get(AIChargeRunArtifact, run.run_id)
    pointer = json.loads(run.result_json)
    assert len(run.result_json.encode("utf-8")) < 65535
    assert pointer["receipt_event_id"] == row.receipt_event_id and pointer["content_hash"] == row.result_hash
    assert row.result_bytes == len(row.result_json.encode("utf-8")) > len(row.result_json)
    assert db.get(AIAuditEvent, row.receipt_event_id).action == receipts.ACCEPT


def test_paid_partial_usage_is_not_replaced_by_legacy_zero(charge_case):
    run, _ = terminal(charge_case, state="failed", inputs=13, outputs=None)
    result, usage = receipts.load_terminal(charge_case["db"], run)
    assert result is None and usage == {"input_tokens": 13, "output_tokens": None, "complete": False, "model_call_attempted": True}
    assert run.output_tokens == 0


@pytest.mark.parametrize("claimed", [False, True])
def test_true_unattempted_cancel_retains_actual_zero_and_original_lease_state(charge_case, claimed):
    run, _ = terminal(charge_case, state="cancelled", inputs=0, outputs=0, attempted=False, claimed=claimed)
    result, usage = receipts.load_terminal(charge_case["db"], run)
    assert result is None and usage == {"input_tokens": 0, "output_tokens": 0, "complete": True, "model_call_attempted": False}
    assert (run.lease_token is not None) == claimed


@pytest.mark.parametrize("mutation", ["action", "target", "actor", "extra_receipt_field", "counter", "blob", "pointer"])
def test_changed_actual_receipt_or_result_cannot_be_downgraded_to_plain_result(charge_case, mutation):
    case, db = charge_case, charge_case["db"]
    run, _ = terminal(case)
    row = db.get(AIChargeRunArtifact, run.run_id)
    audit = db.get(AIAuditEvent, row.receipt_event_id)
    if mutation == "action":
        audit.action = receipts.FAIL
    elif mutation == "target":
        audit.target = str(uuid.uuid4())
    elif mutation == "actor":
        audit.actor_id = case["admin_user"].user_id
    elif mutation == "extra_receipt_field":
        value = json.loads(audit.detail_json)
        value["financially_validated"] = True
        audit.detail_json = sources.c.canonical_json(value)
    elif mutation == "counter":
        run.input_tokens = 14
    elif mutation == "blob":
        row.result_json = row.result_json.replace("尚未", "已经", 1)
    else:
        run.result_json = "{}"
    db.commit()
    with pytest.raises(HTTPException) as caught:
        receipts.load_terminal(db, run)
    assert caught.value.status_code == 409


@pytest.mark.parametrize(
    "field,value", [("requested_by", "other_actor"), ("preview", 0), ("input_tokens", 14), ("output_tokens", 8), ("error_code", "ALTERED"), ("error_message", "合成注入改变"), ("latency_ms", 99)]
)
def test_actual_post_write_sql_fault_rolls_back_whole_run_artifact_and_receipt(charge_case, field, value):
    case, db = charge_case, charge_case["db"]
    run, _, source = running(case)
    sources.current_actor(db, case["super_admin_user"])
    run = db.query(AIRun).filter_by(run_id=run.run_id).populate_existing().with_for_update().one()
    run.status, run.input_tokens, run.output_tokens, run.latency_ms = "succeeded", 13, 7, 4
    draft = ChargeReconciliationDraft(
        schema_version="charge_reconciliation_draft_v1",
        source_id=source["source_id"],
        source_projection_hash=source["projection_hash"],
        coverage="partial_questions_no_completeness_or_correctness_claim",
        observations=[],
    )
    result = result_for_draft(source["public_source"], draft, source["projection_hash"]).model_dump(mode="json")
    actual = case["admin_user"].user_id if value == "other_actor" else value
    connection = db.connection()
    fired = []

    def fault(conn, cursor, statement, parameters, execution_context, many):
        if not fired and statement.lstrip().upper().startswith("UPDATE HOIMSYSTEM_AI_RUN SET"):
            fired.append(True)
            conn.execute(update(AIRun).where(AIRun.run_id == run.run_id).values({field: actual}))

    event.listen(connection, "after_cursor_execute", fault)
    try:
        with pytest.raises(HTTPException) as caught:
            receipts.stage_terminal(db, run, receipts.usage(13, 7, True), result)
        assert caught.value.status_code == 409 and fired == [True]
    finally:
        event.remove(connection, "after_cursor_execute", fault)
        db.rollback()
    db.expire_all()
    assert db.get(AIRun, run.run_id).status == "running"
    artifact = db.get(AIChargeRunArtifact, run.run_id)
    assert artifact.result_json is artifact.receipt_event_id is artifact.accepted_lease is None
    assert db.query(AIAuditEvent).filter_by(target=run.run_id, action=receipts.ACCEPT).count() == 0
    assert db.get(AIChargeCaseSnapshot, source["case_snapshot_id"]).status == "published"


def test_accepted_artifact_cannot_be_overwritten(charge_case):
    case, db = charge_case, charge_case["db"]
    run, result = terminal(case)
    with pytest.raises(HTTPException) as caught:
        receipts.stage_terminal(db, run, receipts.usage(13, 7, True), result)
    assert caught.value.status_code == 409
    db.rollback()
    assert receipts.load_terminal(db, run)[0] == result


@pytest.mark.parametrize(
    "receipt",
    [
        {"input_tokens": None, "output_tokens": 0, "complete": False, "model_call_attempted": False},
        {"input_tokens": True, "output_tokens": 0, "complete": True, "model_call_attempted": True},
        {"input_tokens": 0, "output_tokens": 0, "complete": False, "model_call_attempted": False},
    ],
)
def test_impossible_or_coerced_receipts_rejected(receipt):
    with pytest.raises(ValueError):
        receipts.ChargeUsage.model_validate(receipt)
