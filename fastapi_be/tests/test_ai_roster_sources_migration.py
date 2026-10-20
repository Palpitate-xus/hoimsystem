"""Actual additive workforce migration, unchanged legacy scheduling, and SQL guards."""

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
from app.ai.roster_models import AIRosterSource
from app.db_migrate import migrate
from tests.test_inpatient_support_migration import normalize_sql, snapshot

REVISION = "20261020_roster_sources"
PARENT = "20261020_sofa_assessments"
TABLE = AIRosterSource.__tablename__


def revision_module():
    path = Path(__file__).resolve().parents[1] / "alembic" / "versions" / (REVISION + ".py")
    spec = importlib.util.spec_from_file_location("isolated_roster_source_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def offline(operation):
    output = StringIO()
    with Operations.context(MigrationContext.configure(dialect=mysql.dialect(), opts={"as_sql": True, "output_buffer": output})):
        getattr(revision_module(), operation)()
    return output.getvalue()


def test_workforce_migration_up_down_up_preserves_complete_legacy_scheduling(tmp_path):
    url = "sqlite:///" + str(tmp_path / "roster.sqlite")
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", url)
    assert migrate(url) == "bootstrapped"
    command.downgrade(config, PARENT)
    engine = create_engine(url)
    originals = set(inspect(engine).get_table_names())
    assert TABLE not in originals
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO hoimsystem_department(department_id,name) VALUES(90101,'合成旧科室')"))
        connection.execute(text("INSERT INTO hoimsystem_doctor(doctor_id,name,department_id,title) VALUES(90102,'合成旧人员',90101,'原职称非资格')"))
        connection.execute(text("INSERT INTO hoimsystem_doctor_schedule(schedule_id,doctor_id,week,time,number,specialist) VALUES(90103,90102,'未知','?',0,NULL)"))
        preserved = snapshot(connection, originals - {"alembic_version"})
    for action in ("up", "down", "up"):
        if action == "up":
            command.upgrade(config, REVISION)
            inspector = inspect(engine)
            assert set(inspector.get_table_names()) == originals | {TABLE}
            assert [(column["name"], column["nullable"]) for column in inspector.get_columns(TABLE)] == [(column.name, column.nullable) for column in AIRosterSource.__table__.columns]
            assert {constraint["name"] for constraint in inspector.get_check_constraints(TABLE)} == {
                constraint.name for constraint in AIRosterSource.__table__.constraints if isinstance(constraint, CheckConstraint)
            }
            assert {(index["name"], tuple(index["column_names"]), bool(index["unique"])) for index in inspector.get_indexes(TABLE)} == {
                (index.name, tuple(index.columns.keys()), index.unique) for index in AIRosterSource.__table__.indexes
            }
            assert {(fk["constrained_columns"][0], fk["referred_table"], fk["referred_columns"][0]) for fk in inspector.get_foreign_keys(TABLE)} == {
                (fk.parent.name, fk.column.table.name, fk.column.name) for fk in AIRosterSource.__table__.foreign_keys
            }
        else:
            command.downgrade(config, PARENT)
            assert set(inspect(engine).get_table_names()) == originals
        with engine.connect() as connection:
            assert snapshot(connection, originals - {"alembic_version"}) == preserved
    engine.dispose()


def test_mysql_source_ddl_is_one_additive_table_with_three_utc6_and_two_complete_originals():
    module = revision_module()
    assert module.revision == REVISION and module.down_revision == PARENT
    assert module.branch_labels is module.depends_on is None
    sql = offline("upgrade")
    assert sql.count("CREATE TABLE ") == 1 and sql.count("DATETIME(6)") == 3 and sql.count("MEDIUMTEXT NOT NULL") == 2
    assert all(token not in sql for token in ("ALTER TABLE", "INSERT INTO", "UPDATE ", "DELETE FROM"))
    normalized = normalize_sql(sql)
    assert normalize_sql(str(CreateTable(AIRosterSource.__table__).compile(dialect=mysql.dialect()))) in normalized
    for index in AIRosterSource.__table__.indexes:
        assert normalize_sql(str(CreateIndex(index).compile(dialect=mysql.dialect()))) in normalized
    assert [part.strip() for part in offline("downgrade").split(";") if part.strip()] == ["DROP TABLE " + TABLE]


@pytest.fixture
def source_table():
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        with Operations.context(MigrationContext.configure(connection)):
            revision_module().upgrade()
    yield engine
    engine.dispose()


def insert_source(connection, **changes):
    values = {
        "id": "synthetic-roster-source",
        "kind": "qualification",
        "doctor": 1,
        "payload": '{"synthetic":"' + "资格依据非真实患者" * 3000 + '"}',
        "status": "draft",
        "revision": 1,
        "recorded": "2026-10-20 12:00:00.123456",
        "reviewed": None,
        "reviewer": None,
        "review_basis": "",
        "revoked": None,
        "revoker": None,
        "reason": "",
        **changes,
    }
    connection.execute(
        text(
            "INSERT INTO hoimsystem_ai_roster_source(source_record_id,source_kind,department_id,doctor_id,schema_version,payload_json,parent_binding_json,"
            "content_hash,recorded_at,created_by,status,revision,reviewed_by,reviewed_at,review_basis_note,revoked_by,revoked_at,revoke_reason) "
            "VALUES(:id,:kind,1,:doctor,'roster_fact_v1',:payload,'{}','aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',"
            ":recorded,1,:status,:revision,:reviewer,:reviewed,:review_basis,:revoker,:revoked,:reason)"
        ),
        values,
    )
    return values


@pytest.mark.parametrize(
    "changes",
    [
        {"kind": "invented"},
        {"doctor": None},
        {"status": "draft", "revision": 2},
        {"status": "published", "revision": 2},
        {"status": "rejected", "revision": 2},
        {"status": "published", "revision": 2, "reviewer": 2, "reviewed": "2026-10-20 11:59:59.123456", "review_basis": "synthetic reviewed"},
        {"status": "revoked", "revision": 2},
        {"status": "revoked", "revision": 3, "revoker": 2, "revoked": "2026-10-20 12:02:00.654321", "reason": "synthetic revoke"},
        {"payload": "x" * 262145},
    ],
)
def test_actual_sql_rejects_false_source_states_clocks_and_overflow(source_table, changes):
    with source_table.begin() as connection, pytest.raises(IntegrityError):
        insert_source(connection, **changes)


def test_actual_sql_review_and_revoke_keep_complete_large_unicode_and_original_hash(source_table):
    with source_table.begin() as connection:
        values = insert_source(connection)
        assert len(values["payload"].encode()) > 65535
        assert connection.scalar(text("SELECT payload_json FROM " + TABLE)) == values["payload"]
        update = text(
            "UPDATE hoimsystem_ai_roster_source SET status='published',revision=2,reviewed_by=2,"
            "reviewed_at='2026-10-20 12:01:00.123456',review_basis_note='synthetic explicit review' "
            "WHERE source_record_id=:id AND status='draft' AND revision=1"
        )
        assert connection.execute(update, {"id": values["id"]}).rowcount == 1
        assert connection.execute(update, {"id": values["id"]}).rowcount == 0
        revoke = text(
            "UPDATE hoimsystem_ai_roster_source SET status='revoked',revision=3,revoked_by=2,"
            "revoked_at='2026-10-20 12:02:00.654321',revoke_reason='synthetic explicit correction' "
            "WHERE source_record_id=:id AND status='published' AND revision=2"
        )
        assert connection.execute(revoke, {"id": values["id"]}).rowcount == 1
        assert connection.execute(revoke, {"id": values["id"]}).rowcount == 0
        row = connection.execute(text("SELECT payload_json,content_hash,recorded_at,reviewed_at,revoked_at FROM " + TABLE)).one()
        assert row == (values["payload"], "a" * 64, values["recorded"], "2026-10-20 12:01:00.123456", "2026-10-20 12:02:00.654321")
