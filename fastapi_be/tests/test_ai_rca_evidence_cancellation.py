"""Current Super stop/known-zero SQL, no Source access or inference implied."""

import json
import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import inspect, text

from app.ai import rca_evidence_cancellation as cancellation
from app.ai import rca_evidence_grants as grants
from app.ai import rca_evidence_receipts as receipts
from app.ai.models import AIAuditEvent, AIRun
from app.ai.rca_evidence_run_models import AIRcaEvidenceRunArtifact
from app.models import User
from tests.test_ai_rca_evidence_attempts import claimed
from tests.test_ai_rca_evidence_grants import cas
from tests.test_ai_rca_evidence_grants import grant_case as grant_case
from tests.test_ai_rca_evidence_receipts import dispatched, settle, usage
from tests.test_ai_rca_evidence_storage import denied, no_task_text, stage, task_counts


@pytest.fixture(autouse=True)
def clean_cancel_trigger(db_session):
    yield
    db_session.rollback()
    db_session.execute(text("DROP TRIGGER IF EXISTS rca_cancel_fault"))
    db_session.commit()


def phase(case, name):
    if name == "queued":
        stored, value = stage(case)
        return inspect(stored.run).identity[0], None, value
    proof, value = dispatched(case) if name == "dispatched" else claimed(case)
    return proof.run_id, proof, value


def other_super(db):
    actor = User(username="rca_stop_" + uuid.uuid4().hex[:12], password="synthetic-unused", user_role="super_admin")
    db.add(actor)
    db.commit()
    return actor


@pytest.mark.parametrize("name", ["queued", "claimed", "dispatched"])
@pytest.mark.parametrize("lost_source", [False, True])
def test_actual_explicit_super_without_source_grants_can_stop_only_with_short_ack_and_correct_usage_state(grant_case, name, lost_source):
    case, db = grant_case, grant_case["db"]
    identifier, proof, value = phase(case, name)
    actor = other_super(db)  # No event or patient-purpose grant: no body rights.
    if lost_source:
        record = grants.grant_detail(db, case["actor"], value.binding.event_grant.grant_id)
        grants.revoke_grant(db, case["actor"], record.identity.grant_id, cas(record))
        db.commit()
    result, columns = no_task_text(db, lambda: cancellation.stage_cancel(db, actor, identifier))
    assert not columns and result.status == "cancelled" and result.receipt_pending is (name == "dispatched")
    assert set(result.model_dump()) == {"schema_version", "run_id", "status", "cancel_event_id", "usage_event_id", "receipt_pending", "automatic_legacy_write"}
    db.commit()
    event = db.get(AIAuditEvent, result.cancel_event_id)
    assert event.actor_id == inspect(actor).identity[0] and event.action == "rca_run.cancel" and event.target == identifier
    assert json.loads(event.detail_json)["requested_by"] == value.binding.requested_by
    actual, columns = no_task_text(db, lambda: receipts.technical_header(db, identifier))
    assert not columns
    receipt = receipts.read_receipt(db, actual)
    if name == "dispatched":
        assert result.usage_event_id is None and receipt is None
        assert db.query(AIRun.latency_ms).filter_by(run_id=identifier).scalar() is None
        paid = settle(db, proof, usage=usage(11, None))
        db.commit()
        assert paid.status == "cancelled" and paid.error_code == "TASK_CANCELLED" and paid.usage.input_tokens == 11 and paid.usage.output_tokens is None
    else:
        assert result.usage_event_id is not None and receipt.usage.model_dump(mode="json") == usage(0, 0, False)
        assert receipt.claim_event_id is None if name == "queued" else receipt.claim_event_id == proof.claim_event_id
    denied(db, lambda: receipts.receipt_piece(db, actor, identifier), 403)
    before = task_counts(db)
    with pytest.raises(HTTPException) as repeated:
        cancellation.stage_cancel(db, actor, identifier)
    assert repeated.value.status_code == 409 and task_counts(db) == before


