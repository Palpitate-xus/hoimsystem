"""One first lock for legacy surgery writes and reviewed planning originals.

The caller owns commit/rollback and the existing permission/state decisions.
This gate does not reserve a resource, infer UTC from legacy naive clocks, or
turn a schedule status into an actual start/end observation.
"""


def lock_surgery_write(db, current_user=None):
    from app.ai.surgery_facts import lock_write_gate

    # Even a caller with pending ORM changes must acquire the protocol's first
    # lock before the Session is allowed to flush those changes.
    with db.no_autoflush:
        gate = lock_write_gate(db)
        if current_user is not None:
            from fastapi import HTTPException

            from app.dependencies import CLINICAL_ROLES
            from app.models import User

            # The request dependency can have read this role before a gate
            # wait. A current locking read preserves the original role policy
            # through this mutation; it grants no additional AI permission.
            actor = current_surgery_rows(db.query(User).filter(User.user_id == current_user.user_id)).one_or_none()
            if actor is None or actor.user_role not in CLINICAL_ROLES:
                raise HTTPException(403, "当前身份已无原手术临床写入权限")
        return gate


def current_surgery_rows(query):
    """A current locking read, including when a MySQL RR snapshot already exists."""
    return query.populate_existing().with_for_update()
