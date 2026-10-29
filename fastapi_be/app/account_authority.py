"""Lock account-management subjects before checking administrator authority."""

from fastapi import HTTPException
from sqlalchemy import inspect

from app.models import User

PROTECTED_ROLES = frozenset({"admin", "super_admin"})


def lock_account_management(db, actor, target_user_id, *, operation, new_role=None):
    """Authorize a current actor and target while holding both user-row locks.

    Capture authenticated scalars before refreshing the ORM identity map. The
    ordered locking read also prevents a concurrent role change from bypassing
    the target-account checks until the caller commits or rolls back.
    """
    if operation not in {"role", "reset_password", "delete"}:
        raise ValueError("Unknown account-management operation")
    if type(target_user_id) is not int or target_user_id <= 0:
        raise HTTPException(422, "用户编号必须为正整数")
    state = inspect(actor, raiseerr=False)
    actor_id = state.identity[0] if state is not None and state.identity is not None else getattr(actor, "user_id", None)
    authenticated = tuple(
        (name, state.dict[name])
        for name in ("username", "user_role", "token_invalid_before")
        if state is not None and name in state.dict
    )
    with db.no_autoflush:
        rows = (
            db.query(User)
            .filter(User.user_id.in_({actor_id, target_user_id}))
            .order_by(User.user_id)
            .populate_existing()
            .with_for_update()
            .all()
        )
    accounts = {row.user_id: row for row in rows}
    current_actor = accounts.get(actor_id)
    if current_actor is None or current_actor.user_role not in PROTECTED_ROLES:
        raise HTTPException(403, "当前账号没有用户管理权限")
    if any(getattr(current_actor, name) != value for name, value in authenticated):
        raise HTTPException(403, "登录身份已变更，请重新登录")
    target = accounts.get(target_user_id)
    if target is None:
        return current_actor, None
    if target.user_id == current_actor.user_id and operation in {"role", "delete"}:
        raise HTTPException(400, "不能修改当前账号角色或删除当前账号")
    if current_actor.user_role != "super_admin" and (
        target.user_role in PROTECTED_ROLES or (operation == "role" and new_role in PROTECTED_ROLES)
    ):
        raise HTTPException(403, "只有超级管理员可以管理管理员账号")
    return current_actor, target
