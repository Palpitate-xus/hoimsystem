"""Actual full accepted drafts and independently nullable terminal accounting."""

import datetime as dt

import pytest
from fastapi import HTTPException
from sqlalchemy import event, text

from app.ai import clinical_training_attempts as a
from app.ai import clinical_training_contract as c
from app.ai import clinical_training_receipts as r
from app.ai import clinical_training_result_storage as results
from app.ai import clinical_training_reviews as reviews
from app.ai import clinical_training_storage as s
from app.ai.clinical_training_run_models import AITrainingRunResult
from app.ai.clinical_training_usage_contract import usage
from app.ai.models import AIAuditEvent, AIRun
from tests.ai_admin_usage_assertions import assert_exact_usage_event
from tests.test_ai_clinical_training_configuration import configured as configured
from tests.test_ai_clinical_training_practice import practice_case as practice_case
from tests.test_ai_clinical_training_reference_sql import reference_case as reference_case
from tests.test_ai_clinical_training_registry import observe_bodies
from tests.test_ai_clinical_training_reviews import reviewed_case as reviewed_case
from tests.test_ai_clinical_training_storage import assert_zero_bodies, counts
from tests.test_ai_clinical_training_storage import stored as stored
from tests.test_ai_clinical_training_task_contract import draft


def dispatched(stored):
    case, key = stored
    db = case["db"]
    claim = a.stage_claim(db, case["actor"], key)
    dispatch = a.stage_dispatch(db, case["actor"], claim)
    source = s.load_artifact(db, case["actor"], key, execution=True)[2]
    db.commit()
    return case, key, claim, dispatch, source


@pytest.mark.parametrize("inputs,outputs", [(0, 0), (11, None), (None, 7), (None, None)])
def test_actual_full_result_five_specific_phase_pks_and_partial_usage_never_regrades_or_fabricates_zero(stored, inputs, outputs):
    case, key, claim, dispatch, source = dispatched(stored)
    db, value = case["db"], draft(source.model_dump(mode="json"))
    known = usage(inputs, outputs, True)
    accepted = results.stage_result(db, case["actor"], claim, value, dispatch_event_id=dispatch.dispatch_event_id, usage=known, latency_ms=17)
    db.commit()
    assert accepted.model_dump(mode="json") == value and results.load_result(db, case["actor"], key) == accepted
    actual = a.technical_attempt(db, claim)
    receipt = r.read_receipt(db, actual)
    assert receipt.usage.model_dump(mode="json") == known and receipt.status == "succeeded"
    assert_exact_usage_event(db, key, "clinical_training", known)
    row = db.get(AITrainingRunResult, key)
    assert len({actual.artifact["created_audit_event_id"], actual.artifact["claim_event_id"], actual.artifact["dispatch_event_id"], actual.artifact["usage_event_id"], row.accept_audit_event_id}) == 5
    assert db.get(AIAuditEvent, row.accept_audit_event_id).action == results.ACCEPT_ACTION
    assert db.get(AIAuditEvent, actual.artifact["usage_event_id"]).action == r.USAGE_ACTION
    assert row.source_projection_hash == c.content_hash(source) and row.lease_token == claim.lease_token
    assert (actual.header["input_tokens"], actual.header["output_tokens"]) == (inputs if inputs is not None else 0, outputs if outputs is not None else 0)
    # Legacy nonnullable Run counters are storage placeholders. Only the
    # independent actual receipt exposes known vs unknown, with no cost claim.
    assert "cost" not in receipt.model_dump() and source.feedback.matching_count == source.feedback.question_count == 2
    before = counts(db)
    assert results.stage_result(db, case["actor"], claim, value, dispatch_event_id=dispatch.dispatch_event_id, usage=known, latency_ms=17) is None
    assert counts(db) == before


