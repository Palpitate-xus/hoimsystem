"""Actual SQL claim/dispatch PKs and inert duplicates; no worker/HTTP call yet."""

import json

import pytest
from fastapi import HTTPException
from sqlalchemy import inspect, text

from app.ai import rca_evidence_attempts as attempts
from app.ai import rca_evidence_grants as grants
from app.ai import rca_evidence_storage as storage
from app.ai.models import AIAuditEvent, AIRun
from app.ai.rca_evidence_run_models import AIRcaEvidenceRunArtifact
from tests.test_ai_rca_evidence_grants import NOW, cas
from tests.test_ai_rca_evidence_grants import grant_case as grant_case
from tests.test_ai_rca_evidence_storage import no_task_text, stage, task_counts


@pytest.fixture(autouse=True)
def clean_phase_trigger(db_session):
    yield
    db_session.rollback()
    db_session.execute(text("DROP TRIGGER IF EXISTS rca_phase_fault"))
    db_session.commit()


def claimed(case):
    stored, value = stage(case)
    identifier = inspect(stored.run).identity[0]
    proof = attempts.stage_claim(case["db"], case["actor"], identifier)
    case["db"].commit()
    return proof, value


def test_actual_claim_then_single_dispatch_are_different_specific_audit_rows(grant_case):
    case, db = grant_case, grant_case["db"]
    proof, _ = claimed(case)
    first = proof.model_dump(mode="json")
    row = db.get(AIRcaEvidenceRunArtifact, proof.run_id)
    assert row.claim_lease == proof.lease_token and row.claim_event_id == proof.claim_event_id != row.create_event_id
    audit = db.get(AIAuditEvent, proof.claim_event_id)
    assert audit.action == "rca_run.claim" and json.loads(audit.detail_json)["lease_token"] == proof.lease_token
    assert row.claimed_at == NOW and db.get(AIRun, proof.run_id).start_time == NOW.replace(microsecond=0)
    dispatched = attempts.stage_dispatch(db, case["actor"], first)
    db.commit()
    assert dispatched.schema_version == "rca_evidence_dispatch_v1"
    assert len({dispatched.create_event_id, dispatched.claim_event_id, dispatched.dispatch_event_id}) == 3
    assert db.get(AIAuditEvent, dispatched.dispatch_event_id).action == "rca_run.dispatch"
    stable = task_counts(db)
    assert attempts.stage_dispatch(db, case["actor"], first) is None
    db.rollback()
    assert task_counts(db) == stable
    loaded = storage.load_task(db, case["actor"], proof.run_id)
    assert attempts.claim_proof(db, loaded) == proof and attempts.dispatch_proof(db, loaded) == dispatched


def test_duplicate_claim_after_source_revocation_never_kills_or_reads_the_first_owner(grant_case):
    case, db = grant_case, grant_case["db"]
    proof, value = claimed(case)
    purpose = grants.grant_detail(db, case["actor"], value.binding.event_grant.grant_id)
    grants.revoke_grant(db, case["actor"], purpose.identity.grant_id, cas(purpose))
    db.commit()
    before = task_counts(db)
    result, fields = no_task_text(db, lambda: attempts.stage_claim(db, case["actor"], proof.run_id))
    assert result is None and not fields and task_counts(db) == before
    run = db.query(AIRun.status, AIRun.lease_token).filter_by(run_id=proof.run_id).one()
    assert tuple(run) == ("running", proof.lease_token)


