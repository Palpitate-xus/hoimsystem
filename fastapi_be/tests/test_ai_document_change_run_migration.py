"""Additive synthetic SQL migration/constraints; not real MySQL wait evidence."""

import datetime as dt
import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy.dialects import mysql
from sqlalchemy.schema import CreateTable

from app.ai.document_change_run_models import ANCHOR_HASH_FIELDS, DOCUMENT_CHANGE_RUN_MODELS, SOURCE_HASH_FIELDS

PATH = Path(__file__).resolve().parents[1] / "alembic/versions/20261021_document_change_runs.py"
SPEC = importlib.util.spec_from_file_location("document_change_run_migration", PATH)
migration = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(migration)
NAMES = {model.__table__.name for model in DOCUMENT_CHANGE_RUN_MODELS}
ARTIFACT, RESULT = [model.__table__.name for model in DOCUMENT_CHANGE_RUN_MODELS]
NOW = dt.datetime(2026, 10, 21, 8, 40, 0, 123456)


def apply(db, name):
    with Operations.context(MigrationContext.configure(db)):
        getattr(migration, name)()


def legacy(db):
    result = {}
    for name, ddl in db.exec_driver_sql("SELECT name,sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"):
        if name not in NAMES:
            result[name] = (ddl, [tuple(row) for row in db.exec_driver_sql('SELECT * FROM "' + name + '" ORDER BY rowid')])
    return result


@pytest.fixture
def database():
    engine = sa.create_engine("sqlite:///:memory:")
    with engine.connect() as db:
        db.exec_driver_sql("PRAGMA foreign_keys=ON")
        metadata = sa.MetaData()
        users = sa.Table("hoimsystem_users", metadata, sa.Column("user_id", sa.Integer, primary_key=True))
        audits = sa.Table("hoimsystem_ai_audit_event", metadata, sa.Column("event_id", sa.Integer, primary_key=True))
        original = sa.Table(
            "hoimsystem_ai_document_original",
            metadata,
            sa.Column("original_id", sa.String(36), primary_key=True),
            sa.Column("content_hash", sa.String(64), nullable=False),
            sa.UniqueConstraint("original_id", "content_hash"),
        )
        scope = sa.Table("hoimsystem_ai_document_change_scope", metadata, sa.Column("scope_id", sa.String(36), primary_key=True))
        runs = sa.Table(
            "hoimsystem_ai_run", metadata, sa.Column("run_id", sa.String(36), primary_key=True), sa.Column("input_json", sa.Text), sa.Column("known_zero", sa.Integer), sa.Column("unknown", sa.Integer)
        )
        metadata.create_all(db)
        db.execute(users.insert(), {"user_id": 1})
        db.execute(audits.insert(), [{"event_id": i} for i in range(1, 11)])
        db.execute(original.insert(), [{"original_id": str(i), "content_hash": str(i) * 64} for i in (1, 2)])
        db.execute(scope.insert(), {"scope_id": "scope"})
        db.execute(runs.insert(), [{"run_id": str(i), "input_json": "\ufeff原样\r\n😀e\u0301", "known_zero": 0, "unknown": None} for i in (1, 2)])
        db.commit()
        yield db
    engine.dispose()


def artifact(run_id="1", **overrides):
    raw = '{"migration_storage_only":"' + "😀" * 20000 + '"}'
    return {
        "run_id": run_id,
        "scope_id": "scope",
        "requested_by": 1,
        "schema_version": "document_change_run_artifact_v1",
        "recorded_at": NOW,
        "baseline_original_id": "1",
        "candidate_original_id": "2",
        **{name: "a" * 64 for name in (*SOURCE_HASH_FIELDS, *ANCHOR_HASH_FIELDS)},
        "baseline_original_content_hash": "1" * 64,
        "candidate_original_content_hash": "2" * 64,
        "member_count": 2,
        "source_bytes": len(raw.encode("utf-8")),
        "source_json": raw,
        "scope_governance_json": "{}",
        "scope_created_audit_event_id": 1,
        "scope_review_audit_event_id": 2,
        "created_audit_event_id": 3,
        "usage_event_id": None,
        **overrides,
    }


def result(**overrides):
    raw = '{"migration_storage_only":"' + "😀" * 20000 + '"}'
    return {
        "run_id": "1",
        "scope_id": "scope",
        "schema_version": "document_change_run_result_v1",
        "lease_token": "lease",
        "content_hash": "c" * 64,
        "result_bytes": len(raw.encode("utf-8")),
        "result_json": raw,
        "source_binding_hash": "d" * 64,
        "accepted_at": NOW,
        "accept_audit_event_id": 5,
        **overrides,
    }


