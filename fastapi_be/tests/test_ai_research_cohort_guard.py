"""Actual SQLite current actor/parent shape; MySQL upsert is compile-only."""

from contextlib import nullcontext
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import event, inspect, text
from sqlalchemy.dialects import mysql

from app.ai.research_cohort_write_guard import current_actor, lock_research_gate, lock_research_write
from app.models import Patient
from tests.test_ai_research_cohort_models import scope_row


def test_actual_gate_actor_sorted_scope_patient_pk_lock_order_never_loads_clinical_or_scope_bodies(db_session, seed_data):
    db = db_session
    user = seed_data["admin_user"]
    scopes = [scope_row(user.user_id), scope_row(user.user_id)]
    patients = [Patient(name="隔离合成有限成员甲"), Patient(name="隔离合成有限成员乙")]
    db.add_all(scopes + patients)
    db.commit()
    scope_ids = sorted(inspect(row).identity[0] for row in scopes)
    patient_ids = sorted(inspect(row).identity[0] for row in patients)
    uid = inspect(user).identity[0]
    db.expire(user)
    statements = []

    def seen(conn, cursor, sql, params, context, many):
        statements.append((sql, params, None if context.compiled is None else context.compiled.statement))

    event.listen(db.bind, "before_cursor_execute", seen)
    try:
        actor = lock_research_write(db, user, scope_ids=scope_ids[::-1] + scope_ids, patient_ids=patient_ids[::-1] + patient_ids)
        assert actor.user_id == uid
    finally:
        event.remove(db.bind, "before_cursor_execute", seen)
    assert statements[0][0].startswith("INSERT INTO hoimsystem_ai_research_write_gate")
    assert next(i for i, (sql, _, _) in enumerate(statements) if "SELECT" in sql and "hoimsystem_users" in sql) < next(
        i for i, (sql, _, _) in enumerate(statements) if "SELECT" in sql and "hoimsystem_ai_research_study_scope" in sql
    )
    scope_reads = [(params, stmt) for sql, params, stmt in statements if "SELECT" in sql and "hoimsystem_ai_research_study_scope" in sql]
    patient_reads = [(params, stmt) for sql, params, stmt in statements if "SELECT" in sql and "hoimsystem_patient" in sql]
    assert [params[0] for params, _ in scope_reads] == scope_ids
    assert [params[0] for params, _ in patient_reads] == patient_ids
    assert all(str(stmt.compile(dialect=mysql.dialect())).endswith("FOR UPDATE") for _, stmt in scope_reads + patient_reads)
    assert not any("scope_json" in sql or "hoimsystem_patient.name" in sql for sql, _, _ in statements)
    db.rollback()


@pytest.mark.parametrize("field,value", [("user_role", "director"), ("token_invalid_before", "2026-10-22 00:00:00")])
@pytest.mark.parametrize("entry", ["actor", "write"])
def test_actual_already_loaded_request_epoch_change_is_rejected_instead_of_refreshing_authority(db_session, seed_data, field, value, entry):
    db = db_session
    user = seed_data["admin_user"]
    uid = user.user_id
    assert user.user_role == "admin" and user.token_invalid_before is None
    before = {key: inspect(user).dict[key] for key in ("user_role", "token_invalid_before")}
    db.execute(text("UPDATE hoimsystem_users SET " + field + "=:value WHERE user_id=:id"), {"value": value, "id": uid})
    assert {key: inspect(user).dict[key] for key in before} == before
    with pytest.raises(HTTPException) as error:
        (current_actor if entry == "actor" else lock_research_write)(db, user)
    assert error.value.status_code == 403
    db.rollback()


def test_expired_actor_identity_is_inspected_without_implicit_pre_gate_user_read(db_session, seed_data):
    db = db_session
    user = seed_data["admin_user"]
    uid = inspect(user).identity[0]
    db.expire(user)
    statements = []

    def seen(conn, cursor, sql, params, context, many):
        statements.append(sql)

    event.listen(db.bind, "before_cursor_execute", seen)
    try:
        assert lock_research_write(db, user).user_id == uid
    finally:
        event.remove(db.bind, "before_cursor_execute", seen)
    assert statements[0].startswith("INSERT INTO hoimsystem_ai_research_write_gate")
    db.rollback()


def test_id_only_worker_still_gets_current_authority_but_no_patient_project_permission_is_inferred(db_session, seed_data):
    db = db_session
    user = seed_data["admin_user"]
    uid = user.user_id
    actor = lock_research_write(db, SimpleNamespace(user_id=uid))
    assert actor.user_role == "admin"
    db.rollback()
    db.execute(text("UPDATE hoimsystem_users SET user_role='patient' WHERE user_id=:id"), {"id": uid})
    with pytest.raises(HTTPException) as error:
        lock_research_write(db, SimpleNamespace(user_id=uid))
    assert error.value.status_code == 403
    db.rollback()


@pytest.mark.parametrize("which", ["scope", "patient"])
def test_absent_explicit_parent_is_rejected_without_expanding_member_set(db_session, seed_data, which):
    values = {"scope_ids": ("00000000-0000-4000-8000-000000000001",)} if which == "scope" else {"patient_ids": (2147483647,)}
    with pytest.raises(HTTPException) as error:
        lock_research_write(db_session, seed_data["admin_user"], **values)
    assert error.value.status_code == 404
    db_session.rollback()


def test_current_actor_query_is_always_a_current_shared_read_for_archive_roles(db_session, seed_data):
    db = db_session
    uid = seed_data["admin_user"].user_id
    statements = []

    def seen(conn, cursor, sql, params, context, many):
        if "SELECT" in sql and "hoimsystem_users" in sql:
            statements.append(context.compiled.statement)

    event.listen(db.bind, "before_cursor_execute", seen)
    try:
        current_actor(db, SimpleNamespace(user_id=uid))
    finally:
        event.remove(db.bind, "before_cursor_execute", seen)
    assert len(statements) == 1 and str(statements[0].compile(dialect=mysql.dialect())).endswith("LOCK IN SHARE MODE")
    db.rollback()


def test_mysql_gate_branch_compiles_to_direct_same_value_exclusive_upsert_without_ignore():
    statements = []

    class CompileOnlyDB:
        no_autoflush = nullcontext()

        def get_bind(self):
            return SimpleNamespace(dialect=mysql.dialect())

        def execute(self, statement):
            statements.append(statement)

        def query(self, *_):
            return self

        def filter_by(self, **_):
            return self

        def populate_existing(self):
            return self

        def with_for_update(self, **_):
            return self

        def one(self):
            return SimpleNamespace(gate_id=1, revision=1)

    assert lock_research_gate(CompileOnlyDB()).gate_id == 1
    sql = str(statements[0].compile(dialect=mysql.dialect()))
    assert "ON DUPLICATE KEY UPDATE revision = hoimsystem_ai_research_write_gate.revision" in sql
    assert "IGNORE" not in sql and "AUTO_INCREMENT" not in sql
