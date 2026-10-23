"""Actual nullable usage SQL after Source loss, not worker/HTTP integration."""

import datetime as dt
import json

import pytest
from fastapi import HTTPException
from sqlalchemy import inspect, text

from app.ai import rca_evidence_attempts as attempts
from app.ai import rca_evidence_grants as grants
from app.ai import rca_evidence_receipts as receipts
from app.ai import rca_evidence_storage as storage
from app.ai.models import AIAuditEvent, AIRun
from app.ai.rca_evidence_run_models import AIRcaEvidenceRunArtifact, AIRcaEvidenceRunResult
from tests.ai_admin_usage_assertions import assert_exact_usage_event
from tests.test_ai_rca_evidence_attempts import claimed
from tests.test_ai_rca_evidence_grants import NOW, cas
from tests.test_ai_rca_evidence_grants import grant_case as grant_case
from tests.test_ai_rca_evidence_sources import seed_rca
from tests.test_ai_rca_evidence_storage import denied, no_task_text, task_counts


@pytest.fixture(autouse=True)
def clean_receipt_trigger(db_session):
    yield
    db_session.rollback()
    db_session.execute(text("DROP TRIGGER IF EXISTS rca_receipt_fault"))
    db_session.commit()


def dispatched(case):
    proof, value = claimed(case)
    attempts.stage_dispatch(case["db"], case["actor"], proof)
    case["db"].commit()
    return proof, value


def usage(inputs=11, outputs=13, attempted=True):
    return {"input_tokens": inputs, "output_tokens": outputs, "complete": inputs is not None and outputs is not None, "model_call_attempted": attempted}


def settle(db, proof, **changes):
    identifier = proof["run_id"] if isinstance(proof, dict) else proof.run_id
    dispatched_id = db.query(AIRcaEvidenceRunArtifact.dispatch_event_id).filter_by(run_id=identifier).scalar()
    return receipts.stage_terminal(db, proof, **{"dispatch_event_id": dispatched_id, "usage": usage(), "status": "failed", "error_code": "RCA_PROVIDER_ERROR", "latency_ms": 27, **changes})


@pytest.mark.parametrize("loss", ["event_grant", "role", "token", "patient_association", "new_rca"])
def test_original_lease_records_actual_paid_usage_after_loss_without_reading_task_or_restoring_content(grant_case, loss):
    case, db = grant_case, grant_case["db"]
    proof, value = dispatched(case)
    actor_id = inspect(case["actor"]).identity[0]
    if loss == "event_grant":
        record = grants.grant_detail(db, case["actor"], value.binding.event_grant.grant_id)
        grants.revoke_grant(db, case["actor"], record.identity.grant_id, cas(record))
    elif loss == "role":
        db.execute(text("UPDATE hoimsystem_users SET user_role='admin' WHERE user_id=:id"), {"id": actor_id})
    elif loss == "token":
        db.execute(text("UPDATE hoimsystem_users SET token_invalid_before='2026-10-21 12:00:01.123456' WHERE user_id=:id"), {"id": actor_id})
    elif loss == "patient_association":
        db.execute(text("UPDATE hoimsystem_adverse_event SET patient_id=NULL WHERE event_id=:id"), {"id": case["event_id"]})
    else:
        seed_rca(case)
    db.commit()
    result, columns = no_task_text(db, lambda: settle(db, proof, error_code="RCA_SOURCE_CHANGED"))
    assert not columns and result.usage.input_tokens == 11 and result.usage.output_tokens == 13
    assert result.status == "failed" and result.result_hash is None
    db.commit()
    actual, columns = no_task_text(db, lambda: receipts.technical_attempt(db, proof))
    assert not columns
    loaded, columns = no_task_text(db, lambda: receipts.read_receipt(db, actual))
    assert not columns and loaded == result
    assert_exact_usage_event(db, proof.run_id, "rca", result.usage.model_dump(mode="json"))
    assert db.query(AIRcaEvidenceRunResult).count() == 0
    row = db.get(AIRcaEvidenceRunArtifact, proof.run_id)
    assert row.usage_event_id not in {row.create_event_id, row.claim_event_id, row.dispatch_event_id}
    audit = db.get(AIAuditEvent, row.usage_event_id)
    assert audit.action == "rca_run.usage" and json.loads(audit.detail_json)["usage"] == usage()
    denied(db, lambda: storage.load_task(db, case["actor"], proof.run_id), 409 if loss == "new_rca" else 403)