def reflected(db, name):
    return sa.Table(name, sa.MetaData(), autoload_with=db)


def test_single_additive_head_and_old_source_revision_unchanged():
    assert migration.revision == "20261021_document_change_runs" and len(migration.revision) <= 32
    assert migration.down_revision == "20261021_document_change"
    script = ScriptDirectory.from_config(Config(str(PATH.parents[2] / "alembic.ini")))
    assert script.get_heads() == [migration.revision]
    assert migration.down_revision in {r.revision for r in script.walk_revisions()}


def test_up_down_up_preserves_every_old_ddl_row_and_complete_unicode(database):
    db = database
    prior = legacy(db)
    for _ in range(2):
        apply(db, "upgrade")
        assert legacy(db) == prior
        first, second = reflected(db, ARTIFACT), reflected(db, RESULT)
        a, r = artifact(), result()
        db.execute(first.insert(), a)
        db.execute(second.insert(), r)
        db.commit()
        row = db.execute(sa.select(first)).mappings().one()
        accepted = db.execute(sa.select(second)).mappings().one()
        assert row["source_json"] == a["source_json"] and row["recorded_at"] == NOW
        assert accepted["result_json"] == r["result_json"] and accepted["accepted_at"] == NOW
        assert len(a["source_json"].encode("utf-8")) > 65535
        assert legacy(db) == prior
        apply(db, "downgrade")
        assert legacy(db) == prior and not NAMES & set(sa.inspect(db).get_table_names())


@pytest.mark.parametrize(
    "field,value",
    [
        ("source_digest", "A" * 64),
        ("source_bytes", 0),
        ("member_count", 8193),
        ("requested_by", 0),
        ("usage_event_id", 0),
        ("scope_governance_json", ""),
        ("schema_version", "wrong"),
        ("baseline_original_content_hash", "f" * 64),
        ("created_audit_event_id", 999),
    ],
)
def test_actual_sql_constraints_reject_invalid_artifact(database, field, value):
    apply(database, "upgrade")
    with pytest.raises(sa.exc.IntegrityError), database.begin_nested():
        database.execute(reflected(database, ARTIFACT).insert(), artifact(**{field: value}))
    assert database.execute(sa.text('SELECT COUNT(*) FROM "' + ARTIFACT + '"')).scalar() == 0


def test_nullable_usage_is_not_fake_zero_and_concrete_pk_is_unique(database):
    apply(database, "upgrade")
    table = reflected(database, ARTIFACT)
    database.execute(table.insert(), [artifact("1"), artifact("2")])
    assert database.execute(sa.select(table.c.usage_event_id)).scalars().all() == [None, None]
    database.execute(table.update().where(table.c.run_id == "1").values(usage_event_id=6))
    with pytest.raises(sa.exc.IntegrityError), database.begin_nested():
        database.execute(table.update().where(table.c.run_id == "2").values(usage_event_id=6))
    assert database.execute(sa.select(table.c.usage_event_id).order_by(table.c.run_id)).scalars().all() == [6, None]


def test_model_and_migration_columns_checks_and_relational_identity_match(database):
    apply(database, "upgrade")
    inspector = sa.inspect(database)
    for model in DOCUMENT_CHANGE_RUN_MODELS:
        table = model.__table__
        actual = {v["name"]: v for v in inspector.get_columns(table.name)}
        assert set(actual) == set(table.columns.keys())
        assert {v["name"] for v in inspector.get_check_constraints(table.name)} == {v.name for v in table.constraints if isinstance(v, sa.CheckConstraint)}
        expected_fks = {(tuple(item.parent.name for item in fk.elements), tuple(item.target_fullname for item in fk.elements)) for fk in table.foreign_key_constraints}
        actual_fks = {(tuple(fk["constrained_columns"]), tuple(fk["referred_table"] + "." + name for name in fk["referred_columns"])) for fk in inspector.get_foreign_keys(table.name)}
        assert actual_fks == expected_fks
        ddl = str(CreateTable(table).compile(dialect=mysql.dialect()))
        assert "MEDIUMTEXT" in ddl and "DATETIME(6)" in ddl and "AUTO_INCREMENT" not in ddl
