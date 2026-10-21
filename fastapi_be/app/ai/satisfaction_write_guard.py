"""First lock for the three review/excerpt writers and frozen satisfaction cases."""

from fastapi import HTTPException
from sqlalchemy import inspect
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.ai.satisfaction_models import AISatisfactionWriteGate


def current_satisfaction_rows(query, *, shared=False):
    """Use an actual current read even inside an older MySQL RR snapshot."""
    return query.populate_existing().with_for_update(read=shared)


def lock_satisfaction_gate(db):
    dialect = db.get_bind().dialect.name
    if dialect == "mysql":
        statement = mysql_insert(AISatisfactionWriteGate).values(gate_id=1, revision=1).on_duplicate_key_update(revision=AISatisfactionWriteGate.revision)
    elif dialect == "sqlite":
        statement = sqlite_insert(AISatisfactionWriteGate).values(gate_id=1, revision=1).on_conflict_do_nothing(index_elements=["gate_id"])
    else:
        raise RuntimeError("Satisfaction gate requires an explicitly supported SQL dialect")
    with db.no_autoflush:
        db.execute(statement)
        return current_satisfaction_rows(db.query(AISatisfactionWriteGate).filter_by(gate_id=1)).one()


def current_actor(db, user, *, allowed_roles):
    from app.dependencies import VALID_USER_ROLES
    from app.models import User

    roles = frozenset(allowed_roles)
    if not roles or not roles.issubset(VALID_USER_ROLES):
        raise ValueError("Exact nonempty original business role set required")
    state = inspect(user, raiseerr=False)
    uid = state.identity[0] if state is not None and state.identity is not None else getattr(user, "user_id", None)
    with db.no_autoflush:
        actor = current_satisfaction_rows(db.query(User).filter_by(user_id=uid), shared=True).one_or_none()
    if actor is None or actor.user_role not in roles:
        raise HTTPException(403, "当前账户已无本项原业务权限")
    return actor


def lock_satisfaction_write(db, user, *, allowed_roles):
    """Gate UPDATE -> actor SHARE; caller retains original authorization and transaction."""
    with db.no_autoflush:
        lock_satisfaction_gate(db)
        return current_actor(db, user, allowed_roles=allowed_roles)