@pytest.mark.parametrize("inputs,outputs", [(None, None), (11, None), (None, 13), (0, 0)])
def test_received_components_remain_nullable_and_zero_is_only_a_reported_zero(grant_case, inputs, outputs):
    case, db = grant_case, grant_case["db"]
    proof, _ = dispatched(case)
    result = settle(db, proof, usage=usage(inputs, outputs))
    db.commit()
    assert (result.usage.input_tokens, result.usage.output_tokens) == (inputs, outputs)
    assert result.usage.complete is (inputs is not None and outputs is not None)
    actual = receipts.read_receipt(db, receipts.technical_attempt(db, proof))
    assert actual == result
    # The old nonnullable counters remain compatibility placeholders. They are
    # explicitly not the nullable public receipt or evidence of a zero bill.
    run = db.query(AIRun.input_tokens, AIRun.output_tokens, AIRun.finish_time).filter_by(run_id=proof.run_id).one()
    assert tuple(run) == (inputs or 0, outputs or 0, NOW.replace(microsecond=0))
    assert receipts.receipt_piece(db, case["actor"], proof.run_id)["data"]["usage"] == usage(inputs, outputs)
    before = task_counts(db)
    assert settle(db, proof, usage=usage(99, 88)) is None
    assert task_counts(db) == before


@pytest.mark.parametrize("has_dispatch", [False, True])
def test_interruption_unknown_requires_committed_dispatch_while_known_unattempted_is_zero(grant_case, has_dispatch):
    case, db = grant_case, grant_case["db"]
    proof, _ = dispatched(case) if has_dispatch else claimed(case)
    if has_dispatch:
        result = settle(db, proof, usage=usage(None, None, None), error_code="WORKER_INTERRUPTED")
        assert result.usage.model_call_attempted is None and result.usage.complete is False
        assert result.dispatch_event_id is not None
    else:
        before = task_counts(db)
        with pytest.raises(HTTPException) as failure:
            settle(db, proof, usage=usage(None, None, None), error_code="WORKER_INTERRUPTED")
        assert failure.value.status_code == 409 and task_counts(db) == before
        result = settle(db, proof, usage=usage(0, 0, False), error_code="RCA_REQUEST_REJECTED")
        assert result.usage.model_call_attempted is False and result.dispatch_event_id is None
    db.commit()
    assert receipts.read_receipt(db, receipts.technical_attempt(db, proof)) == result


def test_committed_dispatch_does_not_falsely_prove_that_http_was_attempted(grant_case):
    case, db = grant_case, grant_case["db"]
    proof, _ = dispatched(case)
    result = settle(db, proof, usage=usage(0, 0, False), error_code="RCA_REQUEST_REJECTED")
    assert result.dispatch_event_id is not None and result.usage.model_call_attempted is False


def test_pending_cancellation_preserves_unknown_interrupted_usage_without_accepting_a_body(grant_case):
    case, db = grant_case, grant_case["db"]
    proof, _ = dispatched(case)
    # This simulates the already committed cancellation header. Its user route
    # and independent cancel audit are a later integration boundary.
    db.execute(text("UPDATE hoimsystem_ai_run SET status='cancelled' WHERE run_id=:run"), {"run": proof.run_id})
    db.commit()
    result = settle(db, proof, usage=usage(None, None, None), error_code="WORKER_INTERRUPTED")
    db.commit()
    assert result.status == "cancelled" and result.error_code == "WORKER_INTERRUPTED"
    assert result.usage.model_call_attempted is None and result.result_hash is None
    assert receipts.read_receipt(db, receipts.technical_attempt(db, proof)) == result


def test_actual_clock_reversal_is_rejected_instead_of_fabricating_an_end_time(grant_case, monkeypatch):
    case, db = grant_case, grant_case["db"]
    proof, _ = dispatched(case)
    before = task_counts(db)
    monkeypatch.setattr(grants, "utcnow", lambda: NOW - dt.timedelta(microseconds=1))
    with pytest.raises(HTTPException) as failure:
        settle(db, proof)
    assert failure.value.status_code == 409 and task_counts(db) == before


