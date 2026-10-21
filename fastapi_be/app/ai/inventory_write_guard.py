"""First transaction lock for actual inventory writers and governed planning.

Call before reading mutable stock or business-state rows. The caller retains
its existing authorization and owns commit/rollback. No inventory is changed.
"""

from fastapi import HTTPException
from sqlalchemy import inspect
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.ai.inventory_native_source_models import AIInventoryWriteGate


def current_inventory_rows(query, *, shared=False):
    """A current locking read, even with an older MySQL RR snapshot."""
    return query.populate_existing().with_for_update(read=shared)


def lock_inventory_gate(db):
    """Acquire the singleton, including a fresh database without a seeded row."""
    dialect = db.get_bind().dialect.name
    if dialect == "mysql":
        statement = mysql_insert(AIInventoryWriteGate).values(gate_id=1, revision=1).prefix_with("IGNORE")
    elif dialect == "sqlite":
        statement = sqlite_insert(AIInventoryWriteGate).values(gate_id=1, revision=1).on_conflict_do_nothing(index_elements=["gate_id"])
    else:
        raise RuntimeError("Inventory gate requires an explicitly supported SQL dialect")
    with db.no_autoflush:
        db.execute(statement)
        return current_inventory_rows(db.query(AIInventoryWriteGate).filter_by(gate_id=1)).one()


def lock_inventory_write(db, current_user, *, allowed_roles, skus=(), require_active=False, allow_missing=False):
    """Gate → actual actor SHARE → sorted known actual SKU UPDATE locks.

    Returns the current actor. `allowed_roles` is an internal caller's exact
    original role set, never request data. Source revocation alone may opt into
    a missing original SKU; the global gate still serializes that case.
    """
    from app.dependencies import VALID_USER_ROLES
    from app.models import Consumable, Pharmaceutical, User

    roles = frozenset(allowed_roles)
    if not roles or not roles.issubset(VALID_USER_ROLES):
        raise ValueError("Exact nonempty original allowed roles required")
    normalized = set()
    for value in skus:
        if not isinstance(value, (tuple, list)) or len(value) != 2:
            raise ValueError("Each known SKU requires its actual kind and positive identifier")
        kind, identifier = value
        if kind not in {"pharmaceutical", "consumable"} or type(identifier) is not int or not 1 <= identifier <= 2147483647:
            raise ValueError("Invalid actual inventory SKU")
        normalized.add((kind, identifier))
    state = inspect(current_user, raiseerr=False)
    user_id = state.identity[0] if state is not None and state.identity is not None else getattr(current_user, "user_id", None)
    with db.no_autoflush:
        lock_inventory_gate(db)
        actor = current_inventory_rows(db.query(User).filter_by(user_id=user_id), shared=True).one_or_none()
        if actor is None or actor.user_role not in roles:
            raise HTTPException(403, "当前账户已无本项原业务写入权限")
        for kind, identifier in sorted(normalized):
            model, primary = (Pharmaceutical, Pharmaceutical.pharmaceutical_id) if kind == "pharmaceutical" else (Consumable, Consumable.consumable_id)
            row = current_inventory_rows(db.query(model).filter(primary == identifier)).one_or_none()
            if row is None:
                if allow_missing:
                    continue
                raise HTTPException(409, "实际库存品种已不存在")
            if require_active and row.status != 0:
                raise HTTPException(409, "实际库存品种当前未明确启用")
        return actor
