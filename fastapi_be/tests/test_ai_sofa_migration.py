"""Exercise the actual additive migration, preserving every pre-existing table."""

import importlib.util
from io import StringIO
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import CheckConstraint, create_engine, inspect, text
from sqlalchemy.dialects import mysql
from sqlalchemy.exc import IntegrityError
from sqlalchemy.schema import CreateIndex, CreateTable

from alembic import command
from app.ai.sofa_models import AISofaAssessment, AISofaChangeAssessment, AISofaRunResult
from app.db_migrate import migrate
from tests.test_inpatient_support_migration import normalize_sql, snapshot

MODELS = (AISofaAssessment, AISofaChangeAssessment, AISofaRunResult)
TABLES = {model.__tablename__ for model in MODELS}
REVISION = "20261020_sofa_assessments"
PARENT = "20261020_organ_support_sources"


def revision_module():
    path = Path(__file__).resolve().parents[1] / "alembic" / "versions" / (REVISION + ".py")
    spec = importlib.util.spec_from_file_location("isolated_sofa_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def offline(operation):
    output = StringIO()
    context = MigrationContext.configure(dialect=mysql.dialect(), opts={"as_sql": True, "output_buffer": output})
    with Operations.context(context):
        getattr(revision_module(), operation)()
    return output.getvalue()


def test_actual_sqlite_up_down_up_preserves_all_old_tables_clocks_and_rows(tmp_path):
    url = "sqlite:///" + str(tmp_path / "sofa.sqlite")
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", url)
    assert migrate(url) == "bootstrapped"
    command.downgrade(config, PARENT)
    engine = create_engine(url)
    original_tables = set(inspect(engine).get_table_names())
    assert not original_tables & TABLES
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO hoimsystem_patient(patient_id,name,identity) VALUES(97001,'synthetic SOFA migration','migration-sofa')"))
        connection.execute(text("INSERT INTO hoimsystem_admission(admission_id,patient_id,status,admission_time) VALUES('legacy-sofa-admission',97001,2,'2001-02-03 04:05:06.123456')"))
        connection.execute(text("INSERT INTO hoimsystem_vital_sign(vital_id,patient_id,pulse,temperature,check_time) VALUES(97001,97001,0,36.5,'2002-03-04 05:06:07.654321')"))
        preserved = snapshot(connection, original_tables - {"alembic_version"})
    for operation in ("up", "down", "up"):
        if operation == "up":
            command.upgrade(config, REVISION)
            inspector = inspect(engine)
            assert set(inspector.get_table_names()) == original_tables | TABLES
            for model in MODELS:
                table = model.__tablename__
                columns = inspector.get_columns(table)
                assert [column["name"] for column in columns] == list(model.__table__.columns.keys())
                assert {column["name"]: column["nullable"] for column in columns} == {column.name: column.nullable for column in model.__table__.columns}
                assert {constraint["name"] for constraint in inspector.get_check_constraints(table)} == {
                    constraint.name for constraint in model.__table__.constraints if isinstance(constraint, CheckConstraint)
                }
                assert {(index["name"], tuple(index["column_names"]), bool(index["unique"])) for index in inspector.get_indexes(table)} == {
                    (index.name, tuple(index.columns.keys()), index.unique) for index in model.__table__.indexes
                }
                assert {(fk["constrained_columns"][0], fk["referred_table"], fk["referred_columns"][0]) for fk in inspector.get_foreign_keys(table)} == {
                    (fk.parent.name, fk.column.table.name, fk.column.name) for fk in model.__table__.foreign_keys
                }
        else:
            command.downgrade(config, PARENT)
            assert set(inspect(engine).get_table_names()) == original_tables
        with engine.connect() as connection:
            assert snapshot(connection, original_tables - {"alembic_version"}) == preserved
            if operation == "up":
                assert all(connection.scalar(text("SELECT COUNT(*) FROM " + name)) == 0 for name in TABLES)
    engine.dispose()


def test_mysql_offline_adds_only_three_tables_with_ten_utc6_and_five_mediumtext_columns():
    module = revision_module()
    assert module.revision == REVISION and module.down_revision == PARENT
    assert module.branch_labels is module.depends_on is None
    sql = offline("upgrade")
    assert sql.count("CREATE TABLE ") == 3 and sql.count("DATETIME(6)") == 10 and sql.count("MEDIUMTEXT NOT NULL") == 5
    assert all(token not in sql for token in ("ALTER TABLE", "INSERT INTO", "UPDATE ", "DELETE FROM"))
    normalized = normalize_sql(sql)
    for model in MODELS:
        assert normalize_sql(str(CreateTable(model.__table__).compile(dialect=mysql.dialect()))) in normalized
        for index in model.__table__.indexes:
            assert normalize_sql(str(CreateIndex(index).compile(dialect=mysql.dialect()))) in normalized
    assert [statement.strip() for statement in offline("downgrade").split(";") if statement.strip()] == ["DROP TABLE " + model.__tablename__ for model in reversed(MODELS)]


def test_migrated_daily_table_retains_full_large_unicode_and_rejects_false_governance_or_clocks():
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        with Operations.context(MigrationContext.configure(connection)):
            revision_module().upgrade()
        values = {
            "id": "synthetic-daily",
            "pid": 1,
            "adm": "synthetic-admission",
            "profile": "synthetic-profile",
            "hash": "a" * 64,
            "start": "2026-10-19 12:00:00.123456",
            "end": "2026-10-20 12:00:00.123456",
            "asof": "2026-10-20 12:00:00.123456",
            "evaluation": "2026-10-20 12:00:01.123456",
            "created": "2026-10-20 12:00:01.123456",
            "actor": 1,
            "snapshot": '{"synthetic":"' + "完整原件" * 12000 + '"}',
            "projection": '{"synthetic":"' + "来源" * 18000 + '"}',
            "status": "active",
            "revision": 1,
        }
        insert = text(
            "INSERT INTO hoimsystem_ai_sofa_assessment(assessment_id,patient_id,admission_id,rule_profile_id,rule_profile_content_hash,recipe_digest,policy_digest,manifest_digest,"
            "period_start,period_end,as_of,evaluation_at,created_at,created_by,schema_version,snapshot_json,projection_json,projection_hash,content_hash,status,revision,revoke_reason) "
            "VALUES(:id,:pid,:adm,:profile,:hash,:hash,:hash,:hash,:start,:end,:asof,:evaluation,:created,:actor,'sofa1_source_v1',:snapshot,:projection,:hash,:hash,:status,:revision,'')"
        )
        connection.execute(insert, values)
        stored = connection.execute(text("SELECT snapshot_json,projection_json FROM hoimsystem_ai_sofa_assessment")).one()
        assert stored == (values["snapshot"], values["projection"])
        assert all(len(value.encode("utf-8")) > 65535 for value in stored)
        for changes in ({"revision": 2}, {"status": "revoked", "revision": 2}, {"start": values["end"]}, {"asof": values["start"]}, {"created": values["end"]}):
            with pytest.raises(IntegrityError):
                connection.execute(insert, {**values, **changes, "id": "invalid-" + str(changes)})
        changed = connection.execute(
            text(
                "UPDATE hoimsystem_ai_sofa_assessment SET status='revoked', revision=2, revoked_at='2026-10-20 12:01:00.654321', revoked_by=2, revoke_reason='synthetic explicit correction' "
                "WHERE assessment_id=:id AND status='active' AND revision=1"
            ),
            {"id": values["id"]},
        )
        assert changed.rowcount == 1
        assert connection.scalar(text("SELECT content_hash FROM hoimsystem_ai_sofa_assessment")) == values["hash"]
    engine.dispose()
