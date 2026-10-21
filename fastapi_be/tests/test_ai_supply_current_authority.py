"""Actual ORM authorization queries retain MySQL current shared reads in read-only paths."""

import pytest
from fastapi import HTTPException
from sqlalchemy import event, text
from sqlalchemy.dialects import mysql

from app.ai import supply_sources as sources


def capture_sql(db):
    sql = []

    def capture(state):
        if state.is_select:
            sql.append(str(state.statement.compile(dialect=mysql.dialect())))

    event.listen(db, "do_orm_execute", capture)
    return sql, capture


@pytest.mark.parametrize("kwargs", [{}, {"locking": False}, {"locking": True}])
def test_every_actor_authorization_uses_actual_shared_read(db_session, seed_data, kwargs):
    actor = seed_data["super_admin_user"]
    sql, listener = capture_sql(db_session)
    try:
        assert sources.current_actor(db_session, actor, **kwargs) is actor
    finally:
        event.remove(db_session, "do_orm_execute", listener)
    assert len(sql) == 1 and "hoimsystem_users" in sql[0]
    assert sql[0].rstrip().endswith("LOCK IN SHARE MODE")


def test_expired_actor_has_no_unlocked_lazy_read_before_current_authorization(db_session, seed_data):
    actor = seed_data["super_admin_user"]
    db_session.expire(actor)
    sql, listener = capture_sql(db_session)
    try:
        assert sources.current_actor(db_session, actor).user_role == "super_admin"
    finally:
        event.remove(db_session, "do_orm_execute", listener)
    assert len(sql) == 1 and sql[0].rstrip().endswith("LOCK IN SHARE MODE")


def test_read_authorization_refreshes_cached_role_and_refuses_demotion(db_session, seed_data):
    actor = seed_data["super_admin_user"]
    pk = actor.user_id
    db_session.execute(text("UPDATE hoimsystem_users SET user_role='patient' WHERE user_id=:pk"), {"pk": pk})
    assert actor.user_role == "super_admin"
    with pytest.raises(HTTPException) as error:
        sources.current_actor(db_session, actor, locking=False)
    assert error.value.status_code == 403
    assert actor.user_role == "patient"
    db_session.rollback()


@pytest.mark.parametrize("kwargs", [{}, {"locking": False}, {"locking": True}])
def test_every_professional_signer_check_uses_actual_shared_read(db_session, seed_data, kwargs):
    actor = seed_data["pharmacist_user"]
    attestation = {"status": "confirmed", "signer_user_id": actor.user_id}
    sql, listener = capture_sql(db_session)
    try:
        assert sources._signer(db_session, attestation, **kwargs) == {"user_id": actor.user_id, "user_role": "pharmacist"}
    finally:
        event.remove(db_session, "do_orm_execute", listener)
    assert len(sql) == 1 and sql[0].rstrip().endswith("LOCK IN SHARE MODE")
