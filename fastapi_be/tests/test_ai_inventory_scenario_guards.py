"""Actual current identity reads; SQLite results do not prove MySQL row locks."""

import pytest
from fastapi import HTTPException
from sqlalchemy import event, inspect
from sqlalchemy.dialects import mysql

from app.ai.inventory_scenarios import current_actor
from app.models import User


@pytest.mark.parametrize("locking", [False, True])
def test_even_nonwrite_audit_identity_uses_a_current_share_read(db_session, seed_data, locking):
    actor = seed_data["super_admin_user"]
    identifier = inspect(actor).identity[0]
    db_session.expire(actor)
    statements = []

    def record(state):
        if state.is_select:
            statements.append(str(state.statement.compile(dialect=mysql.dialect(), compile_kwargs={"literal_binds": True})))

    event.listen(db_session, "do_orm_execute", record)
    try:
        assert current_actor(db_session, actor, locking=locking).user_id == identifier
    finally:
        event.remove(db_session, "do_orm_execute", record)
    # The expired Python actor must not trigger an earlier plain role SELECT.
    assert len(statements) == 1
    assert "LOCK IN SHARE MODE" in statements[0]
    assert "hoimsystem_users.user_id" in statements[0]


@pytest.mark.parametrize("role", ["cashier", "nurse", "doctor"])
def test_frozen_audit_does_not_keep_authority_from_a_stale_super_python_object(db_session, seed_data, role):
    actor = seed_data["super_admin_user"]
    identifier = actor.user_id
    db_session.query(User).filter_by(user_id=identifier).update({"user_role": role}, synchronize_session=False)
    db_session.flush()
    assert actor.user_role == "super_admin"  # deliberately stale identity map
    with pytest.raises(HTTPException) as caught:
        current_actor(db_session, actor, locking=False)
    assert caught.value.status_code == 403
