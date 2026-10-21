"""Actual current-role reads and gate order; MySQL clauses are compilation only."""

import pytest
from fastapi import HTTPException
from sqlalchemy import event, inspect, update
from sqlalchemy.dialects import mysql

from app.ai.charge_reconciliation_write_guard import lock_charge_write
from app.dependencies import ADMIN_ROLES
from app.models import User


@pytest.mark.parametrize("legacy", [None, "inventory", "surgery"])
def test_expired_actor_first_effect_is_billing_then_legacy_gate_before_current_user(db_session, seed_data, legacy):
    db, actor = db_session, seed_data["super_admin_user"]
    uid = inspect(actor).identity[0]
    db.expire(actor)
    statements = []

    def observe(conn, cursor, query, parameters, context, many):
        statements.append(query)

    connection = db.connection()
    event.listen(connection, "before_cursor_execute", observe)
    try:
        current = lock_charge_write(db, actor, allowed_roles=ADMIN_ROLES, legacy_gate=legacy)
    finally:
        event.remove(connection, "before_cursor_execute", observe)
    assert current.user_id == uid
    assert "hoimsystem_ai_charge_write_gate" in statements[0]
    user_index = next(i for i, query in enumerate(statements) if "hoimsystem_users" in query)
    if legacy:
        marker = "inventory" if legacy == "inventory" else "surgery"
        assert any(marker in query and "gate" in query for query in statements[1:user_index])
    captured = []

    def compiled(orm):
        if orm.is_select:
            captured.append(str(orm.statement.compile(dialect=mysql.dialect())))

    event.listen(db, "do_orm_execute", compiled)
    try:
        lock_charge_write(db, actor, allowed_roles=ADMIN_ROLES)
    finally:
        event.remove(db, "do_orm_execute", compiled)
    assert any("hoimsystem_users" in query and "LOCK IN SHARE MODE" in query for query in captured)


def test_cached_role_does_not_authorize_after_actual_database_demotion(db_session, seed_data):
    db, actor = db_session, seed_data["super_admin_user"]
    uid = actor.user_id
    db.execute(update(User).where(User.user_id == uid).values(user_role="patient"), execution_options={"synchronize_session": False})
    db.flush()
    assert actor.user_role == "super_admin"
    with pytest.raises(HTTPException) as denied:
        lock_charge_write(db, actor, allowed_roles=ADMIN_ROLES)
    assert denied.value.status_code == 403


def test_mysql_first_gate_uses_atomic_duplicate_update_instead_of_shared_upgrade():
    from app.ai.charge_reconciliation_write_guard import _mysql_gate_statement

    sql = str(_mysql_gate_statement().compile(dialect=mysql.dialect()))
    assert "ON DUPLICATE KEY UPDATE gate_id =" in sql and "IGNORE" not in sql
    assert sql.startswith("INSERT INTO hoimsystem_ai_charge_write_gate")
    assert "revision =" not in sql
