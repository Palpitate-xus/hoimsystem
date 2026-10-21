"""Narrow Actor -> actual Event parent order for RCA source dependencies.

No global Gate. A technical RCA locator returns only the real ID/event pair;
it grants no read/write authority and retains no child lock while waiting for
its Event parent. Existing legacy roles remain the caller's explicit policy.
"""

from fastapi import HTTPException
from sqlalchemy import inspect, select

from app.models import AdverseEvent, AdverseEventRca, User


def current_rows(query, *, shared=False):
    return query.populate_existing().with_for_update(read=shared)


def current_actor(db, user, allowed_roles):
    from app.dependencies import VALID_USER_ROLES

    roles = frozenset(allowed_roles)
    if not roles or not roles <= VALID_USER_ROLES:
        raise ValueError("Explicit actual business roles are required")
    state = inspect(user, raiseerr=False)
    identifier = state.identity[0] if state is not None and state.identity else getattr(user, "user_id", None)
    epoch = {key: state.dict[key] for key in ("user_role", "token_invalid_before") if state is not None and key in state.dict}
    with db.no_autoflush:
        actor = current_rows(db.query(User).filter_by(user_id=identifier), shared=True).one_or_none()
    if actor is None or actor.user_role not in roles or any(getattr(actor, key) != value for key, value in epoch.items()):
        raise HTTPException(403, "当前账户、原登录时效或本项原业务角色已改变")
    return actor


def lock_event_identity(db, event_id):
    """Only opaque parent columns; no event narrative before purpose access."""
    with db.no_autoflush:
        return current_rows(db.query(AdverseEvent.event_id, AdverseEvent.patient_id, AdverseEvent.reporter_id).filter_by(event_id=event_id)).one_or_none()


def lock_actor_event(db, user, event_id, *, allowed_roles):
    actor = current_actor(db, user, allowed_roles)
    return actor, lock_event_identity(db, event_id)


def locate_rca_event(db, rca_id):
    """Current two-column technical locator, never a pre-parent child SHARE/X.

    MySQL returns an immediately closed short RC connection without changing
    the caller's RR view. The same-session narrow fallback accommodates a real
    uncommitted row; final current parent/full-row matching remains mandatory.
    SQLite uses the caller connection to avoid StaticPool rollback interference.
    """
    statement = select(AdverseEventRca.rca_id, AdverseEventRca.event_id).where(AdverseEventRca.rca_id == rca_id)
    with db.no_autoflush:
        bind = db.get_bind()
        if bind.dialect.name in {"mysql", "mariadb"}:
            engine = getattr(bind, "engine", bind)
            with engine.connect().execution_options(isolation_level="READ COMMITTED") as connection:
                row = connection.execute(statement).one_or_none()
            if row is not None:
                return tuple(row)
        row = db.execute(statement).one_or_none()
    return tuple(row) if row is not None else None
