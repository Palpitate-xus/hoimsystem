"""Coordinate native authorization locks before loading private task TEXT."""


def lock_directory_gates(db):
    """A mixed directory always takes Gates before current actor/Run locks."""
    from app.ai.charge_reconciliation_write_guard import lock_charge_gate
    from app.ai.satisfaction_write_guard import lock_satisfaction_gate

    lock_charge_gate(db)
    lock_satisfaction_gate(db)


def guard_private_task_read(db, user, run_id):
    from app.ai.satisfaction_storage import guard_satisfaction_run_id

    # Global history and direct reads share the same Gate order. The current
    # opaque Artifact locator also detects tasks added after an old RR snapshot.
    lock_directory_gates(db)
    if guard_satisfaction_run_id(db, user, run_id, audit_only=user.user_role == "super_admin"):
        # Current Source authority has been established without task TEXT.
        return
    from app.ai.document_extraction_runtime import guard_document_run_id

    # Document authorization must still precede fetching its original text.
    # Native callers subsequently recheck full current actor/source/FK proofs.
    guard_document_run_id(db, user, run_id)
