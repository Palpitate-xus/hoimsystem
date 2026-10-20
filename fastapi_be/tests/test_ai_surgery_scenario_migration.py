"""Actual additive SQLite migration and SQL scenario/result lifecycle invariants."""

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
from app.ai.surgery_scenario_models import AISurgeryRunResult, AISurgeryScenario
from app.db_migrate import migrate
from tests.test_ai_bed_migration import revision_module
from tests.test_inpatient_support_migration import normalize_sql, snapshot

REVISION = "20261020_surgery_scenarios"
PARENT = "20261020_surgery_sources"
MODELS = (AISurgeryScenario, AISurgeryRunResult)
TABLES = {model.__tablename__ for model in MODELS}


def test_actual_up_down_up_preserves_all_preceding_definitions_and_rows(tmp_path):
    url = "sqlite:///" + str(tmp_path / "surgery-scenarios.sqlite")
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", url)
    assert migrate(url) == "bootstrapped"
    command.downgrade(config, PARENT)
    engine = create_engine(url)
    previous = set(inspect(engine).get_table_names())
    assert not previous & TABLES
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO hoimsystem_department(department_id,name) VALUES(90661,'合成旧手术场景科')"))
        connection.execute(text("INSERT INTO hoimsystem_surgery_schedule(schedule_id,operating_room,surgery_date,status) VALUES('synthetic-scenario-old','旧房间保留','2020-01-02',3)"))
        preserved = snapshot(connection, previous - {"alembic_version"})
    for action in ("up", "down", "up"):
        if action == "up":
            command.upgrade(config, REVISION)
            inspector = inspect(engine)
            assert set(inspector.get_table_names()) == previous | TABLES
            for model in MODELS:
                name = model.__tablename__
                assert [(col["name"], col["nullable"]) for col in inspector.get_columns(name)] == [(col.name, col.nullable) for col in model.__table__.columns]
                assert {item["name"] for item in inspector.get_check_constraints(name)} == {item.name for item in model.__table__.constraints if isinstance(item, CheckConstraint)}
                assert {(item["name"], tuple(item["column_names"])) for item in inspector.get_indexes(name)} == {(item.name, tuple(item.columns.keys())) for item in model.__table__.indexes}
                assert {(item["constrained_columns"][0], item["referred_table"], item["referred_columns"][0]) for item in inspector.get_foreign_keys(name)} == {
                    (fk.parent.name, fk.column.table.name, fk.column.name) for fk in model.__table__.foreign_keys
                }
        else:
            command.downgrade(config, PARENT)
            assert set(inspect(engine).get_table_names()) == previous
        with engine.connect() as connection:
            assert snapshot(connection, previous - {"alembic_version"}) == preserved
    engine.dispose()


def test_mysql_compiled_migration_matches_two_models_five_utc6_and_three_mediumtext():
    module = revision_module(REVISION)
    assert module.revision == REVISION and module.down_revision == PARENT
    assert module.branch_labels is module.depends_on is None
    output = StringIO()
    with Operations.context(MigrationContext.configure(dialect=mysql.dialect(), opts={"as_sql": True, "output_buffer": output})):
        module.upgrade()
    sql = output.getvalue()
    assert sql.count("CREATE TABLE ") == 2 and sql.count("DATETIME(6)") == 5 and sql.count("MEDIUMTEXT") == 3
    assert not any(word in sql for word in ("ALTER TABLE", "UPDATE ", "DELETE FROM", "INSERT INTO"))
    for model in MODELS:
        # Check clauses separately because SQLAlchemy constraint set order varies.
        expected = str(CreateTable(model.__table__).compile(dialect=mysql.dialect()))
        for column in model.__table__.columns:
            assert normalize_sql(str(column.type.compile(dialect=mysql.dialect()))) in normalize_sql(sql)
        assert model.__tablename__ in expected
        for constraint in model.__table__.constraints:
            if isinstance(constraint, CheckConstraint):
                assert normalize_sql(str(constraint.sqltext)) in normalize_sql(sql)
        for index in model.__table__.indexes:
            assert normalize_sql(str(CreateIndex(index).compile(dialect=mysql.dialect()))) in normalize_sql(sql)
    output = StringIO()
    with Operations.context(MigrationContext.configure(dialect=mysql.dialect(), opts={"as_sql": True, "output_buffer": output})):
        module.downgrade()
    assert [item.strip() for item in output.getvalue().split(";") if item.strip()] == ["DROP TABLE " + model.__tablename__ for model in reversed(MODELS)]


