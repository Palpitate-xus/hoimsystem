"""Authorize native task sources before loading their private Task TEXT."""


def lock_directory_gates(db):
    from app.ai.inventory_write_guard import lock_inventory_gate

    lock_inventory_gate(db)


def guard_private_task_read(db, user, run_id):
    from app.ai.drug_label_runtime import guard_drug_label_run_id

    lock_directory_gates(db)
    if guard_drug_label_run_id(db, user, run_id, frozen_audit=user.user_role == "super_admin"):
        return
    from app.ai.document_extraction_runtime import guard_document_run_id

    guard_document_run_id(db, user, run_id)