@pytest.mark.parametrize("duplicate_dispatch", [None, 2147483647])
def test_second_delivery_source_failure_cannot_settle_the_original_dispatch_even_with_same_claim_lease(grant_case, duplicate_dispatch):
    case, db = grant_case, grant_case["db"]
    proof, value = dispatched(case)
    original_dispatch_id = db.query(AIRcaEvidenceRunArtifact.dispatch_event_id).filter_by(run_id=proof.run_id).scalar()
    record = grants.grant_detail(db, case["actor"], value.binding.event_grant.grant_id)
    grants.revoke_grant(db, case["actor"], record.identity.grant_id, cas(record))
    db.commit()
    before = task_counts(db)
    result, columns = no_task_text(db, lambda: settle(db, proof, dispatch_event_id=duplicate_dispatch, usage=usage(0, 0, False), error_code="RCA_SOURCE_CHANGED"))
    assert result is None and not columns and task_counts(db) == before
    assert db.query(AIRun.status).filter_by(run_id=proof.run_id).scalar() == "running"
    assert db.query(AIRcaEvidenceRunArtifact.usage_event_id).filter_by(run_id=proof.run_id).scalar() is None
    actual = settle(db, proof, dispatch_event_id=original_dispatch_id)
    assert actual.usage.model_dump(mode="json") == usage() and actual.status == "failed"


def test_dispatch_marker_is_an_actual_pk_not_a_bool(grant_case):
    case, db = grant_case, grant_case["db"]
    proof, _ = dispatched(case)
    before = task_counts(db)
    with pytest.raises(HTTPException) as failure:
        settle(db, proof, dispatch_event_id=True)
    assert failure.value.status_code == 409 and task_counts(db) == before


@pytest.mark.parametrize("fault", ["claim_pk", "lease", "usage_pk", "terminal_header"])
def test_specific_lease_audit_and_terminal_header_corruption_never_silently_relabels_a_receipt(grant_case, fault):
    case, db = grant_case, grant_case["db"]
    proof, _ = dispatched(case)
    if fault in {"claim_pk", "lease"}:
        raw = proof.model_dump(mode="json")
        raw["claim_event_id" if fault == "claim_pk" else "lease_token"] = proof.claim_event_id + 100 if fault == "claim_pk" else "00000000-0000-0000-0000-000000000099"

        def callback():
            return settle(db, raw)
    else:
        settle(db, proof)
        db.commit()
        if fault == "usage_pk":
            wrong = db.query(AIAuditEvent.event_id).filter_by(action="rca_grant.create").first()[0]
            db.execute(text("UPDATE hoimsystem_ai_rca_evidence_run_artifact SET usage_event_id=:wrong WHERE run_id=:run"), {"run": proof.run_id, "wrong": wrong})
        else:
            db.execute(text("UPDATE hoimsystem_ai_run SET input_tokens=999 WHERE run_id=:run"), {"run": proof.run_id})
        db.commit()

        def callback():
            return receipts.read_receipt(db, receipts.technical_attempt(db, proof))

    with pytest.raises(HTTPException) as failure:
        callback()
    assert failure.value.status_code == 409


@pytest.mark.parametrize("fault", ["audit_reject", "audit_tamper", "run_header", "artifact_lease"])
def test_actual_usage_sql_fault_rolls_back_terminal_status_specific_receipt_and_artifact_pointer(grant_case, fault):
    case, db = grant_case, grant_case["db"]
    proof, _ = dispatched(case)
    if fault == "audit_reject":
        sql = "CREATE TRIGGER rca_receipt_fault BEFORE INSERT ON hoimsystem_ai_audit_event WHEN NEW.action='rca_run.usage' BEGIN SELECT RAISE(ABORT,'synthetic usage audit rejection'); END"
    elif fault == "audit_tamper":
        sql = "CREATE TRIGGER rca_receipt_fault AFTER INSERT ON hoimsystem_ai_audit_event WHEN NEW.action='rca_run.usage' BEGIN UPDATE hoimsystem_ai_audit_event SET detail_json='{}' WHERE event_id=NEW.event_id; END"
    elif fault == "run_header":
        sql = "CREATE TRIGGER rca_receipt_fault AFTER UPDATE ON hoimsystem_ai_rca_evidence_run_artifact WHEN NEW.usage_event_id IS NOT NULL BEGIN UPDATE hoimsystem_ai_run SET input_tokens=999 WHERE run_id=NEW.run_id; END"
    else:
        sql = "CREATE TRIGGER rca_receipt_fault AFTER UPDATE ON hoimsystem_ai_rca_evidence_run_artifact WHEN NEW.usage_event_id IS NOT NULL BEGIN UPDATE hoimsystem_ai_run SET lease_token='00000000-0000-0000-0000-000000000099' WHERE run_id=NEW.run_id; END"
    before = task_counts(db)
    db.execute(text(sql))
    db.commit()
    with pytest.raises(HTTPException) as failure:
        settle(db, proof)
    assert failure.value.status_code == 409 and task_counts(db) == before
    assert db.query(AIRun.status).filter_by(run_id=proof.run_id).scalar() == "running"
    assert db.query(AIRcaEvidenceRunArtifact.usage_event_id).filter_by(run_id=proof.run_id).scalar() is None
