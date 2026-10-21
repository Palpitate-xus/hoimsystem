"""Actual synthetic SQL gate/current-actor tests; never issues business writes."""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import event, text
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Query

from app.ai import inventory_write_guard as guard
from app.ai.inventory_native_source_models import AIInventoryWriteGate
from app.dependencies import ADMIN_ROLES, CLINICAL_ROLES, PHARMACY_ROLES
from app.models import Consumable, Pharmaceutical, User


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
        actor = guard.lock_inventory_write(db, seed_data["admin_user"], allowed_roles=ADMIN_ROLES)
        assert actor is seed_data["admin_user"]
    assert db.query(AIInventoryWriteGate).count() == 1
    assert db.query(AIInventoryWriteGate).one().revision == 1
    assert len(db.query(Pharmaceutical).all()) == before
    db.rollback()
    assert db.query(AIInventoryWriteGate).count() == 0


@pytest.mark.parametrize(
    "roles,key,accepted", [(PHARMACY_ROLES, "doctor_user", False), (CLINICAL_ROLES, "doctor_user", True), (ADMIN_ROLES, "pharmacist_user", False), (PHARMACY_ROLES, "pharmacist_user", True)]
)
def test_actual_current_actor_preserves_each_legacy_role_policy(db_session, seed_data, roles, key, accepted):
    if accepted:
        assert guard.lock_inventory_write(db_session, seed_data[key], allowed_roles=roles).user_role in roles
    else:
        with pytest.raises(HTTPException) as error:
            guard.lock_inventory_write(db_session, seed_data[key], allowed_roles=roles)
        assert error.value.status_code == 403
    db_session.rollback()


def test_cached_authorized_actor_is_rechecked_by_actual_current_read(db_session, seed_data):
    db, actor = db_session, seed_data["admin_user"]
    pk = actor.user_id
    assert actor.user_role == "admin"
    db.execute(text("UPDATE hoimsystem_users SET user_role='patient' WHERE user_id=:pk"), {"pk": pk})
    assert actor.user_role == "admin"
    with pytest.raises(HTTPException) as error:
        guard.lock_inventory_write(db, actor, allowed_roles=ADMIN_ROLES)
    assert error.value.status_code == 403
    assert actor.user_role == "patient"
    db.rollback()


def test_expired_actor_has_no_implicit_unlocked_user_read_before_gate(db_session, seed_data):
    db, actor = db_session, seed_data["admin_user"]
    db.expire(actor)
    sql, listener = statements(db)
    try:
        guard.lock_inventory_write(db, actor, allowed_roles=ADMIN_ROLES)
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", listener)
    reads = [s for s, _ in sql if s.lstrip().upper().startswith("SELECT")]
    assert "hoimsystem_ai_inventory_write_gate" in reads[0]
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
        guard.lock_inventory_write(db, seed_data["admin_user"], allowed_roles=ADMIN_ROLES)
    finally:
        db.autoflush = original_autoflush
        event.remove(db.get_bind(), "before_cursor_execute", listener)
    assert pending.pharmaceutical_id is None
    assert not any(s.lstrip().upper().startswith("INSERT INTO HOIMSYSTEM_PHARMACEUTICAL ") for s, _ in sql)
    db.rollback()


def test_known_actual_skus_are_locked_once_in_global_sorted_order(db_session, seed_data):
    db = db_session
    drug = db.query(Pharmaceutical).first()
    con = Consumable(name="synthetic独立耗材", stock=0, status=0)
    db.add(con)
    db.commit()
    keys = [("pharmaceutical", drug.pharmaceutical_id), ("consumable", con.consumable_id), ("pharmaceutical", drug.pharmaceutical_id)]
    sql, listener = statements(db)
    try:
        guard.lock_inventory_write(db, seed_data["admin_user"], allowed_roles=ADMIN_ROLES, skus=keys, require_active=True)
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", listener)
    reads = [s for s, _ in sql if s.lstrip().upper().startswith("SELECT")]
    assert len(reads) == 4
    assert ["hoimsystem_ai_inventory_write_gate" in reads[0], "hoimsystem_users" in reads[1], "hoimsystem_consumable" in reads[2], "hoimsystem_pharmaceutical" in reads[3]] == [True] * 4
    assert drug.stock is not None and con.stock == 0
    db.rollback()


def test_missing_or_disabled_sku_is_not_implicitly_active(db_session, seed_data):
    db = db_session
    with pytest.raises(HTTPException) as error:
        guard.lock_inventory_write(db, seed_data["admin_user"], allowed_roles=ADMIN_ROLES, skus=[("consumable", 2147483647)])
    assert error.value.status_code == 409
    assert guard.lock_inventory_write(db, seed_data["admin_user"], allowed_roles=ADMIN_ROLES, skus=[("consumable", 2147483647)], allow_missing=True)
    item = Consumable(name="synthetic停用耗材", stock=0, status=1)
    db.add(item)
    db.flush()
    with pytest.raises(HTTPException) as error:
        guard.lock_inventory_write(db, seed_data["admin_user"], allowed_roles=ADMIN_ROLES, skus=[("consumable", item.consumable_id)], require_active=True)
    assert error.value.status_code == 409
    db.rollback()


@pytest.mark.parametrize("skus", [[("pharmaceutical", True)], [("pharmaceutical", 0)], [("drug", 1)], [("consumable", "1")], [("consumable", 2147483648)], ["pharmaceutical"]])
def test_invalid_known_identity_fails_before_any_sql(db_session, seed_data, skus):
    sql, listener = statements(db_session)
    try:
        with pytest.raises(ValueError):
            guard.lock_inventory_write(db_session, seed_data["admin_user"], allowed_roles=ADMIN_ROLES, skus=skus)
    finally:
        event.remove(db_session.get_bind(), "before_cursor_execute", listener)
    assert sql == []


def test_mysql_actor_lock_is_shared_and_business_sku_lock_is_exclusive():
    actor = guard.current_inventory_rows(Query(User).filter_by(user_id=1), shared=True)
    sku = guard.current_inventory_rows(Query(Pharmaceutical).filter_by(pharmaceutical_id=1))
    assert str(actor.statement.compile(dialect=mysql.dialect())).rstrip().endswith("LOCK IN SHARE MODE")
    assert str(sku.statement.compile(dialect=mysql.dialect())).rstrip().endswith("FOR UPDATE")


def test_absent_actor_never_acquires_business_identity(db_session):
    with pytest.raises(HTTPException) as error:
        guard.lock_inventory_write(db_session, SimpleNamespace(user_id=2147483647), allowed_roles=ADMIN_ROLES)
    assert error.value.status_code == 403
    db_session.rollback()
