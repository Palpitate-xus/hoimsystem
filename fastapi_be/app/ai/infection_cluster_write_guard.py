"""Infection Gate first; current request epoch before any clinical body access."""

from fastapi import HTTPException
from sqlalchemy import inspect
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.ai.infection_cluster_models import AIInfectionWriteGate


def current(query, *, shared=False):
    return query.populate_existing().with_for_update(read=shared)


def lock_gate(db):
    dialect = db.get_bind().dialect.name
    if dialect == "mysql":
        statement = mysql_insert(AIInfectionWriteGate).values(gate_id=1, revision=1).on_duplicate_key_update(revision=AIInfectionWriteGate.revision)
    elif dialect == "sqlite":
        statement = sqlite_insert(AIInfectionWriteGate).values(gate_id=1, revision=1).on_conflict_do_nothing(index_elements=["gate_id"])
    else:
        raise RuntimeError("Only explicitly tested SQLite/MySQL infection Gate dialects are supported")
    with db.no_autoflush:
        db.execute(statement)
        return current(db.query(AIInfectionWriteGate).filter_by(gate_id=1)).one()


def identity(user):
    state = inspect(user, raiseerr=False)
    return state.identity[0] if state is not None and state.identity is not None else user.user_id


def lock_infection_write(db, user, *, allowed_roles, patient_ids=(), related_user_ids=()):
    """Gate X → current User SHARE → sorted actual Patient X; caller owns transaction.

    Preserve a loaded request's role/token epoch before populate_existing mutates
    its identity-map object. An expired ORM identity causes no implicit SELECT.
    This technical lock helper grants no infection-purpose/clinical read right.
    """
    from app.dependencies import VALID_USER_ROLES
    from app.models import Patient, User

    roles = frozenset(allowed_roles)
    if not roles or not roles.issubset(VALID_USER_ROLES):
        raise ValueError("The exact internal original role set is required")
    ids = sorted(set(patient_ids))
    if any(type(pid) is not int or not 1 <= pid <= 2147483647 for pid in ids):
        raise ValueError("Actual positive patient PKs are required")
    state = inspect(user, raiseerr=False)
    loaded = user.__dict__ if state is not None else vars(user)
    epoch = (loaded["user_role"], loaded.get("token_invalid_before")) if "user_role" in loaded and "token_invalid_before" in loaded else None
    uid = identity(user)
    with db.no_autoflush:
        lock_gate(db)
        users = {row.user_id: row for row in current(db.query(User).filter(User.user_id.in_(sorted({uid, *related_user_ids}))).order_by(User.user_id), shared=True).all()}
        actor = users.get(uid)
        if actor is None or actor.user_role not in roles or epoch is not None and epoch != (actor.user_role, actor.token_invalid_before):
            raise HTTPException(403, "当前账户角色或令牌时段已变化")
        for pid in ids:
            if current(db.query(Patient.patient_id).filter_by(patient_id=pid)).one_or_none() is None:
                raise HTTPException(409, "明确患者当前不存在")
    return actor
