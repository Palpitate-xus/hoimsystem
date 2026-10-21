"""Actual SQL changed requests; an id-only worker is not a stale JWT epoch."""

import datetime as dt
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import event, inspect, text
from sqlalchemy.dialects import mysql

from app.ai import satisfaction_runtime
from app.ai.satisfaction_contract import SOURCE_ROLES
from app.ai.satisfaction_write_guard import current_actor, lock_satisfaction_write
from app.models import User


@pytest.mark.parametrize("entry", ["actor", "write", "runtime"])
@pytest.mark.parametrize("changed", ["user_role", "token_invalid_before"])
def test_loaded_request_epoch_cannot_silently_refresh_into_a_new_current_authority(db_session, seed_data, entry, changed):
    db = db_session
    actor = seed_data["admin_user"]
    db.refresh(actor)
    identifier = inspect(actor).identity[0]
    original = {key: inspect(actor).dict[key] for key in ("user_role", "token_invalid_before")}
    value = "director" if changed == "user_role" else dt.datetime(2026, 10, 21, 12, 0, 0, 123456)
    db.execute(text(f"UPDATE hoimsystem_users SET {changed}=:value WHERE user_id=:identifier"), {"value": value, "identifier": identifier})
    assert {key: inspect(actor).dict[key] for key in original} == original
    with pytest.raises(HTTPException) as error:
        if entry == "actor":
            current_actor(db, actor, allowed_roles=SOURCE_ROLES)
        elif entry == "write":
            lock_satisfaction_write(db, actor, allowed_roles=SOURCE_ROLES)
        else:
            satisfaction_runtime.current_actor(db, actor)
    assert error.value.status_code == 403
    db.rollback()


def test_id_only_internal_worker_uses_real_current_shared_read_without_inventing_request_epoch(db_session, seed_data):
    db = db_session
    actor = seed_data["admin_user"]
    db.refresh(actor)
    identifier = inspect(actor).identity[0]
    db.execute(text("UPDATE hoimsystem_users SET user_role='director' WHERE user_id=:identifier"), {"identifier": identifier})
    current = current_actor(db, SimpleNamespace(user_id=identifier), allowed_roles=SOURCE_ROLES)
    assert current.user_role == "director" and current.user_id == identifier
    db.rollback()


def test_expired_request_does_not_trigger_an_unlocked_identity_or_epoch_attribute_read(db_session, seed_data):
    db = db_session
    actor = seed_data["admin_user"]
    db.refresh(actor)
    identifier = inspect(actor).identity[0]
    db.expire(actor)
    statements = []

    def selected(state):
        if state.is_select:
            statements.append(str(state.statement.compile(dialect=mysql.dialect())))

    event.listen(db, "do_orm_execute", selected)
    try:
        current = current_actor(db, actor, allowed_roles=SOURCE_ROLES)
    finally:
        event.remove(db, "do_orm_execute", selected)
    user_reads = [sql for sql in statements if User.__tablename__ in sql]
    assert current.user_id == identifier and len(user_reads) == 1
    assert "FOR SHARE" in user_reads[0] or "LOCK IN SHARE MODE" in user_reads[0]
