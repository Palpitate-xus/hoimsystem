"""Coordinate native authorization locks before loading private task TEXT."""

from app.ai.charge_reconciliation_run_models import AIChargeRunArtifact
from app.ai.models import AIRun


def guard_private_task_read(db, user, run_id):
    # These are immutable identity locators, not authorization or current-source
    # reads. Run and Artifact are created atomically: a consistent snapshot
    # seeing a native Run also sees its identity. Do not lock Anchor before Gate.
    with db.no_autoflush:
        row = db.query(AIRun.feature_key).filter_by(run_id=run_id).one_or_none()
        charge = db.query(AIChargeRunArtifact.run_id).filter_by(run_id=run_id).first()
    if charge is not None or row is not None and row.feature_key == "charge_reconciliation":
        from app.ai.charge_reconciliation_write_guard import lock_charge_gate

        lock_charge_gate(db)
    from app.ai.document_extraction_runtime import guard_document_run_id

    # Document authorization must still precede fetching its original text.
    # Native callers subsequently recheck full current actor/source/FK proofs.
    guard_document_run_id(db, user, run_id)
