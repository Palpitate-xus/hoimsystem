"""Database statements for transaction-owned singleton write gates."""

from sqlalchemy.dialects.postgresql import insert


def postgresql_gate_statement(model):
    """Insert or exclusively lock the existing row without changing its epoch.

    DO NOTHING can leave concurrent callers upgrading shared locks. A no-op
    UPDATE acquires the same exclusive lock required by the following read.
    The caller owns commit/rollback and every business authorization check.
    """
    return insert(model).values(gate_id=1, revision=1).on_conflict_do_update(index_elements=["gate_id"], set_={"revision": model.revision})
