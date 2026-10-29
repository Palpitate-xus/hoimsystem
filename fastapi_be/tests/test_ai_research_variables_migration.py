"""Execute the frozen incremental migration against an isolated populated DB."""

import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, event, inspect, text

from app.ai.research_variables_models import RESEARCH_VARIABLE_MODELS
from app.database import Base


def signature(conn, name):
    inspector = inspect(conn)
    return {
        "columns": [(c["name"], str(c["type"]), c["nullable"], c["primary_key"]) for c in inspector.get_columns(name)],
        "checks": sorted((c["name"], "".join(c["sqltext"].split())) for c in inspector.get_check_constraints(name)),
        "foreign_keys": sorted((tuple(c["constrained_columns"]), c["referred_table"], tuple(c["referred_columns"])) for c in inspector.get_foreign_keys(name)),
        "indexes": sorted((c["name"], tuple(c["column_names"]), bool(c["unique"])) for c in inspector.get_indexes(name)),
    }


def test_up_down_up_preserves_every_old_ddl_row_and_matches_actual_orm_schema():
    path = Path(__file__).resolve().parents[1] / "alembic/versions/20261021_research_variables.py"
    assert "from app" not in path.read_text()
    spec = importlib.util.spec_from_file_location("isolated_variable_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    assert migration.revision == "20261021_research_variables"
    assert migration.down_revision == "20261021_research_prompt_origin"
    engines = [create_engine("sqlite:///:memory:") for _ in range(2)]
    for engine in engines:

        @event.listens_for(engine, "connect")
        def fk_on(conn, _):
            conn.execute("PRAGMA foreign_keys=ON")

    new = {m.__tablename__ for m in RESEARCH_VARIABLE_MODELS}
    old = [t for name, t in Base.metadata.tables.items() if name not in new]
    Base.metadata.create_all(engines[0], tables=old)
    Base.metadata.create_all(engines[1])
    with engines[0].begin() as conn, engines[1].connect() as expected:
        conn.execute(Base.metadata.tables["hoimsystem_users"].insert().values(user_id=987651, username='synthetic-variable', user_role='admin'))
        conn.execute(text("INSERT INTO hoimsystem_patient(patient_id,name) VALUES(987651,'隔离合成变量基础')"))
        before = conn.execute(text("SELECT type,name,tbl_name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name")).all()
        for action in ("upgrade", "downgrade", "upgrade"):
            migration.op = Operations(MigrationContext.configure(conn))
            getattr(migration, action)()
            assert set(inspect(conn).get_table_names()) == {t.name for t in old} | (new if action == "upgrade" else set())
            after = conn.execute(text("SELECT type,name,tbl_name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name")).all()
            assert [r for r in after if r.tbl_name not in new] == before
            assert conn.execute(text("SELECT username,user_role FROM hoimsystem_users WHERE user_id=987651")).one() == ("synthetic-variable", "admin")
            assert conn.execute(text("SELECT name FROM hoimsystem_patient WHERE patient_id=987651")).scalar_one() == "隔离合成变量基础"
            if action == "upgrade":
                assert {name: signature(conn, name) for name in new} == {name: signature(expected, name) for name in new}
    for engine in engines:
        engine.dispose()
