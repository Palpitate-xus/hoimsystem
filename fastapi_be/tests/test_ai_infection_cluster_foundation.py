"""Actual SQLite/current actor checks; MySQL compilation is not a concurrency proof."""

import datetime as dt
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import HTTPException
from sqlalchemy import create_engine, event, inspect
from sqlalchemy.dialects import mysql
from sqlalchemy.exc import IntegrityError
from sqlalchemy.schema import CreateTable

from app.ai.infection_cluster_models import INFECTION_SOURCE_MODELS, AIInfectionWriteGate
from app.ai.infection_cluster_write_guard import lock_infection_write


def test_mysql_gate_no_auto_increment_and_exact_storage_types():
    ddl = "\n".join(str(CreateTable(model.__table__).compile(dialect=mysql.dialect())) for model in INFECTION_SOURCE_MODELS)
    assert "AUTO_INCREMENT" not in str(CreateTable(AIInfectionWriteGate.__table__).compile(dialect=mysql.dialect()))
    assert ddl.count("DATETIME(6)") == 12
    assert ddl.count("MEDIUMTEXT") == 6
    assert "BLOB(32)" in ddl
    assert "reviewed_by<>created_by" in ddl
    assert "uq_inf_review_exact_root" in ddl


def test_actual_sqlite_gate_refreshes_actor_and_rejects_original_epoch(db_session, seed_data):
    actor = seed_data["super_admin_user"]
    old = SimpleNamespace(user_id=actor.user_id, user_role="super_admin", token_invalid_before=None)
    db_session.query(type(actor)).filter_by(user_id=actor.user_id).update({"user_role": "admin"}, synchronize_session=False)
    db_session.commit()
    with pytest.raises(HTTPException) as rejected:
        lock_infection_write(db_session, old, allowed_roles={"super_admin", "admin"})
    assert rejected.value.status_code == 403
    db_session.rollback()
    fresh = SimpleNamespace(user_id=actor.user_id, user_role="admin", token_invalid_before=None)
    assert lock_infection_write(db_session, fresh, allowed_roles={"admin"}).user_role == "admin"
    assert db_session.query(AIInfectionWriteGate).one().gate_id == 1
    db_session.rollback()


def test_expired_actor_does_not_emit_plain_user_select_before_gate(db_session, seed_data):
    actor = seed_data["super_admin_user"]
    db_session.expire(actor)
    statements = []

    def capture(conn, cursor, sql, parameters, context, executemany):
        statements.append(sql)

    event.listen(db_session.get_bind(), "before_cursor_execute", capture)
    try:
        lock_infection_write(db_session, actor, allowed_roles={"super_admin"})
    finally:
        event.remove(db_session.get_bind(), "before_cursor_execute", capture)
    assert "INSERT INTO hoimsystem_ai_infection_write_gate" in statements[0]
    assert next(i for i, sql in enumerate(statements) if "hoimsystem_users" in sql) > 0
    db_session.rollback()


def test_sqlite_additive_migration_up_down_up_preserves_parent_row():
    path = Path(__file__).parents[1] / "alembic/versions/20261021_infection_sources.py"
    spec = importlib.util.spec_from_file_location("infection_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE hoimsystem_users(user_id INTEGER PRIMARY KEY, value TEXT)")
        connection.exec_driver_sql("INSERT INTO hoimsystem_users VALUES(17, '原样😀')")
        for table, pk in [("hoimsystem_patient", "patient_id"), ("hoimsystem_infection_case", "case_id"), ("hoimsystem_ai_audit_event", "event_id")]:
            connection.exec_driver_sql(f"CREATE TABLE {table}({pk} INTEGER PRIMARY KEY)")
        original = connection.exec_driver_sql("SELECT * FROM hoimsystem_users").all()
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            assert all(model.__tablename__ in inspect(connection).get_table_names() for model in INFECTION_SOURCE_MODELS)
            definition = INFECTION_SOURCE_MODELS[2].__table__
            values = dict(
                definition_id="00000000-0000-0000-0000-000000000001",
                payload_json="😀" * (2097152 + 1),
                content_hash="a" * 64,
                status="draft",
                revision=1,
                recorded_at=dt.datetime(2026, 10, 21),
                review_basis="",
                privacy_review="unknown",
                faithfulness_review="unknown",
                revoke_basis="",
                created_by=17,
                create_event_id=1,
            )
            with pytest.raises(IntegrityError), connection.begin_nested():
                connection.execute(definition.insert().values(**values))
            migration.downgrade()
            assert all(model.__tablename__ not in inspect(connection).get_table_names() for model in INFECTION_SOURCE_MODELS)
            migration.upgrade()
        assert connection.exec_driver_sql("SELECT * FROM hoimsystem_users").all() == original
    engine.dispose()
