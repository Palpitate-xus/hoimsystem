"""Current training Gate and actor epoch; never an answer-key capability."""

from fastapi import HTTPException
from sqlalchemy import inspect

from app.ai.clinical_training_models import AITrainingWriteGate

TRAINING_STAFF_ROLES = frozenset({"super_admin", "admin", "director", "doctor", "nurse", "pharmacist"})


def current_rows(query, *, shared=False):
    return query.populate_existing().with_for_update(read=shared)


def current_actor(db, user, *, allowed_roles=TRAINING_STAFF_ROLES):
    from app.dependencies import VALID_USER_ROLES
    from app.models import User

    roles = frozenset(allowed_roles)
    if not roles or not roles.issubset(VALID_USER_ROLES):
        raise ValueError("An explicit platform-role set is required")
    state = inspect(user, raiseerr=False)
    epoch = {key: state.dict[key] for key in ("user_role", "token_invalid_before") if key in state.dict} if state is not None else {}
    identifier = state.identity[0] if state is not None and state.identity is not None else getattr(user, "user_id", None)
    if type(identifier) is not int or identifier < 1:
        raise HTTPException(403, "当前培训账户身份无效")
    with db.no_autoflush:
        actor = current_rows(db.query(User).filter_by(user_id=identifier), shared=True).one_or_none()
    if actor is None or actor.user_role not in roles or any(getattr(actor, key) != value for key, value in epoch.items()):
        raise HTTPException(403, "培训账户的当前角色或登录授权已变化")
    return actor


def lock_training_write(db, user, *, governance=False):
    with db.no_autoflush:
        gate = current_rows(db.query(AITrainingWriteGate).filter_by(gate_id=1)).one_or_none()
    if gate is None or gate.revision != 1:
        raise HTTPException(409, "培训来源迁移Gate未正确初始化")
    return current_actor(db, user, allowed_roles={"super_admin"} if governance else TRAINING_STAFF_ROLES)
