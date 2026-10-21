"""Feature-local write/current-read order, never a clinical or research grant."""

from fastapi import HTTPException
from sqlalchemy import inspect
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.ai.research_cohort_models import AIResearchStudyScope, AIResearchWriteGate

RESEARCH_SOURCE_ROLES = frozenset({"super_admin", "admin", "director", "doctor"})


def current_research_rows(query, *, shared=False):
    """Explicit current read, including ordinary history under an old RR view."""
    return query.populate_existing().with_for_update(read=shared)


def lock_research_gate(db):
    dialect = db.get_bind().dialect.name
    if dialect == "mysql":
        statement = mysql_insert(AIResearchWriteGate).values(gate_id=1, revision=1).on_duplicate_key_update(revision=AIResearchWriteGate.revision)
    elif dialect == "sqlite":
        statement = sqlite_insert(AIResearchWriteGate).values(gate_id=1, revision=1).on_conflict_do_nothing(index_elements=["gate_id"])
    else:
        raise RuntimeError("Research sources require an explicitly supported SQL dialect")
    with db.no_autoflush:
        db.execute(statement)
        return current_research_rows(db.query(AIResearchWriteGate).filter_by(gate_id=1)).one()


def current_actor(db, user, *, allowed_roles=RESEARCH_SOURCE_ROLES):
    from app.dependencies import VALID_USER_ROLES
    from app.models import User

    roles = frozenset(allowed_roles)
    if not roles or not roles.issubset(VALID_USER_ROLES):
        raise ValueError("Exact nonempty platform role set required")
    state = inspect(user, raiseerr=False)
    epoch = {key: state.dict[key] for key in ("user_role", "token_invalid_before") if key in state.dict} if state is not None else {}
    identifier = state.identity[0] if state is not None and state.identity is not None else getattr(user, "user_id", None)
    with db.no_autoflush:
        actor = current_research_rows(db.query(User).filter_by(user_id=identifier), shared=True).one_or_none()
    if actor is None or actor.user_role not in roles:
        raise HTTPException(403, "当前账户不具备本项来源操作角色；角色本身不授予科研患者权限")
    if any(getattr(actor, key) != value for key, value in epoch.items()):
        raise HTTPException(403, "本次请求原角色或登录授权已变化")
    return actor


def lock_research_write(db, user, *, allowed_roles=RESEARCH_SOURCE_ROLES, scope_ids=(), patient_ids=()):
    """Gate X -> current actor SHARE -> sorted scope X -> sorted Patient PK X.

    The caller must authorize purpose, project ACL and every patient's reviewed
    research permission before it reads clinical content. Locks alone grant none.
    """
    from app.models import Patient

    with db.no_autoflush:
        lock_research_gate(db)
        actor = current_actor(db, user, allowed_roles=allowed_roles)
        for identifier in sorted(set(scope_ids)):
            row = current_research_rows(db.query(AIResearchStudyScope.scope_id).filter_by(scope_id=identifier)).one_or_none()
            if row is None:
                raise HTTPException(404, "明确科研项目来源不存在")
        for identifier in sorted(set(patient_ids)):
            row = current_research_rows(db.query(Patient.patient_id).filter_by(patient_id=identifier)).one_or_none()
            if row is None:
                raise HTTPException(404, "明确科研患者成员不存在")
    return actor
