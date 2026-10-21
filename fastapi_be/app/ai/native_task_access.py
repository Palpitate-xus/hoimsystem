"""Coordinate native authorization locks before loading private task TEXT."""

from app.ai.charge_reconciliation_run_models import AIChargeRunArtifact
from app.ai.models import AIRun
from app.ai.satisfaction_artifact_models import AISatisfactionRunArtifact


def lock_directory_gates(db):
    """A mixed directory always takes Gates before current actor/Run locks."""
    from app.ai.charge_reconciliation_write_guard import lock_charge_gate
    from app.ai.satisfaction_write_guard import lock_satisfaction_gate

    lock_charge_gate(db)
    lock_satisfaction_gate(db)


def guard_private_task_read(db, user, run_id):
    # These are immutable identity locators, not authorization or current-source
    # reads. Run and Artifact are created atomically: a consistent snapshot
    # seeing a native Run also sees its identity. Do not lock Anchor before Gate.
    with db.no_autoflush:
        row = db.query(AIRun.feature_key, AIRun.requested_by).filter_by(run_id=run_id).one_or_none()
        charge = db.query(AIChargeRunArtifact.run_id).filter_by(run_id=run_id).first()
        satisfaction = db.query(AISatisfactionRunArtifact.run_id).filter_by(run_id=run_id).first()
    if charge is not None or row is not None and row.feature_key == "charge_reconciliation":
        from app.ai.charge_reconciliation_write_guard import lock_charge_gate

        lock_charge_gate(db)
    if satisfaction is not None or row is not None and row.feature_key == "feedback_analysis":
        from fastapi import HTTPException

        from app.ai.satisfaction_runtime import current_actor

        actor = current_actor(db, user)
        if row is not None and actor.user_role != "super_admin" and row.requested_by != actor.user_id:
            raise HTTPException(403, "没有读取该评价任务的权限")
    from app.ai.document_extraction_runtime import guard_document_run_id

    # Document authorization must still precede fetching its original text.
    # Native callers subsequently recheck full current actor/source/FK proofs.
    guard_document_run_id(db, user, run_id)
