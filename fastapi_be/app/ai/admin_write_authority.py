"""Keep an administrator's authenticated subject fixed across a management write."""

from contextlib import contextmanager
from dataclasses import dataclass
from functools import wraps
from inspect import iscoroutinefunction, signature

from fastapi import HTTPException
from sqlalchemy import inspect

from app.models import User

_WRITE_AUTHORITY = "hoim_ai_admin_write_authority"


@dataclass(frozen=True)
class AdminAuthority:
    user_id: int | None
    authenticated: tuple


def capture_authority(user):
    """Inspect loaded scalars without refreshing an expired identity first."""
    state = inspect(user, raiseerr=False)
    user_id = state.identity[0] if state is not None and state.identity is not None else getattr(user, "user_id", None)
    loaded = tuple((name, state.dict[name]) for name in ("username", "user_role", "token_invalid_before") if state is not None and name in state.dict)
    return AdminAuthority(user_id, loaded)


def current_super_admin(db, authority):
    """A locking current read bypasses a JWT-created MySQL RR snapshot."""
    with db.no_autoflush:
        actor = db.query(User).filter_by(user_id=authority.user_id).populate_existing().with_for_update(read=True).one_or_none()
    if actor is None or actor.user_role != "super_admin" or any(getattr(actor, name) != value for name, value in authority.authenticated):
        raise HTTPException(403, "当前登录身份已无AI超级管理员权限，请重新登录")
    return actor


def resume_admin_write(db):
    """Reacquire the common gates and the original subject after a probe await."""
    from app.ai.native_task_access import lock_directory_gates

    authority = db.info[_WRITE_AUTHORITY]
    lock_directory_gates(db)
    return current_super_admin(db, authority)


async def checked_capability_probe(db, inspector, provider):
    """No transaction is held on the wire; revoked subjects cannot resume writes."""
    try:
        return await inspector(provider)
    finally:
        resume_admin_write(db)


def verify_admin_write_before_commit(db):
    """Check after real SQL, including triggers, before committing data and audit."""
    authority = db.info.get(_WRITE_AUTHORITY)
    if authority is not None:
        db.flush()
        current_super_admin(db, authority)


@contextmanager
def _write_context(db, user):
    from app.ai.native_task_access import lock_directory_gates

    if _WRITE_AUTHORITY in db.info:
        raise RuntimeError("AI management write contexts cannot be nested")
    authority = capture_authority(user)
    try:
        lock_directory_gates(db)
        actor = current_super_admin(db, authority)
        # Internal callers may supply expired objects. Once the first current
        # read authorizes them, preserve its scalars across all later refreshes.
        db.info[_WRITE_AUTHORITY] = capture_authority(actor)
        yield actor
    except BaseException:
        db.rollback()
        raise
    finally:
        db.info.pop(_WRITE_AUTHORITY, None)


def admin_write(handler):
    """Preserve FastAPI's signature, role dependency and direct-call behavior."""
    parameters = signature(handler)

    if iscoroutinefunction(handler):

        @wraps(handler)
        async def asynchronous(*args, **kwargs):
            bound = parameters.bind(*args, **kwargs)
            with _write_context(bound.arguments["db"], bound.arguments["user"]) as actor:
                bound.arguments["user"] = actor
                return await handler(*bound.args, **bound.kwargs)

        return asynchronous

    @wraps(handler)
    def synchronous(*args, **kwargs):
        bound = parameters.bind(*args, **kwargs)
        with _write_context(bound.arguments["db"], bound.arguments["user"]) as actor:
            bound.arguments["user"] = actor
            return handler(*bound.args, **bound.kwargs)

    return synchronous
