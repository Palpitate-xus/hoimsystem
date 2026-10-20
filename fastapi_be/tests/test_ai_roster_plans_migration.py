"""Actual additive roster-plan migration, original preservation and SQL constraints."""

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
from app.ai.roster_plan_models import AIRosterPlan, AIRosterRunResult
from app.db_migrate import migrate
from tests.test_inpatient_support_migration import normalize_sql, snapshot

MODELS = (AIRosterPlan, AIRosterRunResult)
TABLES = {model.__tablename__ for model in MODELS}
REVISION = "20261020_roster_plans"
PARENT = "20261020_roster_sources"


def revision_module():
    path = Path(__file__).resolve().parents[1] / "alembic" / "versions" / (REVISION + ".py")
    spec = importlib.util.spec_from_file_location("isolated_roster_plans_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def offline(operation):
    output = StringIO()
    with Operations.context(MigrationContext.configure(dialect=mysql.dialect(), opts={"as_sql": True, "output_buffer": output})):
        getattr(revision_module(), operation)()
    return output.getvalue()


def test_actual_migration_up_down_up_keeps_all_previous_tables_rows_and_schedules(tmp_path):
    url = "sqlite:///" + str(tmp_path / "roster-plans.sqlite")
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", url)
    assert migrate(url) == "bootstrapped"
    command.downgrade(config, PARENT)
    engine = create_engine(url)
    originals = set(inspect(engine).get_table_names())
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO hoimsystem_department(department_id,name) VALUES(90201,'合成旧排班')"))
        connection.execute(text("INSERT INTO hoimsystem_doctor(doctor_id,name,department_id) VALUES(90202,'合成人员',90201)"))
        connection.execute(text("INSERT INTO hoimsystem_doctor_schedule(schedule_id,doctor_id,week,time,number,specialist) VALUES(90203,90202,'未知','?',0,NULL)"))
        preserved = snapshot(connection, originals - {"alembic_version"})
    for action in ("up", "down", "up"):
        if action == "up":
            command.upgrade(config, REVISION)
            inspector = inspect(engine)
            assert set(inspector.get_table_names()) == originals | TABLES
            for model in MODELS:
                table = model.__tablename__
                assert [(col["name"], col["nullable"]) for col in inspector.get_columns(table)] == [(col.name, col.nullable) for col in model.__table__.columns]
                assert {item["name"] for item in inspector.get_check_constraints(table)} == {item.name for item in model.__table__.constraints if isinstance(item, CheckConstraint)}
                assert {(item["name"], tuple(item["column_names"]), bool(item["unique"])) for item in inspector.get_indexes(table)} == {
                    (item.name, tuple(item.columns.keys()), item.unique) for item in model.__table__.indexes
                }
                assert {(item["constrained_columns"][0], item["referred_table"], item["referred_columns"][0]) for item in inspector.get_foreign_keys(table)} == {
                    (fk.parent.name, fk.column.table.name, fk.column.name) for fk in model.__table__.foreign_keys
                }
        else:
            command.downgrade(config, PARENT)
            assert set(inspect(engine).get_table_names()) == originals
        with engine.connect() as connection:
            assert snapshot(connection, originals - {"alembic_version"}) == preserved
    engine.dispose()


def test_mysql_static_ddl_matches_complete_models_without_touching_previous_tables():
    module = revision_module()
    assert module.revision == REVISION and module.down_revision == PARENT
    assert module.branch_labels is module.depends_on is None
    sql = offline("upgrade")
    assert sql.count("CREATE TABLE ") == 2 and sql.count("DATETIME(6)") == 5 and sql.count("MEDIUMTEXT") == 3
    assert all(word not in sql for word in ("ALTER TABLE", "UPDATE ", "DELETE FROM", "INSERT INTO"))
    for model in MODELS:
        assert normalize_sql(str(CreateTable(model.__table__).compile(dialect=mysql.dialect()))) in normalize_sql(sql)
        for index in model.__table__.indexes:
            assert normalize_sql(str(CreateIndex(index).compile(dialect=mysql.dialect()))) in normalize_sql(sql)
    assert [part.strip() for part in offline("downgrade").split(";") if part.strip()] == ["DROP TABLE " + model.__tablename__ for model in reversed(MODELS)]


@pytest.fixture
def plan_table():
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        with Operations.context(MigrationContext.configure(connection)):
            revision_module().upgrade()
    yield engine
    engine.dispose()


def insert_plan(connection, **changes):
    values = {
        "id": "synthetic-plan",
        "asof": "2026-10-20 12:00:00.123456",
        "created": "2026-10-20 12:00:00.654321",
        "snapshot": '{"basis":"' + "合成场景排班能力非实时库存" * 3000 + '"}',
        "status": "draft",
        "revision": 1,
        "reviewer": None,
        "reviewed": None,
        "review_basis": "",
        "revoker": None,
        "revoked": None,
        "reason": "",
        "projection": None,
        "projection_hash": None,
        **changes,
    }
    connection.execute(
        text(
            "INSERT INTO hoimsystem_ai_roster_plan(plan_id,department_id,schema_version,as_of,created_at,created_by,snapshot_json,content_hash,collection_digest,"
            "projection_json,projection_hash,status,revision,reviewed_by,reviewed_at,review_basis_note,revoked_by,revoked_at,revoke_reason) "
            "VALUES(:id,1,'roster_plan_private_v1',:asof,:created,1,:snapshot,:hash,:hash,:projection,:projection_hash,:status,:revision,:reviewer,:reviewed,:review_basis,:revoker,:revoked,:reason)"
        ),
        {**values, "hash": "a" * 64},
    )
    return values


@pytest.mark.parametrize(
    "changes",
    [
        {"status": "running"},
        {"status": "published", "revision": 2},
        {"projection": "{}", "projection_hash": "a" * 64},
        {"asof": "2026-10-20 12:00:00.654322"},
        {"reviewer": 2},
        {"status": "rejected", "revision": 2, "reviewer": 2, "reviewed": "2026-10-20 11:59:00.000000", "review_basis": "synthetic reason"},
        {"status": "revoked", "revision": 2},
        {"snapshot": ""},
    ],
)
def test_sql_rejects_false_publication_partial_clocks_and_unbound_projections(plan_table, changes):
    with plan_table.begin() as connection, pytest.raises(IntegrityError):
        insert_plan(connection, **changes)


def test_actual_sql_publish_cas_and_revoke_preserve_large_original_and_projection(plan_table):
    with plan_table.begin() as connection:
        values = insert_plan(connection)
        assert len(values["snapshot"].encode()) > 65535
        projection = '{"declared_capacity":0,"unknown":null,"basis":"' + "合成原始依据" * 3000 + '"}'
        publish = text(
            "UPDATE hoimsystem_ai_roster_plan SET status='published',revision=2,reviewed_by=2,reviewed_at='2026-10-20 12:01:00.123456',"
            "review_basis_note='synthetic explicit review',projection_json=:projection,projection_hash=:hash WHERE plan_id=:id AND status='draft' AND revision=1"
        )
        assert connection.execute(publish, {"projection": projection, "hash": "b" * 64, "id": values["id"]}).rowcount == 1
        assert connection.execute(publish, {"projection": "{}", "hash": "c" * 64, "id": values["id"]}).rowcount == 0
        revoke = text(
            "UPDATE hoimsystem_ai_roster_plan SET status='revoked',revision=3,revoked_by=2,revoked_at='2026-10-20 12:02:00.654321',"
            "revoke_reason='synthetic correction' WHERE plan_id=:id AND status='published' AND revision=2"
        )
        assert connection.execute(revoke, {"id": values["id"]}).rowcount == 1
        row = connection.execute(text("SELECT snapshot_json,projection_json,projection_hash,as_of,created_at,reviewed_at,revoked_at FROM hoimsystem_ai_roster_plan")).one()
        assert row == (values["snapshot"], projection, "b" * 64, values["asof"], values["created"], "2026-10-20 12:01:00.123456", "2026-10-20 12:02:00.654321")


@pytest.mark.parametrize("size,body", [(0, "{}"), (8388609, "{}"), (2, "")])
def test_sql_rejects_unbounded_or_empty_result_blobs(plan_table, size, body):
    with plan_table.begin() as connection, pytest.raises(IntegrityError):
        connection.execute(
            text(
                "INSERT INTO hoimsystem_ai_roster_run_result(run_id,plan_id,lease_token,schema_version,source_binding_hash,content_hash,result_json,result_bytes,created_at) "
                "VALUES('synthetic-run','synthetic-plan','synthetic-lease','roster_complete_result_v1',:hash,:hash,:body,:size,'2026-10-20 12:00:00.123456')"
            ),
            {"hash": "a" * 64, "body": body, "size": size},
        )