def test_actual_result_beyond_legacy_text_keeps_entire_blob_and_only_short_pointer_in_run(stored):
    case, key, claim, dispatch, source = dispatched(stored)
    db, value = case["db"], draft(source.model_dump(mode="json"))
    explanation = value["explanations"][0]
    value["revision_steps"] = [dict(question_ids=[explanation["question_id"]], kind="repeat_same_synthetic_question", explanation="复" * 4000, evidence=explanation["evidence"]) for _ in range(32)]
    raw = c.whole(value)
    assert len(raw.encode()) > 65535
    accepted = results.stage_result(db, case["actor"], claim, value, dispatch_event_id=dispatch.dispatch_event_id, usage=usage(11, None, True), latency_ms=3)
    db.commit()
    row = db.get(AITrainingRunResult, key)
    run = db.get(AIRun, key)
    assert row.result_json.encode() == raw.encode() and row.result_bytes == len(raw.encode())
    assert run.result_json == r.result_reference({column.name: getattr(row, column.name) for column in AITrainingRunResult.__table__.columns if column.name != "result_json"})
    assert len(run.result_json.encode()) < 65535 and "复" * 4000 not in run.result_json
    assert results.load_result(db, case["actor"], key) == accepted


@pytest.mark.parametrize("fault", ["review", "role", "epoch", "configuration"])
def test_source_loss_refuses_accept_before_bodies_but_exact_original_dispatch_keeps_actual_paid_partial_usage(stored, fault):
    case, key, claim, dispatch, source = dispatched(stored)
    db = case["db"]
    if fault == "review":
        reviews.revoke_review(db, case["author"], case["review"]["review_id"], dict(revision=1, reason="本次实际来源模型范围撤回"))
    elif fault == "role":
        db.execute(text("UPDATE hoimsystem_users SET user_role='admin' WHERE user_id=:key"), dict(key=case["actor"].user_id))
    elif fault == "epoch":
        db.execute(text("UPDATE hoimsystem_users SET token_invalid_before=:clock WHERE user_id=:key"), dict(key=case["actor"].user_id, clock=dt.datetime.now(dt.UTC).replace(tzinfo=None)))
    else:
        case["config"].enabled = 0
        db.flush()
    columns, observer = observe_bodies(db)
    try:
        with pytest.raises(HTTPException) as error:
            results.stage_result(db, case["actor"], claim, draft(source.model_dump(mode="json")), dispatch_event_id=dispatch.dispatch_event_id, usage=usage(11, None, True), latency_ms=3)
        assert error.value.status_code in {403, 409}
        terminal = r.stage_terminal(db, claim, dispatch_event_id=dispatch.dispatch_event_id, usage=usage(11, None, True), status="failed", error_code="TRAINING_CURRENT_STATE_CHANGED", latency_ms=3)
        assert terminal.usage.input_tokens == 11 and terminal.usage.output_tokens is None and terminal.status == "failed"
    finally:
        event.remove(db.get_bind(), "after_cursor_execute", observer)
    assert_zero_bodies(columns)
    actual = a.technical_attempt(db, claim)
    assert r.read_receipt(db, actual) == terminal and db.query(AITrainingRunResult).filter_by(run_id=key).count() == 0


def test_actual_unclaimed_failure_has_specific_zero_usage_without_synthetic_claim_or_source_body(stored):
    case, key = stored
    db = case["db"]
    reviews.revoke_review(db, case["author"], case["review"]["review_id"], dict(revision=1, reason="排队期间明确撤回课程模型范围"))
    columns, observer = observe_bodies(db)
    try:
        receipt = r.stage_unclaimed_failure(db, key, error_code="TASK_NO_LONGER_AUTHORIZED")
        actual = a.technical_header(db, key)
        assert r.read_receipt(db, actual) == receipt
    finally:
        event.remove(db.get_bind(), "after_cursor_execute", observer)
    assert_zero_bodies(columns)
    assert receipt.claim_event_id is receipt.dispatch_event_id is receipt.lease_token is None
    assert receipt.usage.model_dump(mode="json") == usage(0, 0, False)
    assert actual.artifact["claimed_at"] is None and actual.header["start_time"] is None
    assert r.stage_unclaimed_failure(db, key, error_code="TASK_NO_LONGER_AUTHORIZED") is None


