"""Actual additive bed-source/series migrations and SQL lifecycle invariants."""

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
from app.ai.bed_models import AIBedSource
from app.ai.bed_series_models import AIBedRunResult, AIBedSeries
from app.db_migrate import migrate
from tests.test_inpatient_support_migration import normalize_sql, snapshot

MODELS = (AIBedSource, AIBedSeries, AIBedRunResult)
PARENT = "20261020_roster_plans"
REVISIONS = ("20261020_bed_sources", "20261020_bed_series")
TABLES = {model.__tablename__ for model in MODELS}


def revision_module(revision):
    path = Path(__file__).resolve().parents[1] / "alembic/versions" / (revision + ".py")
    spec = importlib.util.spec_from_file_location("isolated_" + revision, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def offline(revision, action):
    output = StringIO()
    with Operations.context(MigrationContext.configure(dialect=mysql.dialect(), opts={"as_sql": True, "output_buffer": output})):
        getattr(revision_module(revision), action)()
    return output.getvalue()


def test_both_actual_migrations_roundtrip_keep_all_previous_rows_and_occupancy(tmp_path):
    url = "sqlite:///" + str(tmp_path / "bed-originals.sqlite")
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", url)
    assert migrate(url) == "bootstrapped"
    command.downgrade(config, PARENT)
    engine = create_engine(url)
    originals = set(inspect(engine).get_table_names())
    assert not originals & TABLES
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO hoimsystem_department(department_id,name) VALUES(90301,'合成旧病区科室')"))
        connection.execute(text("INSERT INTO hoimsystem_ward(ward_id,name,department_id,bed_count,status) VALUES(90302,'合成旧病区',90301,17,0)"))
        connection.execute(text("INSERT INTO hoimsystem_bed(bed_id,ward_id,bed_no,status) VALUES(90303,90302,'合成',2)"))
        connection.execute(
            text(
                "INSERT INTO hoimsystem_admission(admission_id,department_id,ward_id,bed_id,admission_time,discharge_time,status) VALUES('synthetic-old-admission',90301,90302,90303,'2020-01-01 01:02:03',NULL,1)"
            )
        )
        preserved = snapshot(connection, originals - {"alembic_version"})
    for action in ("up", "down", "up"):
        if action == "up":
            command.upgrade(config, REVISIONS[-1])
            inspector = inspect(engine)
            assert set(inspector.get_table_names()) == originals | TABLES
            for model in MODELS:
                name = model.__tablename__
                assert [(item["name"], item["nullable"]) for item in inspector.get_columns(name)] == [(col.name, col.nullable) for col in model.__table__.columns]
                assert {item["name"] for item in inspector.get_check_constraints(name)} == {item.name for item in model.__table__.constraints if isinstance(item, CheckConstraint)}
                assert {(item["name"], tuple(item["column_names"])) for item in inspector.get_indexes(name)} == {(item.name, tuple(item.columns.keys())) for item in model.__table__.indexes}
                assert {(item["constrained_columns"][0], item["referred_table"], item["referred_columns"][0]) for item in inspector.get_foreign_keys(name)} == {
                    (fk.parent.name, fk.column.table.name, fk.column.name) for fk in model.__table__.foreign_keys
                }
        else:
            command.downgrade(config, PARENT)
            assert set(inspect(engine).get_table_names()) == originals
        with engine.connect() as connection:
            assert snapshot(connection, originals - {"alembic_version"}) == preserved
    engine.dispose()


def test_mysql_ddl_is_two_linked_additive_migrations_with_eight_utc6_and_five_mediumtext():
    first, second = map(revision_module, REVISIONS)
    assert (first.revision, second.revision) == REVISIONS
    assert first.down_revision == PARENT and second.down_revision == first.revision
    assert all(module.branch_labels is module.depends_on is None for module in (first, second))
    sql = "\n".join(offline(revision, "upgrade") for revision in REVISIONS)
    assert sql.count("CREATE TABLE ") == 3 and sql.count("DATETIME(6)") == 8 and sql.count("MEDIUMTEXT") == 5
    assert not any(word in sql for word in ("ALTER TABLE", "UPDATE ", "DELETE FROM", "INSERT INTO"))
    for model in MODELS:
        assert normalize_sql(str(CreateTable(model.__table__).compile(dialect=mysql.dialect()))) in normalize_sql(sql)
        for index in model.__table__.indexes:
            assert normalize_sql(str(CreateIndex(index).compile(dialect=mysql.dialect()))) in normalize_sql(sql)
    down = "\n".join(offline(revision, "downgrade") for revision in reversed(REVISIONS))
    assert [part.strip() for part in down.split(";") if part.strip()] == ["DROP TABLE " + model.__tablename__ for model in reversed(MODELS)]


@pytest.fixture
def tables():
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection, Operations.context(MigrationContext.configure(connection)):
        for revision in REVISIONS:
            revision_module(revision).upgrade()
    yield engine
    engine.dispose()


def insert_source(connection, **changes):
    values = {
        "source_record_id": "synthetic-bed-source",
        "source_kind": "census",
        "department_id": 1,
        "ward_id": 2,
        "schema_version": "bed_source_private_v1",
        "payload_json": '{"original":"' + "合成实测原件非医院历史" * 3000 + '"}',
        "parent_binding_json": "{}",
        "content_hash": "a" * 64,
        "recorded_at": "2026-10-20 12:00:00.123456",
        "created_by": 1,
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
    connection.execute(text("INSERT INTO hoimsystem_ai_bed_source(" + ",".join(values) + ") VALUES(" + ",".join(":" + key for key in values) + ")"), values)
    return values


@pytest.mark.parametrize(
    "changes",
    [
        {"source_kind": "invented"},
        {"ward_id": None},
        {"payload_json": ""},
        {"parent_binding_json": ""},
        {"status": "draft", "revision": 2},
        {"status": "published", "revision": 2},
        {"status": "revoked", "revision": 2},
        {"status": "published", "revision": 2, "reviewed_by": 2, "reviewed_at": "2026-10-20 11:59:59.123456", "review_basis_note": "合成审核"},
        {"payload_json": "x" * 262145},
        {"parent_binding_json": "x" * 32769},
    ],
)
def test_source_sql_rejects_false_governance_bad_clocks_and_storage_overflow(tables, changes):
    with tables.begin() as connection, pytest.raises(IntegrityError):
        insert_source(connection, **changes)


def test_source_full_unicode_microseconds_and_cas_survive_review_and_revoke(tables):
    with tables.begin() as connection:
        values = insert_source(connection)
        assert len(values["payload_json"].encode()) > 65535
        sql = text(
            "UPDATE hoimsystem_ai_bed_source SET status='published',revision=2,reviewed_by=2,reviewed_at='2026-10-20 12:01:00.654321',review_basis_note='合成独立核对' WHERE source_record_id=:id AND status='draft' AND revision=1"
        )
        assert connection.execute(sql, {"id": values["source_record_id"]}).rowcount == 1
        assert connection.execute(sql, {"id": values["source_record_id"]}).rowcount == 0
        sql = text(
            "UPDATE hoimsystem_ai_bed_source SET status='revoked',revision=3,revoked_by=2,revoked_at='2026-10-20 12:02:00.123456',revoke_reason='合成原件更正' WHERE source_record_id=:id AND status='published' AND revision=2"
        )
        assert connection.execute(sql, {"id": values["source_record_id"]}).rowcount == 1
        assert connection.execute(sql, {"id": values["source_record_id"]}).rowcount == 0
        row = connection.execute(text("SELECT payload_json,content_hash,recorded_at,reviewed_at,revoked_at FROM hoimsystem_ai_bed_source")).one()
        assert row == (values["payload_json"], "a" * 64, values["recorded_at"], "2026-10-20 12:01:00.654321", "2026-10-20 12:02:00.123456")


def insert_series(connection, **changes):
    values = {
        "series_id": "synthetic-bed-series",
        "department_id": 1,
        "ward_id": 2,
        "schema_version": "bed_series_private_v1",
        "as_of": "2026-10-20 12:00:00.123456",
        "created_at": "2026-10-20 12:00:00.654321",
        "created_by": 1,
        "snapshot_json": '{"original":"' + "合成完整日序列非真实记录" * 3000 + '"}',
        "content_hash": "b" * 64,
        "collection_digest": "c" * 64,
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
    connection.execute(text("INSERT INTO hoimsystem_ai_bed_series(" + ",".join(values) + ") VALUES(" + ",".join(":" + key for key in values) + ")"), values)
    return values


@pytest.mark.parametrize(
    "changes",
    [
        {"ward_id": None},
        {"as_of": "2026-10-20 12:00:00.654322"},
        {"snapshot_json": ""},
        {"snapshot_json": "x" * 8388609},
        {"projection_json": "{}", "projection_hash": "d" * 64},
        {"status": "published", "revision": 2, "reviewed_by": 2, "reviewed_at": "2026-10-20 12:01:00.123456", "review_basis_note": "合成审核"},
    ],
)
def test_series_sql_requires_complete_governance_projection_and_bounded_original(tables, changes):
    with tables.begin() as connection, pytest.raises(IntegrityError):
        insert_series(connection, **changes)


def test_series_publication_and_large_lease_bound_result_preserve_full_original(tables):
    with tables.begin() as connection:
        values = insert_series(connection)
        projection = '{"public":"' + "合成公开原量" * 5000 + '"}'
        connection.execute(
            text(
                "UPDATE hoimsystem_ai_bed_series SET status='published',revision=2,reviewed_by=2,reviewed_at='2026-10-20 12:01:00.123456',review_basis_note='合成独立范围审核',projection_json=:p,projection_hash=:h WHERE series_id=:id"
            ),
            {"p": projection, "h": "d" * 64, "id": values["series_id"]},
        )
        body = '{"result":"' + "合成完整证明" * 6000 + '"}'
        assert min(len(value.encode()) for value in (values["snapshot_json"], projection, body)) > 65535
        connection.execute(
            text(
                "INSERT INTO hoimsystem_ai_bed_run_result(run_id,series_id,lease_token,schema_version,source_binding_hash,content_hash,result_json,result_bytes,created_at) VALUES('synthetic-run',:series,'original-lease','bed_result_blob_v1',:binding,:hash,:body,:size,'2026-10-20 12:03:00.654321')"
            ),
            {"series": values["series_id"], "binding": "e" * 64, "hash": "f" * 64, "body": body, "size": len(body.encode())},
        )
        assert connection.execute(text("SELECT snapshot_json,projection_json FROM hoimsystem_ai_bed_series")).one() == (values["snapshot_json"], projection)
        assert connection.execute(text("SELECT lease_token,result_json,result_bytes,created_at FROM hoimsystem_ai_bed_run_result")).one() == (
            "original-lease",
            body,
            len(body.encode()),
            "2026-10-20 12:03:00.654321",
        )
