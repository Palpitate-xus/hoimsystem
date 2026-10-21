"""Stopping an already retained task does not grant current source execution."""

import pytest
from fastapi import HTTPException
from sqlalchemy import inspect, text

from app.ai import satisfaction_execution as execution
from app.ai import satisfaction_receipts as receipts
from app.ai.models import AIAuditEvent, AIRun
from app.ai.satisfaction_artifact_models import AISatisfactionRunArtifact
from app.ai.satisfaction_sources import authorize_case, revoke_case
from app.models import User
from tests.test_ai_satisfaction_runtime import prepared
from tests.test_ai_satisfaction_runtime import runtime_case as runtime_case  # noqa: F401
from tests.test_ai_satisfaction_sources import BASIS
from tests.test_ai_satisfaction_sources import satisfaction_case as satisfaction_case  # noqa: F401


def invalidate(case, item, reason):
    db = case["db"]
    if reason == "revoked":
        revoke_case(db, case["super_admin_user"], item["case_id"], {"expected_revision": 2, "basis_note": BASIS})
    else:
        db.execute(text("UPDATE hoimsystem_review SET comment='current original changed after queue' WHERE review_id=:identifier"), {"identifier": item["review_id"]})
        db.commit()


@pytest.mark.parametrize("claimed", [False, True])
@pytest.mark.parametrize("reason", ["revoked", "changed_original"])
def test_actual_super_can_only_stop_queued_or_running_tasks_after_source_becomes_unavailable(runtime_case, claimed, reason):
    case, db = runtime_case, runtime_case["db"]
    item = prepared(case, claimed=claimed)
    invalidate(case, item, reason)
    with pytest.raises(HTTPException) as ordinary:
        execution.cancel_satisfaction_run(db, case["admin_user"], item["run_id"])
    assert ordinary.value.status_code == 409
    assert db.get(AIRun, item["run_id"]).status == ("running" if claimed else "queued")
    execution.cancel_satisfaction_run(db, case["super_admin_user"], item["run_id"])
    run = db.get(AIRun, item["run_id"])
    result, usage = receipts.load_terminal(db, run)
    assert run.status == "cancelled" and result is None and run.result_json == "{}"
    artifact = db.get(AISatisfactionRunArtifact, item["run_id"])
    assert artifact.result_json is None and artifact.receipt_event_id is None
    if claimed:
        assert run.lease_token == item["lease"] and run.latency_ms is None
        assert usage == receipts.usage() and artifact.usage_event_id is None
    else:
        assert run.lease_token is None and run.start_time is None and run.latency_ms == 0
        assert usage == receipts.usage(0, 0, False) and artifact.usage_event_id is not None
    with pytest.raises(HTTPException) as blocked:
        authorize_case(db, case["super_admin_user"], item["case_id"])
    assert blocked.value.status_code == 409
    assert execution.claim_satisfaction_run(db, item["run_id"]) is None


def test_actual_cancel_audit_demoting_super_rolls_back_cancel_receipt_and_actor_mutation(runtime_case):
    case, db = runtime_case, runtime_case["db"]
    item = prepared(case, claimed=False)
    invalidate(case, item, "revoked")
    uid = inspect(case["super_admin_user"]).identity[0]
    before = db.query(AIAuditEvent).count()
    db.execute(
        text(
            f"CREATE TRIGGER satisfaction_cancel_epoch AFTER INSERT ON hoimsystem_ai_audit_event WHEN NEW.action='run.satisfaction.cancel' BEGIN UPDATE hoimsystem_users SET user_role='admin' WHERE user_id={uid}; END"
        )
    )
    db.commit()
    try:
        with pytest.raises(HTTPException):
            execution.cancel_satisfaction_run(db, case["super_admin_user"], item["run_id"])
        assert db.get(AIRun, item["run_id"]).status == "queued"
        assert db.get(AISatisfactionRunArtifact, item["run_id"]).usage_event_id is None
        assert db.query(AIAuditEvent).count() == before and db.get(User, uid).user_role == "super_admin"
    finally:
        db.rollback()
        db.execute(text("DROP TRIGGER satisfaction_cancel_epoch"))
        db.commit()


def test_super_cancel_does_not_bypass_own_immutable_task_proof(runtime_case):
    case, db = runtime_case, runtime_case["db"]
    item = prepared(case, claimed=False)
    invalidate(case, item, "revoked")
    db.execute(text("UPDATE hoimsystem_ai_run SET evidence_json='[]' WHERE run_id=:identifier"), {"identifier": item["run_id"]})
    db.commit()
    with pytest.raises(HTTPException) as error:
        execution.cancel_satisfaction_run(db, case["super_admin_user"], item["run_id"])
    assert error.value.status_code == 409 and db.get(AIRun, item["run_id"]).status == "queued"
    assert db.get(AISatisfactionRunArtifact, item["run_id"]).usage_event_id is None
