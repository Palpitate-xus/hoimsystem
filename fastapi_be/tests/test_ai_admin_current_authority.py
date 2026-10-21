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
    # Mixed directories take Billing, Satisfaction and Inventory before actor;
    # neither Gate carries private Run or Source text.
    assert len(sql) == 4
    assert "hoimsystem_ai_charge_write_gate" in sql[0] and sql[0].rstrip().endswith("FOR UPDATE")
    assert "hoimsystem_ai_satisfaction_write_gate" in sql[1] and sql[1].rstrip().endswith("FOR UPDATE")
    assert "hoimsystem_ai_inventory_write_gate" in sql[2] and sql[2].rstrip().endswith("FOR UPDATE")
    assert "hoimsystem_users" in sql[3] and sql[3].rstrip().endswith("LOCK IN SHARE MODE")


def test_audit_actor_rejects_changed_loaded_token_epoch_before_task_reads(db_session, seed_data):
    import datetime

    actor = seed_data["super_admin_user"]
    assert actor.user_role == "super_admin"
    assert actor.token_invalid_before is None
    db_session.execute(
        text("UPDATE hoimsystem_users SET token_invalid_before=:stamp WHERE user_id=:pk"), {"stamp": datetime.datetime(2026, 10, 21, 12, 30, 0, 123456).isoformat(sep=" "), "pk": actor.user_id}
    )
    assert actor.token_invalid_before is None
    try:
        with pytest.raises(HTTPException) as error:
            ai_admin._current_super_admin(db_session, actor)
        assert error.value.status_code == 403
    finally:
        db_session.rollback()


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
