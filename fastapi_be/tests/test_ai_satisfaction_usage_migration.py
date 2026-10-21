"""Fourth additive receipt migration preserves its prior Artifact stage."""

import importlib.util
from io import StringIO
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect
from sqlalchemy.dialects import mysql

from app.ai.satisfaction_artifact_models import AISatisfactionRunArtifact
from app.database import Base
from tests.test_ai_satisfaction_artifact_migration import migration as artifact_migration
from tests.test_inpatient_support_migration import snapshot


def migration():
    path = Path(__file__).resolve().parents[1] / "alembic/versions/20261021_sat_usage_receipt.py"
    spec = importlib.util.spec_from_file_location("satisfaction_usage_migration", path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def test_fourth_actual_additive_up_down_up_keeps_all_other_tables_and_original_artifact_stage(tmp_path):
    engine = create_engine("sqlite:///" + str(tmp_path / "satisfaction-usage.sqlite"))
    table = AISatisfactionRunArtifact.__table__
    Base.metadata.create_all(engine, tables=[row for row in Base.metadata.sorted_tables if row.name != table.name])
    with engine.begin() as conn, Operations.context(MigrationContext.configure(conn)):
        artifact_migration().upgrade()
    old_names = set(inspect(engine).get_table_names()) - {table.name}
    with engine.connect() as conn:
        original = snapshot(conn, old_names)
    for action in ("upgrade", "downgrade", "upgrade"):
        with engine.begin() as conn, Operations.context(MigrationContext.configure(conn)):
            getattr(migration(), action)()
        columns = {row["name"] for row in inspect(engine).get_columns(table.name)}
        assert ("usage_event_id" in columns) == (action == "upgrade")
        assert len(inspect(engine).get_foreign_keys(table.name)) == (5 if action == "upgrade" else 4)
        with engine.connect() as conn:
            assert snapshot(conn, old_names) == original
    engine.dispose()


def test_fourth_mysql_compiles_only_local_artifact_alter_separate_usage_fk():
    value = migration()
    assert value.down_revision == "20261021_satisfaction_artifacts"
    output = StringIO()
    with Operations.context(MigrationContext.configure(dialect=mysql.dialect(), opts={"as_sql": True, "output_buffer": output})):
        value.upgrade()
    ddl = output.getvalue()
    assert "ALTER TABLE hoimsystem_ai_satisfaction_run_artifact" in ddl
    assert "FOREIGN KEY(usage_event_id) REFERENCES hoimsystem_ai_audit_event" in ddl
    assert "UNIQUE (usage_event_id)" in ddl and "ck_sat_artifact_usage" in ddl
    assert "CREATE TABLE" not in ddl and "DROP TABLE" not in ddl


def test_mysql_downgrade_drops_usage_foreign_key_before_its_supporting_unique_index():
    output = StringIO()
    with Operations.context(MigrationContext.configure(dialect=mysql.dialect(), opts={"as_sql": True, "output_buffer": output})):
        migration().downgrade()
    ddl = output.getvalue()
    assert ddl.index("DROP FOREIGN KEY fk_sat_artifact_usage") < ddl.index("DROP INDEX uq_sat_artifact_usage") < ddl.index("DROP COLUMN usage_event_id")