def test_unclaimed_current_source_loss_records_known_zero_without_task_body_and_a_raced_claim_is_inert(grant_case):
    case, db = grant_case, grant_case["db"]
    identifier, _, value = phase(case, "queued")
    assert receipts.receipt_piece(db, case["actor"], identifier)["data"] is None
    grant = grants.grant_detail(db, case["actor"], value.binding.event_grant.grant_id)
    grants.revoke_grant(db, case["actor"], grant.identity.grant_id, cas(grant))
    db.commit()
    receipt, columns = no_task_text(db, lambda: receipts.stage_unclaimed_terminal(db, identifier, status="failed", error_code="TASK_NO_LONGER_AUTHORIZED"))
    assert not columns and receipt.claim_event_id is receipt.dispatch_event_id is receipt.lease_token is None
    assert receipt.usage.model_dump(mode="json") == usage(0, 0, False)
    db.commit()
    assert receipts.read_receipt(db, receipts.technical_header(db, identifier)) == receipt
    # A different real task already claimed by an owner is never terminated by
    # this stale queue delivery's knowledge that it previously saw no claim.
    proof, _ = claimed(case)
    before = task_counts(db)
    result, columns = no_task_text(db, lambda: receipts.stage_unclaimed_terminal(db, proof.run_id, status="failed", error_code="TASK_NO_LONGER_AUTHORIZED"))
    assert result is None and not columns and task_counts(db) == before
    assert db.query(AIRun.status).filter_by(run_id=proof.run_id).scalar() == "running"


@pytest.mark.parametrize("fault", ["audit_reject", "audit_tamper", "role", "epoch", "header", "artifact"])
def test_actual_cancel_postflush_fault_rolls_back_cancel_audit_zero_receipt_and_header(grant_case, fault):
    case, db = grant_case, grant_case["db"]
    identifier, _, _ = phase(case, "queued")
    actor = other_super(db)
    actor_id = inspect(actor).identity[0]
    if fault == "audit_reject":
        sql = "CREATE TRIGGER rca_cancel_fault BEFORE INSERT ON hoimsystem_ai_audit_event WHEN NEW.action='rca_run.cancel' BEGIN SELECT RAISE(ABORT,'synthetic cancel audit reject'); END"
    elif fault == "audit_tamper":
        action = "UPDATE hoimsystem_ai_audit_event SET detail_json='{}' WHERE event_id=NEW.event_id;"
        sql = "CREATE TRIGGER rca_cancel_fault AFTER INSERT ON hoimsystem_ai_audit_event WHEN NEW.action='rca_run.cancel' BEGIN " + action + " END"
    else:
        if fault == "role":
            action = f"UPDATE hoimsystem_users SET user_role='admin' WHERE user_id={actor_id};"
        elif fault == "epoch":
            action = f"UPDATE hoimsystem_users SET token_invalid_before='2026-10-21 12:00:01.123456' WHERE user_id={actor_id};"
        elif fault == "header":
            action = "UPDATE hoimsystem_ai_run SET input_tokens=99 WHERE run_id=NEW.target;"
        else:
            action = "UPDATE hoimsystem_ai_rca_evidence_run_artifact SET source_hash='" + "e" * 64 + "' WHERE run_id=NEW.target;"
        sql = "CREATE TRIGGER rca_cancel_fault AFTER INSERT ON hoimsystem_ai_audit_event WHEN NEW.action='rca_run.cancel' BEGIN " + action + " END"
    before = task_counts(db)
    db.execute(text(sql))
    db.commit()
    with pytest.raises(HTTPException) as failure:
        cancellation.stage_cancel(db, actor, identifier)
    assert failure.value.status_code == (403 if fault in {"role", "epoch"} else 409)
    assert task_counts(db) == before and db.query(AIRun.status).filter_by(run_id=identifier).scalar() == "queued"
    assert db.query(AIRcaEvidenceRunArtifact.usage_event_id).filter_by(run_id=identifier).scalar() is None


def test_lost_actor_role_cannot_use_technical_stop_exception(grant_case):
    case, db = grant_case, grant_case["db"]
    identifier, _, _ = phase(case, "queued")
    db.execute(text("UPDATE hoimsystem_users SET user_role='admin' WHERE user_id=:id"), {"id": inspect(case["actor"]).identity[0]})
    db.commit()

    def attempt():
        with pytest.raises(HTTPException) as failure:
            cancellation.stage_cancel(db, case["actor"], identifier)
        assert failure.value.status_code == 403

    _, columns = no_task_text(db, attempt)
    assert not columns and db.query(AIRun.status).filter_by(run_id=identifier).scalar() == "queued"