@pytest.fixture
def sql():
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection, Operations.context(MigrationContext.configure(connection)):
        revision_module(REVISION).upgrade()
    yield engine
    engine.dispose()


def insert_scenario(connection, **changes):
    values = {
        "scenario_id": "synthetic-surgery-scenario",
        "department_id": 1,
        "pool_id": "synthetic-pool",
        "schema_version": "surgery_scenario_private_v1",
        "as_of": "2026-10-20 12:00:00.123456",
        "created_at": "2026-10-20 12:00:00.654321",
        "created_by": 1,
        "snapshot_json": '{"original":"' + "合成完整病例与阶段资源原件" * 3000 + '"}',
        "content_hash": "a" * 64,
        "collection_digest": "b" * 64,
        "projection_json": None,
        "projection_hash": None,
        "status": "draft",
        "revision": 1,
        "reviewed_by": None,
        "reviewed_at": None,
        "review_basis_note": "",
        "revoked_by": None,
        "revoked_at": None,
        "revoke_reason": "",
        **changes,
    }
    connection.execute(text("INSERT INTO hoimsystem_ai_surgery_scenario(" + ",".join(values) + ") VALUES(" + ",".join(":" + key for key in values) + ")"), values)
    return values


@pytest.mark.parametrize(
    "changes",
    [
        {"pool_id": None},
        {"as_of": "2026-10-20 12:00:00.654322"},
        {"snapshot_json": ""},
        {"snapshot_json": "x" * 8388609},
        {"projection_json": "{}", "projection_hash": "c" * 64},
        {"status": "published", "revision": 2, "reviewed_by": 2, "reviewed_at": "2026-10-20 12:01:00.123456", "review_basis_note": "合成审核"},
        {"status": "draft", "revision": 2},
        {"status": "revoked", "revision": 2},
    ],
)
def test_sql_rejects_missing_scope_incomplete_governance_clocks_and_overflow(sql, changes):
    with sql.begin() as connection, pytest.raises(IntegrityError):
        insert_scenario(connection, **changes)


def test_large_complete_original_and_lease_result_survive_publication_and_cas_revocation(sql):
    with sql.begin() as connection:
        original = insert_scenario(connection)
        projection = '{"public":"' + "合成脱敏场景原量" * 4000 + '"}'
        result = '{"result":"' + "合成完整搜索证明" * 6000 + '"}'
        assert all(len(item.encode()) > 65535 for item in (original["snapshot_json"], projection, result))
        publish = text(
            "UPDATE hoimsystem_ai_surgery_scenario SET status='published',revision=2,reviewed_by=2,reviewed_at='2026-10-20 12:01:00.123456',review_basis_note='合成独立核对',projection_json=:body,projection_hash=:hash "
            "WHERE scenario_id=:id AND status='draft' AND revision=1"
        )
        values = {"id": original["scenario_id"], "body": projection, "hash": "c" * 64}
        assert connection.execute(publish, values).rowcount == 1
        assert connection.execute(publish, values).rowcount == 0
        connection.execute(
            text(
                "INSERT INTO hoimsystem_ai_surgery_run_result(run_id,scenario_id,lease_token,schema_version,source_binding_hash,content_hash,result_json,result_bytes,created_at) "
                "VALUES('synthetic-run',:id,'original-lease','surgery_result_blob_v1',:binding,:hash,:body,:size,'2026-10-20 12:03:00.654321')"
            ),
            {"id": original["scenario_id"], "binding": "d" * 64, "hash": "e" * 64, "body": result, "size": len(result.encode())},
        )
        revoke = text(
            "UPDATE hoimsystem_ai_surgery_scenario SET status='revoked',revision=3,revoked_by=2,revoked_at='2026-10-20 12:02:00.123456',revoke_reason='合成原件更正' "
            "WHERE scenario_id=:id AND status='published' AND revision=2"
        )
        assert connection.execute(revoke, {"id": original["scenario_id"]}).rowcount == 1
        assert connection.execute(revoke, {"id": original["scenario_id"]}).rowcount == 0
        assert connection.execute(text("SELECT snapshot_json,projection_json,as_of,revoked_at FROM hoimsystem_ai_surgery_scenario")).one() == (
            original["snapshot_json"],
            projection,
            original["as_of"],
            "2026-10-20 12:02:00.123456",
        )
        assert connection.execute(text("SELECT lease_token,result_json,result_bytes,created_at FROM hoimsystem_ai_surgery_run_result")).one() == (
            "original-lease",
            result,
            len(result.encode()),
            "2026-10-20 12:03:00.654321",
        )
