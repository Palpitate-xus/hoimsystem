"""Incremental real SQLite DDL/row preservation; MySQL here compiles only."""

import ast
import importlib.util
import io
from pathlib import Path
from types import SimpleNamespace

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.dialects import mysql, sqlite
from sqlalchemy.exc import IntegrityError
from sqlalchemy.schema import CreateTable

from app.ai.deidentification_run_models import AIDeidentificationRunResult
from app.database import Base
from tests.test_ai_deidentification_run_migration import migration_module as historical_migration
from tests.test_ai_deidentification_run_migration import normalize
from tests.test_ai_deidentification_run_models import actual_foreign_keys as actual_foreign_keys  # noqa: F401
from tests.test_ai_deidentification_run_models import artifact, audit, pending


def migration_module():
    path = Path(__file__).resolve().parents[1] / "alembic/versions/20261021_deid_dispatch.py"
    spec = importlib.util.spec_from_file_location("synthetic_deid_dispatch_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.revision == "20261021_deid_dispatch" and module.down_revision == "20261021_deid_runs"
    assert len(module.revision) <= 32
    assert not any(isinstance(node, ast.ImportFrom) and (node.module or "").startswith("app") for node in ast.walk(ast.parse(path.read_text())))
    return module


def test_actual_incremental_up_down_up_preserves_preexisting_ddl_rows_and_matches_current_orm():
    migration, old_migration = migration_module(), historical_migration()
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def fk(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")

    task_tables = {"hoimsystem_ai_deidentification_run_source", "hoimsystem_ai_deidentification_run_result"}
    prior = [table for table in Base.metadata.sorted_tables if table.name not in task_tables]
    Base.metadata.create_all(engine, tables=prior)
    target = AIDeidentificationRunResult.__tablename__
    with engine.begin() as conn:
        old_migration.op = Operations(MigrationContext.configure(conn))
        old_migration.upgrade()
        conn.execute(text("INSERT INTO hoimsystem_users(user_id,username,user_role) VALUES(987652,'synthetic-deid-dispatch','admin')"))
        conn.execute(text("INSERT INTO hoimsystem_patient(patient_id,name) VALUES(987652,'合成增量迁移原行🧪')"))

        def ddl():
            return conn.execute(text("SELECT type,name,tbl_name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name")).all()

        before = [row for row in ddl() if row.tbl_name != target]
        tables = [table for table in Base.metadata.sorted_tables if table.name != target]
        rows = {table.name: conn.execute(table.select()).all() for table in tables}
        for action in ("upgrade", "downgrade", "upgrade"):
            migration.op = Operations(MigrationContext.configure(conn))
            getattr(migration, action)()
            assert [row for row in ddl() if row.tbl_name != target] == before
            assert {table.name: conn.execute(table.select()).all() for table in tables} == rows
            actual = inspect(conn)
            fields = {column["name"] for column in actual.get_columns(target)}
            expected = set(AIDeidentificationRunResult.__table__.columns.keys())
            assert fields == (expected if action == "upgrade" else expected - {"claim_event_id", "dispatch_event_id"})
            if action == "upgrade":
                table = AIDeidentificationRunResult.__table__
                assert {c["name"]: normalize(c["sqltext"]) for c in actual.get_check_constraints(target)} == {
                    c.name: normalize(str(c.sqltext.compile(dialect=sqlite.dialect(), compile_kwargs={"literal_binds": True}))) for c in table.constraints if c.__class__.__name__ == "CheckConstraint"
                }
                assert {tuple(c["column_names"]) for c in actual.get_unique_constraints(target)} == {("claim_event_id",), ("dispatch_event_id",)}
                fk_fields = {tuple(c["constrained_columns"]) for c in actual.get_foreign_keys(target)}
                assert {("claim_event_id",), ("dispatch_event_id",), ("run_id",), ("usage_event_id",), ("accept_event_id",)} == fk_fields
    engine.dispose()
    compiled = str(CreateTable(AIDeidentificationRunResult.__table__).compile(dialect=mysql.dialect()))
    assert "fk_deid_claim_audit" in compiled and "fk_deid_dispatch_audit" in compiled
    assert "AUTO_INCREMENT" not in compiled and "MEDIUMTEXT" in compiled


@pytest.mark.parametrize("field,value", [("claim_event_id", -1), ("claim_event_id", 0), ("claim_event_id", 2147483647), ("dispatch_event_id", 0), ("dispatch_event_id", 2147483647)])
def test_actual_incremental_receipt_columns_require_positive_real_audit_fk(db_session, seed_data, field, value):
    source = artifact(db_session, seed_data)
    row = pending(db_session, source)
    if field == "dispatch_event_id":
        row.claim_event_id = audit(db_session, source.requested_by, source.run_id, "deidentification.task.claim").event_id
    setattr(row, field, value)
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_dispatch_requires_distinct_claim_and_downgrade_cannot_erase_claim_identity(db_session, seed_data):
    source = artifact(db_session, seed_data)
    row = pending(db_session, source)
    identifier = audit(db_session, source.requested_by, source.run_id, "deidentification.task.claim").event_id
    row.claim_event_id = identifier
    db_session.flush()
    module = migration_module()
    module.op = Operations(MigrationContext.configure(db_session.connection()))
    with pytest.raises(RuntimeError, match="cannot lose"):
        module.downgrade()
    row.dispatch_event_id = identifier
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_mysql_downgrade_compiles_fk_drop_before_its_supporting_unique_index():
    """Real MySQL emits 1553 if its FK still needs the index being removed.

    The empty-receipt guard executes against actual SQLite here. Only the
    remaining dialect DDL is compiled; private MySQL separately executes it.
    """
    output = io.StringIO()
    operations = Operations(MigrationContext.configure(dialect_name="mysql", opts={"as_sql": True, "output_buffer": output}))
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE hoimsystem_ai_deidentification_run_result(run_id TEXT,claim_event_id INTEGER,dispatch_event_id INTEGER)"))
        module = migration_module()
        module.op = SimpleNamespace(get_bind=lambda: conn, batch_alter_table=operations.batch_alter_table)
        module.downgrade()
    engine.dispose()
    compiled = output.getvalue()
    for short in ("dispatch", "claim"):
        foreign = compiled.index("DROP FOREIGN KEY fk_deid_" + short + "_audit")
        unique = compiled.index("DROP INDEX uq_deid_" + short + "_audit")
        column = compiled.index("DROP COLUMN " + short + "_event_id")
        assert foreign < unique < column
