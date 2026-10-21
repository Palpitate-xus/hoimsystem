"""Historical two-table SQLite migration, before the later dispatch extension.

The frozen revision intentionally lacks the new claim/dispatch Audit columns.
The additive extension has its own full current-ORM up/down/up regression.
"""

import ast
import importlib.util
import re
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.dialects import sqlite

from app.ai.deidentification_run_models import DEIDENTIFICATION_RUN_MODELS
from app.database import Base


def migration_module():
    path = Path(__file__).resolve().parents[1] / "alembic/versions/20261021_deid_runs.py"
    spec = importlib.util.spec_from_file_location("synthetic_deidentification_run_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    assert migration.revision == "20261021_deid_runs" and len(migration.revision) <= 32
    assert migration.down_revision == "20261021_deidentification"
    parsed = ast.parse(path.read_text())
    assert not any(isinstance(node, ast.ImportFrom) and (node.module or "").startswith("app") for node in ast.walk(parsed))
    return migration


def normalize(value):
    return re.sub(r"\s+", " ", value).strip()


def test_actual_frozen_migration_up_down_up_preserves_every_preceding_ddl_and_row():
    migration = migration_module()
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def foreign_keys(conn, _):
        conn.execute("PRAGMA foreign_keys=ON")

    new = {model.__tablename__ for model in DEIDENTIFICATION_RUN_MODELS}
    old = [table for name, table in Base.metadata.tables.items() if name not in new]
    Base.metadata.create_all(engine, tables=old)
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO hoimsystem_users(user_id,username,user_role) VALUES(987653,'synthetic-deid-task','admin')"))
        conn.execute(text("INSERT INTO hoimsystem_patient(patient_id,name) VALUES(987653,'合成迁移原行😀')"))
        before_ddl = conn.execute(text("SELECT type,name,tbl_name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name")).all()
        before_rows = {table.name: conn.execute(table.select()).all() for table in old}
        for action in ("upgrade", "downgrade", "upgrade"):
            migration.op = Operations(MigrationContext.configure(conn))
            getattr(migration, action)()
            expected = {table.name for table in old} | (new if action == "upgrade" else set())
            assert set(inspect(conn).get_table_names()) == expected
            actual_ddl = conn.execute(text("SELECT type,name,tbl_name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name")).all()
            assert [row for row in actual_ddl if row.tbl_name not in new] == before_ddl
            assert {table.name: conn.execute(table.select()).all() for table in old} == before_rows
            if action == "upgrade":
                inspector = inspect(conn)
                for model in DEIDENTIFICATION_RUN_MODELS:
                    table = model.__table__
                    assert {column["name"] for column in inspector.get_columns(table.name)} == set(table.columns.keys()) - {"claim_event_id", "dispatch_event_id"}
                    expected_checks = {
                        constraint.name: normalize(str(constraint.sqltext.compile(dialect=sqlite.dialect(), compile_kwargs={"literal_binds": True})))
                        for constraint in table.constraints
                        if constraint.__class__.__name__ == "CheckConstraint" and constraint.name not in {"ck_deid_result_claim", "ck_deid_result_dispatch"}
                    }
                    actual_checks = {constraint["name"]: normalize(constraint["sqltext"]) for constraint in inspector.get_check_constraints(table.name)}
                    assert actual_checks == expected_checks
                    actual_fk = {(tuple(fk["constrained_columns"]), fk["referred_table"], tuple(fk["referred_columns"])) for fk in inspector.get_foreign_keys(table.name)}
                    expected_fk = {(tuple(c.name for c in fk.columns), fk.referred_table.name, tuple(element.column.name for element in fk.elements)) for fk in table.foreign_key_constraints if not {c.name for c in fk.columns} & {"claim_event_id", "dispatch_event_id"}}
                    assert actual_fk == expected_fk
                    assert {index["name"]: tuple(index["column_names"]) for index in inspector.get_indexes(table.name)} == {
                        index.name: tuple(column.name for column in index.columns) for index in table.indexes
                    }
    engine.dispose()
