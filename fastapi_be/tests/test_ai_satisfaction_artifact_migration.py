"""Additive actual SQLite migrations and exact compiled MySQL artifact shape."""

import importlib.util
from io import StringIO
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import CheckConstraint, create_engine, inspect, text
from sqlalchemy.dialects import mysql
from sqlalchemy.schema import CreateTable

from app.ai.satisfaction_artifact_models import AISatisfactionRunArtifact
from app.database import Base
from tests.test_inpatient_support_migration import snapshot


def migration():
    path = Path(__file__).resolve().parents[1] / "alembic/versions/20261021_satisfaction_artifacts.py"
    spec = importlib.util.spec_from_file_location("isolated_satisfaction_artifact_migration", path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def test_actual_single_additive_up_down_up_preserves_all_previous_ddl_and_rows(tmp_path):
    table = AISatisfactionRunArtifact.__table__
    engine = create_engine("sqlite:///" + str(tmp_path / "satisfaction-artifact.sqlite"))
    Base.metadata.create_all(engine, tables=[row for row in Base.metadata.sorted_tables if row.name != table.name])
    names = set(inspect(engine).get_table_names())
    with engine.begin() as conn:
        conn.execute(Base.metadata.tables["hoimsystem_users"].insert().values(user_id=90771, username='synthetic-satisfaction-artifact', user_role='super_admin'))
        conn.execute(text("INSERT INTO hoimsystem_review(review_id,score,comment) VALUES(90772,-1,'原异常评分及原评论未被任务artifact改写')"))
        prior = snapshot(conn, names)
    for action in ("upgrade", "downgrade", "upgrade"):
        with engine.begin() as conn, Operations.context(MigrationContext.configure(conn)):
            getattr(migration(), action)()
        assert set(inspect(engine).get_table_names()) == names | ({table.name} if action == "upgrade" else set())
        with engine.connect() as conn:
            assert snapshot(conn, names) == prior
        if action == "upgrade":
            assert {row["name"]: row["nullable"] for row in inspect(engine).get_columns(table.name)} == {row.name: row.nullable for row in table.columns if row.name != "usage_event_id"}
            assert {row["name"]: " ".join(row["sqltext"].split()) for row in inspect(engine).get_check_constraints(table.name)} == {
                row.name: " ".join(str(row.sqltext.compile(compile_kwargs={"literal_binds": True, "include_table": False})).replace(table.name + ".", "").split())
                for row in table.constraints
                if isinstance(row, CheckConstraint) and row.name != "ck_sat_artifact_usage"
            }
            assert len(inspect(engine).get_foreign_keys(table.name)) == 4
    engine.dispose()


def test_mysql_ddl_specific_audit_foreign_key_complete_bytes_and_two_utc6_clocks():
    value = migration()
    assert value.down_revision == "20261021_satisfaction_sources"
    output = StringIO()
    with Operations.context(MigrationContext.configure(dialect=mysql.dialect(), opts={"as_sql": True, "output_buffer": output})):
        value.upgrade()
    ddl = output.getvalue()
    actual = str(CreateTable(AISatisfactionRunArtifact.__table__).compile(dialect=mysql.dialect()))
    for text_ in (ddl, actual):
        assert text_.count("DATETIME(6)") == 2 and text_.count("MEDIUMTEXT") == 1
        assert "hoimsystem_ai_audit_event" in text_ and "receipt_event_id" in text_
        assert "8388608" in text_ and "CAST(result_json AS BINARY)" in text_
        assert "accepted_lease" in text_ and "AUTO_INCREMENT" not in text_
