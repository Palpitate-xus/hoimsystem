"""One first lock for legacy surgery writes and reviewed planning originals.

The caller owns commit/rollback and the existing permission/state decisions.
This gate does not reserve a resource, infer UTC from legacy naive clocks, or
turn a schedule status into an actual start/end observation.
"""


def lock_surgery_write(db):
    from app.ai.surgery_facts import lock_write_gate

    # Even a caller with pending ORM changes must acquire the protocol's first
    # lock before the Session is allowed to flush those changes.
    with db.no_autoflush:
        return lock_write_gate(db)


def current_surgery_rows(query):
    """A current locking read, including when a MySQL RR snapshot already exists."""
    return query.populate_existing().with_for_update()
