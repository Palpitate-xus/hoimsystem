"""Current operations authority; the domain gate grants no model transfer."""

from fastapi import HTTPException
from sqlalchemy import inspect

from app.ai.operations_support_models import AIOperationsWriteGate

OPERATIONS_SOURCE_ROLES = frozenset({"super_admin", "admin"})


def current_rows(query, *, shared=False):
    return query.populate_existing().with_for_update(read=shared)


def current_actor(db, user, *, allowed_roles=OPERATIONS_SOURCE_ROLES):
    from app.dependencies import VALID_USER_ROLES
    from app.models import User

    roles = frozenset(allowed_roles)
    if not roles or not roles.issubset(VALID_USER_ROLES):
        raise ValueError("An explicit nonempty platform role set is required")
    state = inspect(user, raiseerr=False)
    epoch = {key: state.dict[key] for key in ("user_role", "token_invalid_before") if key in state.dict} if state is not None else {}
    identifier = state.identity[0] if state is not None and state.identity is not None else getattr(user, "user_id", None)
    if type(identifier) is not int or identifier < 1:
        raise HTTPException(403, "当前运维来源账户身份无效")
    with db.no_autoflush:
        actor = current_rows(db.query(User).filter_by(user_id=identifier), shared=True).one_or_none()
    if actor is None or actor.user_role not in roles or any(getattr(actor, key) != value for key, value in epoch.items()):
        raise HTTPException(403, "当前账户角色或登录授权已变化，不能访问本项运维来源")
    return actor


def lock_operations_write(db, user, *, governance=False):
    """Seeded domain Gate X -> saved request epoch -> current Actor SHARE.

    No lazy inserts, files, application logs or process configuration are read.
    Only a current super administrator may register/review/revoke documents.
    """
    with db.no_autoflush:
        gate = current_rows(db.query(AIOperationsWriteGate).filter_by(gate_id=1)).one_or_none()
        if gate is None or gate.revision != 1:
            raise HTTPException(409, "运维来源增量迁移尚未正确初始化")
        return current_actor(db, user, allowed_roles={"super_admin"} if governance else OPERATIONS_SOURCE_ROLES)
