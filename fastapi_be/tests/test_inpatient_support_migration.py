"""One additive revision: actual SQLite lifecycle, old facts and exact MySQL model DDL."""

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
from app.db_migrate import migrate
from app.inpatient_infection_models import InpatientInfectionEpisodeSource
from app.inpatient_respiratory_models import InpatientArterialPairSource, InpatientMapSource, InpatientRespiratorySource
from app.inpatient_vasoactive_models import AIVasoactiveDrugMapping, InpatientVasoactiveSource

MODELS = (AIVasoactiveDrugMapping, InpatientMapSource, InpatientRespiratorySource, InpatientArterialPairSource, InpatientVasoactiveSource, InpatientInfectionEpisodeSource)
TABLES = {model.__tablename__ for model in MODELS}
REVISION = "20261020_organ_support_sources"
PARENT = "20261020_qsofa_sources"


def revision_module():
    path = Path(__file__).resolve().parents[1] / "alembic" / "versions" / (REVISION + ".py")
    spec = importlib.util.spec_from_file_location("isolated_organ_support_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def offline(operation):
    output = StringIO()
    context = MigrationContext.configure(dialect=mysql.dialect(), opts={"as_sql": True, "output_buffer": output})
    with Operations.context(context):
        getattr(revision_module(), operation)()
    return output.getvalue()


def normalize_sql(value):
    return " ".join(value.strip().rstrip(";").split())


def snapshot(connection, names):
    return {
        name: {
            "ddl": connection.execute(text("SELECT sql FROM sqlite_master WHERE type='table' AND name=:name"), {"name": name}).scalar_one(),
            "rows": connection.execute(text('SELECT * FROM "' + name + '"')).all(),
        }
        for name in sorted(names)
    }


def test_actual_sqlite_up_down_up_adds_only_six_tables_and_preserves_all_old_ddl_and_rows(tmp_path):
    url = "sqlite:///" + str(tmp_path / "organ-support.sqlite")
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", url)
    assert migrate(url) == "bootstrapped"
    command.downgrade(config, PARENT)
    engine = create_engine(url)
    before_tables = set(inspect(engine).get_table_names())
    assert not (before_tables & TABLES)
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO hoimsystem_patient(patient_id,name,identity) VALUES(96001,'synthetic original support','migration-organ-support')"))
        connection.execute(text("INSERT INTO hoimsystem_admission(admission_id,patient_id,status,admission_time) VALUES('legacy-support-admission',96001,2,'2001-02-03 04:05:06.123456')"))
        connection.execute(text("INSERT INTO hoimsystem_vital_sign(vital_id,patient_id,pulse,temperature,check_time) VALUES(96001,96001,0,36.5,'2002-03-04 05:06:07.654321')"))
        connection.execute(
            text(
                "INSERT INTO hoimsystem_inpatient_observation(observation_id,patient_id,admission_id,observed_at,recorded_at,created_by,schema_version,payload_json,content_hash,status,revision,revoke_reason) "
                "VALUES('legacy-point',96001,'legacy-support-admission','2003-04-05 06:07:08.123456','2003-04-05 06:08:08.654321',1,'inpatient_observation_v1','{}',:hash,'active',1,'')"
            ),
            {"hash": "a" * 64},
        )
        preserved = snapshot(connection, before_tables - {"alembic_version"})
    for operation in ("up", "down", "up"):
        if operation == "up":
            command.upgrade(config, REVISION)
            assert set(inspect(engine).get_table_names()) == before_tables | TABLES
            inspector = inspect(engine)
            for model in MODELS:
                table = model.__tablename__
                actual_columns = inspector.get_columns(table)
                assert [column["name"] for column in actual_columns] == list(model.__table__.columns.keys())
                assert {column["name"]: column["nullable"] for column in actual_columns} == {column.name: column.nullable for column in model.__table__.columns}
                assert {constraint["name"] for constraint in inspector.get_check_constraints(table)} == {
                    constraint.name for constraint in model.__table__.constraints if isinstance(constraint, CheckConstraint)
                }
                assert {(index["name"], tuple(index["column_names"]), bool(index["unique"])) for index in inspector.get_indexes(table)} == {
                    (index.name, tuple(index.columns.keys()), index.unique) for index in model.__table__.indexes
                }
                expected_foreign_keys = {(fk.parent.name, fk.column.table.name, fk.column.name) for fk in model.__table__.foreign_keys}
                assert {(fk["constrained_columns"][0], fk["referred_table"], fk["referred_columns"][0]) for fk in inspector.get_foreign_keys(table)} == expected_foreign_keys
        else:
            command.downgrade(config, PARENT)
            assert set(inspect(engine).get_table_names()) == before_tables
        with engine.connect() as connection:
            assert snapshot(connection, before_tables - {"alembic_version"}) == preserved
            if operation == "up":
                assert all(connection.scalar(text("SELECT COUNT(*) FROM " + name)) == 0 for name in TABLES)
    engine.dispose()


def test_mysql_offline_additive_ddl_exactly_matches_six_real_orm_definitions_and_18_utc6_clocks():
    module = revision_module()
    assert module.revision == REVISION and module.down_revision == PARENT and module.branch_labels is module.depends_on is None
    sql = offline("upgrade")
    assert sql.count("CREATE TABLE ") == 6 and sql.count("DATETIME(6)") == 18
    assert sql.count("reference_snapshot_json MEDIUMTEXT NOT NULL") == 5
    assert "ALTER TABLE" not in sql and "INSERT INTO" not in sql and "UPDATE " not in sql and "DELETE FROM" not in sql
    normalized = normalize_sql(sql)
    for model in MODELS:
        assert normalize_sql(str(CreateTable(model.__table__).compile(dialect=mysql.dialect()))) in normalized
        for index in model.__table__.indexes:
            assert normalize_sql(str(CreateIndex(index).compile(dialect=mysql.dialect()))) in normalized
    drops = [statement.strip() for statement in offline("downgrade").split(";") if statement.strip()]
    assert drops == ["DROP TABLE " + model.__tablename__ for model in reversed(MODELS)]


@pytest.mark.parametrize("model", MODELS[1:])
def test_migration_clinical_checks_accept_nullable_event_and_valid_cas_governance_but_reject_invalid_originals(model):
    engine = create_engine("sqlite:///:memory:")
    module = revision_module()
    with engine.begin() as connection:
        with Operations.context(MigrationContext.configure(connection)):
            module.upgrade()
        table = model.__tablename__
        values = {
            "id": "synthetic-immutable-source",
            "pid": 1,
            "adm": "original-admission",
            "event": None,
            "recorded": "2026-10-20 12:00:00.123456",
            "actor": 1,
            "schema": "synthetic-test-schema",
            "payload": "{}",
            "refs": "{}",
            "qualification": "{}",
            "hash": "a" * 64,
            "status": "active",
            "revision": 1,
            "reason": "",
        }
        insert = text(
            "INSERT INTO "
            + table
            + "(support_source_id,patient_id,admission_id,event_at,recorded_at,created_by,schema_version,payload_json,reference_snapshot_json,author_qualification_json,content_hash,status,revision,revoke_reason) "
            "VALUES(:id,:pid,:adm,:event,:recorded,:actor,:schema,:payload,:refs,:qualification,:hash,:status,:revision,:reason)"
        )
        connection.execute(insert, values)
        assert connection.scalar(text("SELECT event_at FROM " + table)) is None
        with pytest.raises(IntegrityError):
            connection.execute(insert, {**values, "id": "future-event", "event": "2026-10-20 12:00:00.123457"})
        with pytest.raises(IntegrityError):
            connection.execute(insert, {**values, "id": "false-revision", "revision": 2})
        with pytest.raises(IntegrityError):
            connection.execute(insert, {**values, "id": "revoked-without-fields", "status": "revoked", "revision": 2})
        with pytest.raises(IntegrityError):
            connection.execute(insert, {**values, "id": "invalid-status", "status": "draft"})
        changed = connection.execute(
            text(
                "UPDATE "
                + table
                + " SET status='revoked', revision=2, revoked_at='2026-10-20 12:01:00.654321', revoked_by=2, revoke_reason='synthetic explicit correction' WHERE support_source_id=:id AND status='active' AND revision=1"
            ),
            {"id": values["id"]},
        )
        assert changed.rowcount == 1
        duplicate = connection.execute(text("UPDATE " + table + " SET revision=2 WHERE support_source_id=:id AND status='active' AND revision=1"), {"id": values["id"]})
        assert duplicate.rowcount == 0
        assert connection.execute(text("SELECT status,revision,content_hash FROM " + table)).one() == ("revoked", 2, values["hash"])
    engine.dispose()
