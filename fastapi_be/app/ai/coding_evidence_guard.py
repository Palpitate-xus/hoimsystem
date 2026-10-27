"""First transaction lock for actual coding writers and governed planning.

Call before reading mutable case-home, dictionary or grouping rows. The caller retains
its existing authorization and owns commit/rollback. No coding is changed.
"""

from fastapi import HTTPException
from sqlalchemy import inspect
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.ai.coding_evidence_models import AICodingWriteGate
from app.sql_locks import postgresql_gate_statement


def current_coding_rows(query, *, shared=False):
    """A current locking read, even with an older MySQL RR snapshot."""
    return query.populate_existing().with_for_update(read=shared)


def lock_coding_gate(db):
    """Acquire the singleton, including a fresh database without a seeded row."""
    dialect = db.get_bind().dialect.name
    if dialect == "mysql":
        statement = mysql_insert(AICodingWriteGate).values(gate_id=1, revision=1).prefix_with("IGNORE")
    elif dialect == "postgresql":
        statement = postgresql_gate_statement(AICodingWriteGate)
    elif dialect == "sqlite":
        statement = sqlite_insert(AICodingWriteGate).values(gate_id=1, revision=1).on_conflict_do_nothing(index_elements=["gate_id"])
    else:
        raise RuntimeError("Coding gate requires an explicitly supported SQL dialect")
    with db.no_autoflush:
        db.execute(statement)
        return current_coding_rows(db.query(AICodingWriteGate).filter_by(gate_id=1)).one()


def lock_coding_write(db, current_user, *, allowed_roles, home_ids=()):
    """Gate -> current actor SHARE -> sorted actual case-home UPDATE locks.

    Callers retain every original business/case authorization and own the
    transaction. Role and membership locks are not professional credentials.
    """
    import re

    from app.dependencies import VALID_USER_ROLES
    from app.models import MedicalRecordHome, User

    roles = frozenset(allowed_roles)
    if not roles or not roles.issubset(VALID_USER_ROLES):
        raise ValueError("Exact nonempty original business role set required")
    ids = set(home_ids)
    if any(type(v) is not str or not re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", v) for v in ids):
        raise ValueError("Actual canonical home UUIDs required")
    state = inspect(current_user, raiseerr=False)
    uid = state.identity[0] if state is not None and state.identity is not None else getattr(current_user, "user_id", None)
    with db.no_autoflush:
        lock_coding_gate(db)
        actor = current_coding_rows(db.query(User).filter_by(user_id=uid), shared=True).one_or_none()
        if actor is None or actor.user_role not in roles:
            raise HTTPException(403, "当前账户已无本项原业务权限")
        for home_id in sorted(ids):
            if current_coding_rows(db.query(MedicalRecordHome.home_id).filter_by(home_id=home_id)).one_or_none() is None:
                raise HTTPException(409, "实际病案首页已不存在")
        return actor
