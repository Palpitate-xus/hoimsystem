"""Audit readers must retain the actual Super role, including an ordinary Source-role demotion."""

import pytest
from fastapi import HTTPException
from sqlalchemy import event, text
from sqlalchemy.dialects import mysql

from app.routers import ai_admin


@pytest.mark.parametrize("reader", ["list", "trace"])
def test_audit_readers_recheck_stale_super_before_any_run_read(db_session, seed_data, reader):
    actor = seed_data["super_admin_user"]
    db_session.execute(text("UPDATE hoimsystem_users SET user_role='pharmacist' WHERE user_id=:pk"), {"pk": actor.user_id})
    assert actor.user_role == "super_admin"
    sql = []

    def observe(state):
        if state.is_select:
            sql.append(str(state.statement.compile(dialect=mysql.dialect())))

    event.listen(db_session, "do_orm_execute", observe)
    try:
        with pytest.raises(HTTPException) as error:
            if reader == "list":
                ai_admin.list_global_runs(db=db_session, user=actor)
            else:
                ai_admin.inspect_run_trace("no-task-read-allowed", db=db_session, user=actor)
        assert error.value.status_code == 403
    finally:
        event.remove(db_session, "do_orm_execute", observe)
        db_session.rollback()
    # Native mixed directories acquire their nonprivate Gate before any User
    # or Run locks. A stale Super must then stop at the current actor read.
    assert len(sql) == 2
    assert "hoimsystem_ai_inventory_write_gate" in sql[0] and sql[0].rstrip().endswith("FOR UPDATE")
    assert "hoimsystem_users" in sql[1] and sql[1].rstrip().endswith("LOCK IN SHARE MODE")
    assert not any("hoimsystem_ai_run" in statement or "hoimsystem_ai_drug_label" in statement for statement in sql)


def test_expired_audit_actor_has_exactly_one_current_shared_read(db_session, seed_data):
    actor = seed_data["super_admin_user"]
    db_session.expire(actor)
    sql = []

    def observe(state):
        if state.is_select:
            sql.append(str(state.statement.compile(dialect=mysql.dialect())))

    event.listen(db_session, "do_orm_execute", observe)
    try:
        assert ai_admin._current_super_admin(db_session, actor).user_role == "super_admin"
    finally:
        event.remove(db_session, "do_orm_execute", observe)
    assert len(sql) == 1 and sql[0].rstrip().endswith("LOCK IN SHARE MODE")