@pytest.mark.parametrize("axis", ["wrong_provided_audit", "wrong_stored_audit", "wrong_lease", "epoch_loss"])
def test_dispatch_requires_exact_original_claim_pk_and_current_epoch(grant_case, axis):
    case, db = grant_case, grant_case["db"]
    proof, value = claimed(case)
    raw = proof.model_dump(mode="json")
    if axis == "wrong_provided_audit":
        raw["claim_event_id"] += 100
    elif axis == "wrong_stored_audit":
        purpose = grants.grant_detail(db, case["actor"], value.binding.event_grant.grant_id)
        db.execute(text("UPDATE hoimsystem_ai_rca_evidence_run_artifact SET claim_event_id=:id WHERE run_id=:run"), {"id": purpose.governance.created_audit_event_id, "run": proof.run_id})
        db.commit()
    elif axis == "wrong_lease":
        raw["lease_token"] = "00000000-0000-0000-0000-000000000099"
    else:
        db.execute(text("UPDATE hoimsystem_users SET token_invalid_before='2026-10-21 12:00:02.123456' WHERE user_id=:id"), {"id": inspect(case["actor"]).identity[0]})
        db.commit()
        db.refresh(case["actor"])
    before = task_counts(db)
    with pytest.raises(HTTPException) as failure:
        attempts.stage_dispatch(db, case["actor"], raw)
    assert failure.value.status_code == (403 if axis == "epoch_loss" else 409)
    assert task_counts(db) == before
    assert db.get(AIRcaEvidenceRunArtifact, proof.run_id).dispatch_event_id is None
    assert db.get(AIRun, proof.run_id).status == "running"


@pytest.mark.parametrize("phase", ["claim", "dispatch"])
@pytest.mark.parametrize("fault", ["reject_audit", "wrong_audit", "actor", "lease"])
def test_actual_phase_sql_trigger_rolls_back_run_artifact_and_exact_audit(grant_case, phase, fault):
    case, db = grant_case, grant_case["db"]
    if phase == "claim":
        stored, _ = stage(case)
        identifier = inspect(stored.run).identity[0]

        def callback():
            return attempts.stage_claim(db, case["actor"], identifier)

        column = "claim_event_id"
    else:
        proof, _ = claimed(case)
        identifier = proof.run_id

        def callback():
            return attempts.stage_dispatch(db, case["actor"], proof)

        column = "dispatch_event_id"
    if fault == "reject_audit":
        sql = f"CREATE TRIGGER rca_phase_fault BEFORE INSERT ON hoimsystem_ai_audit_event WHEN NEW.action='rca_run.{phase}' BEGIN SELECT RAISE(ABORT,'actual synthetic audit reject'); END"
    elif fault == "wrong_audit":
        sql = f"CREATE TRIGGER rca_phase_fault AFTER INSERT ON hoimsystem_ai_audit_event WHEN NEW.action='rca_run.{phase}' BEGIN UPDATE hoimsystem_ai_audit_event SET detail_json='{{}}' WHERE event_id=NEW.event_id; END"
    elif fault == "actor":
        sql = f"CREATE TRIGGER rca_phase_fault AFTER UPDATE ON hoimsystem_ai_rca_evidence_run_artifact WHEN NEW.{column} IS NOT NULL AND OLD.{column} IS NULL BEGIN UPDATE hoimsystem_users SET user_role='admin' WHERE user_id={inspect(case['actor']).identity[0]}; END"
    else:
        sql = f"CREATE TRIGGER rca_phase_fault AFTER UPDATE ON hoimsystem_ai_rca_evidence_run_artifact WHEN NEW.{column} IS NOT NULL AND OLD.{column} IS NULL BEGIN UPDATE hoimsystem_ai_run SET lease_token='00000000-0000-0000-0000-000000000099' WHERE run_id=NEW.run_id; END"
    before = task_counts(db)
    expected = db.query(AIRun.status, AIRun.lease_token, AIRun.start_time).filter_by(run_id=identifier).one()
    db.execute(text(sql))
    db.commit()
    try:
        with pytest.raises(HTTPException) as failure:
            callback()
        assert failure.value.status_code in {403, 409}
        assert task_counts(db) == before
        assert tuple(db.query(AIRun.status, AIRun.lease_token, AIRun.start_time).filter_by(run_id=identifier).one()) == tuple(expected)
        assert getattr(db.get(AIRcaEvidenceRunArtifact, identifier), column) is None
    finally:
        db.rollback()
        db.execute(text("DROP TRIGGER rca_phase_fault"))
        db.commit()
