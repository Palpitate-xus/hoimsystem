"""Actual synthetic SQL gate/current-actor tests; never issues business writes."""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import event, text
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Query

from app.ai import coding_evidence_guard as guard
from app.ai.coding_evidence_models import AICodingWriteGate
from app.dependencies import ADMIN_ROLES, CLINICAL_ROLES, PHARMACY_ROLES
from app.models import Pharmaceutical, User


def statements(db):
    result = []

    def collect(conn, cursor, statement, parameters, context, executemany):
        result.append((statement, parameters))

    event.listen(db.get_bind(), "before_cursor_execute", collect)
    return result, collect


def test_actual_gate_is_singleton_and_never_commits_callers_transaction(db_session, seed_data):
    db = db_session
    before = len(db.query(Pharmaceutical).all())
    for _ in range(2):
        actor = guard.lock_coding_write(db, seed_data["admin_user"], allowed_roles=ADMIN_ROLES)
        assert actor is seed_data["admin_user"]
    assert db.query(AICodingWriteGate).count() == 1
    assert db.query(AICodingWriteGate).one().revision == 1
    assert len(db.query(Pharmaceutical).all()) == before
    db.rollback()
    assert db.query(AICodingWriteGate).count() == 0


@pytest.mark.parametrize(
    "roles,key,accepted", [(PHARMACY_ROLES, "doctor_user", False), (CLINICAL_ROLES, "doctor_user", True), (ADMIN_ROLES, "pharmacist_user", False), (PHARMACY_ROLES, "pharmacist_user", True)]
)
def test_actual_current_actor_preserves_each_legacy_role_policy(db_session, seed_data, roles, key, accepted):
    if accepted:
        assert guard.lock_coding_write(db_session, seed_data[key], allowed_roles=roles).user_role in roles
    else:
        with pytest.raises(HTTPException) as error:
            guard.lock_coding_write(db_session, seed_data[key], allowed_roles=roles)
        assert error.value.status_code == 403
    db_session.rollback()


def test_cached_authorized_actor_is_rechecked_by_actual_current_read(db_session, seed_data):
    db, actor = db_session, seed_data["admin_user"]
    pk = actor.user_id
    assert actor.user_role == "admin"
    db.execute(text("UPDATE hoimsystem_users SET user_role='patient' WHERE user_id=:pk"), {"pk": pk})
    assert actor.user_role == "admin"
    with pytest.raises(HTTPException) as error:
        guard.lock_coding_write(db, actor, allowed_roles=ADMIN_ROLES)
    assert error.value.status_code == 403
    assert actor.user_role == "patient"
    db.rollback()


def test_expired_actor_has_no_implicit_unlocked_user_read_before_gate(db_session, seed_data):
    db, actor = db_session, seed_data["admin_user"]
    db.expire(actor)
    sql, listener = statements(db)
    try:
        guard.lock_coding_write(db, actor, allowed_roles=ADMIN_ROLES)
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", listener)
    reads = [s for s, _ in sql if s.lstrip().upper().startswith("SELECT")]
    assert "hoimsystem_ai_coding_write_gate" in reads[0]
    assert "hoimsystem_users" in reads[1]
    assert len(reads) == 2
    db.rollback()


def test_pending_orm_changes_cannot_autoflush_before_protocol_locks(db_session, seed_data):
    db = db_session
    pending = Pharmaceutical(name="仅synthetic未保存新药", stock=8, status=0)
    db.add(pending)
    sql, listener = statements(db)
    original_autoflush = db.autoflush
    try:
        db.autoflush = True
        guard.lock_coding_write(db, seed_data["admin_user"], allowed_roles=ADMIN_ROLES)
    finally:
        db.autoflush = original_autoflush
        event.remove(db.get_bind(), "before_cursor_execute", listener)
    assert pending.pharmaceutical_id is None
    assert not any(s.lstrip().upper().startswith("INSERT INTO HOIMSYSTEM_PHARMACEUTICAL ") for s, _ in sql)
    db.rollback()


@pytest.mark.parametrize("homes", [[True], ["../x"], ["not-a-uuid"]])
def test_invalid_known_home_is_rejected_before_sql(db_session, seed_data, homes):
    sql, listener = statements(db_session)
    try:
        with pytest.raises(ValueError):
            guard.lock_coding_write(db_session, seed_data["admin_user"], allowed_roles=ADMIN_ROLES, home_ids=homes)
    finally:
        event.remove(db_session.get_bind(), "before_cursor_execute", listener)
    assert sql == []


def test_mysql_actor_is_current_shared_even_with_populate_existing_disabled():
    actor = guard.current_coding_rows(Query(User).filter_by(user_id=1), shared=True)
    assert str(actor.statement.compile(dialect=mysql.dialect())).rstrip().endswith("LOCK IN SHARE MODE")
    assert actor.load_options._populate_existing


def test_absent_actor_never_acquires_business_identity(db_session):
    with pytest.raises(HTTPException) as error:
        guard.lock_coding_write(db_session, SimpleNamespace(user_id=2147483647), allowed_roles=ADMIN_ROLES)
    assert error.value.status_code == 403
    db_session.rollback()
