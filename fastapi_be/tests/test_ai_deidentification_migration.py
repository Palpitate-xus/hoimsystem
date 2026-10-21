"""Actual isolated SQLite additive up/down/up; MySQL is compile-only here."""

import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, event, inspect, text

from app.ai.deidentification_models import DEIDENTIFICATION_MODELS
from app.database import Base


def test_frozen_standalone_migration_up_down_up_preserves_all_existing_ddl_and_rows():
    path = Path(__file__).resolve().parents[1] / "alembic/versions/20261021_deidentification.py"
    spec = importlib.util.spec_from_file_location("synthetic_deidentification_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    assert migration.revision == "20261021_deidentification" and migration.down_revision == "20261021_research_cohort"
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def foreign_keys(conn, _):
        conn.execute("PRAGMA foreign_keys=ON")

    new = {m.__tablename__ for m in DEIDENTIFICATION_MODELS}
    old = [t for name, t in Base.metadata.tables.items() if name not in new]
    Base.metadata.create_all(engine, tables=old)
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO hoimsystem_users(user_id,username,user_role) VALUES(987654,'synthetic-research','admin')"))
        conn.execute(text("INSERT INTO hoimsystem_patient(patient_id,name) VALUES(987654,'隔离合成有限研究成员')"))
        before = conn.execute(text("SELECT type,name,tbl_name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name")).all()
        for action in ("upgrade", "downgrade", "upgrade"):
            migration.op = Operations(MigrationContext.configure(conn))
            getattr(migration, action)()
            expected = {t.name for t in old} | (new if action == "upgrade" else set())
            assert set(inspect(conn).get_table_names()) == expected
            current = conn.execute(text("SELECT type,name,tbl_name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name")).all()
            assert [r for r in current if r.tbl_name not in new] == before
            assert conn.execute(text("SELECT username,user_role FROM hoimsystem_users WHERE user_id=987654")).one() == ("synthetic-research", "admin")
            assert conn.execute(text("SELECT name FROM hoimsystem_patient WHERE patient_id=987654")).scalar_one() == "隔离合成有限研究成员"
            if action == "upgrade":
                for model in DEIDENTIFICATION_MODELS:
                    actual = inspect(conn).get_columns(model.__tablename__)
                    assert {c["name"] for c in actual} == set(model.__table__.columns.keys())
                    assert len(inspect(conn).get_check_constraints(model.__tablename__)) == len([c for c in model.__table__.constraints if c.__class__.__name__ == "CheckConstraint"])
                    assert len(inspect(conn).get_foreign_keys(model.__tablename__)) == len(model.__table__.foreign_key_constraints)
    engine.dispose()