@pytest.mark.parametrize("mode", ["undispatched", "interrupted", "wrong_delivery"])
def test_exact_dispatch_ownership_unknown_recovery_and_proven_unattempted_are_distinct(stored, mode):
    case, key = stored
    db = case["db"]
    claim = a.stage_claim(db, case["actor"], key)
    dispatch = a.stage_dispatch(db, case["actor"], claim) if mode != "undispatched" else None
    before = counts(db)
    if mode == "wrong_delivery":
        assert r.stage_terminal(db, claim, dispatch_event_id=None, usage=usage(0, 0, False), status="failed", error_code="TASK_NO_LONGER_AUTHORIZED", latency_ms=0) is None
        assert counts(db) == before
        return
    known = usage(None, None, None) if mode == "interrupted" else usage(0, 0, False)
    receipt = r.stage_terminal(db, claim, dispatch_event_id=dispatch.dispatch_event_id if dispatch else None, usage=known, status="failed", error_code="WORKER_INTERRUPTED", latency_ms=0)
    assert receipt.usage.model_dump(mode="json") == known and r.read_receipt(db, a.technical_attempt(db, claim)) == receipt


@pytest.mark.parametrize("fault", ["wrong_quote", "model_regrade", "different_source", "unattempted", "foreign_dispatch"])
def test_invalid_content_or_unowned_attempt_cannot_create_accepted_result(stored, fault):
    case, key, claim, dispatch, source = dispatched(stored)
    db, value = case["db"], draft(source.model_dump(mode="json"))
    reported, dispatch_id = usage(11, 7, True), dispatch.dispatch_event_id
    if fault == "wrong_quote":
        value["explanations"][0]["evidence"][0]["quote"] = "未受审的答案解析"
    elif fault == "model_regrade":
        value["matching_count"] = 0
    elif fault == "different_source":
        value["source_sha256"] = "0" * 64
    elif fault == "unattempted":
        reported = usage(0, 0, False)
    else:
        dispatch_id += 1
    before = counts(db)
    if fault == "foreign_dispatch":
        assert results.stage_result(db, case["actor"], claim, value, dispatch_event_id=dispatch_id, usage=reported, latency_ms=1) is None
    else:
        with pytest.raises(HTTPException) as error:
            results.stage_result(db, case["actor"], claim, value, dispatch_event_id=dispatch_id, usage=reported, latency_ms=1)
        assert error.value.status_code == 409
    assert counts(db) == before


@pytest.mark.parametrize("fault", ["reference", "owner", "config"])
def test_actual_after_result_insert_mutation_rolls_back_result_accept_usage_and_source_change(stored, fault):
    case, key, claim, dispatch, source = dispatched(stored)
    db = case["db"]
    before = counts(db)
    document_id, owner_id = case["documents"][0].document_id, case["actor"].user_id
    change = (
        "UPDATE hoimsystem_ai_knowledge_document SET status='retired' WHERE document_id='" + document_id + "';"
        if fault == "reference"
        else "UPDATE hoimsystem_users SET user_role='admin' WHERE user_id=" + str(owner_id) + ";"
        if fault == "owner"
        else "UPDATE hoimsystem_ai_feature_config SET enabled=0 WHERE feature_key='clinical_training';"
    )
    trigger = "training_after_result_insert_" + fault
    db.execute(text("CREATE TEMP TRIGGER " + trigger + " AFTER INSERT ON hoimsystem_ai_training_run_result BEGIN " + change + " END"))
    db.commit()
    try:
        with pytest.raises(HTTPException) as error:
            results.stage_result(db, case["actor"], claim, draft(source.model_dump(mode="json")), dispatch_event_id=dispatch.dispatch_event_id, usage=usage(11, 7, True), latency_ms=1)
        assert error.value.status_code in {403, 409}
        db.rollback()
        assert counts(db) == before
        actual = a.technical_attempt(db, claim)
        assert actual.header["status"] == "running" and actual.artifact["usage_event_id"] is None
        assert db.execute(text("SELECT status FROM hoimsystem_ai_knowledge_document WHERE document_id=:key"), dict(key=document_id)).scalar_one() == "published"
    finally:
        db.execute(text("DROP TRIGGER IF EXISTS " + trigger))
        db.commit()
