"""Additive two-table migration, exact clocks, relational constraints and old rows."""

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

from app import models  # noqa: F401
from app.ai.document_change_models import DOCUMENT_CHANGE_MODELS

PATH = Path(__file__).resolve().parents[1] / "alembic/versions/20261021_document_change.py"
SPEC = importlib.util.spec_from_file_location("document_change_migration", PATH)
migration = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(migration)
NAMES = {table.__table__.name for table in DOCUMENT_CHANGE_MODELS}


def apply(connection, name):
    with Operations.context(MigrationContext.configure(connection)):
        getattr(migration, name)()


def snapshot(connection):
    rows = connection.exec_driver_sql("SELECT name,sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name").all()
    return {name: {"ddl": ddl, "rows": [tuple(row) for row in connection.exec_driver_sql('SELECT * FROM "' + name + '" ORDER BY rowid').all()]} for name, ddl in rows if name not in NAMES}


@pytest.fixture
def database():
    engine = sa.create_engine("sqlite:///:memory:")
    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        metadata = sa.MetaData()
        sa.Table("hoimsystem_users", metadata, sa.Column("user_id", sa.Integer, primary_key=True))
        sa.Table("hoimsystem_ai_audit_event", metadata, sa.Column("event_id", sa.Integer, primary_key=True))
        original = sa.Table(
            "hoimsystem_ai_document_original",
            metadata,
            sa.Column("original_id", sa.String(36), primary_key=True),
            sa.Column("content_hash", sa.String(64), nullable=False),
            sa.UniqueConstraint("original_id", "content_hash"),
        )
        legacy = sa.Table("synthetic_legacy", metadata, sa.Column("legacy_id", sa.Integer, primary_key=True), sa.Column("raw_text", sa.Text), sa.Column("unknown", sa.Integer))
        metadata.create_all(connection)
        connection.exec_driver_sql("INSERT INTO hoimsystem_users VALUES (1)")
        connection.exec_driver_sql("INSERT INTO hoimsystem_ai_audit_event VALUES (1)")
        connection.execute(original.insert(), [{"original_id": str(index), "content_hash": str(index) * 64} for index in (1, 2)])
        connection.execute(legacy.insert(), {"legacy_id": 1, "raw_text": "\ufeff原字\r\n😀e\u0301", "unknown": None})
        connection.commit()
        yield connection
    engine.dispose()


def link_values():
    return {
        "link_id": "link",
        "original_id": "1",
        "original_content_hash": "1" * 64,
        "original_governance_hash": "a" * 64,
        "target_kind": "clinical_pathway",
        "risk_rule_profile_id": None,
        "clinical_pathway_id": 1,
        "target_snapshot_hash": "b" * 64,
        "span_start": 0,
        "span_end": 1,
        "link_json": '{"migration_storage_only":"' + "😀" * 20000 + '"}',
        "content_hash": "c" * 64,
        "created_by": 1,
        "recorded_at": __import__("datetime").datetime(2026, 10, 21, 12, 0, 0, 123456),
        "status": "draft",
        "revision": 1,
        "privacy_review": "unknown",
        "faithfulness_review": "unknown",
        "dependency_review": "unknown",
        "reviewed_by": None,
        "reviewed_at": None,
        "review_basis_note": "",
        "revoked_by": None,
        "revoked_at": None,
        "revoke_reason": "",
        "created_audit_event_id": 1,
        "review_audit_event_id": None,
        "revoke_audit_event_id": None,
    }


def test_single_additive_successor_head_and_old_anchor_remains_an_ancestor():
    assert migration.revision == "20261021_document_change" and len(migration.revision) <= 32
    assert migration.down_revision == "20261021_doc_extraction_runs"
    config = Config(str(PATH.parents[2] / "alembic.ini"))
    config.set_main_option("script_location", str(PATH.parent.parent))
    script = ScriptDirectory.from_config(config)
    assert script.get_heads() == [migration.revision]


def test_actual_up_down_up_preserves_old_ddl_rows_and_mediumtext_unicode(database):
    before = snapshot(database)
    apply(database, "upgrade")
    assert snapshot(database) == before
    metadata = sa.MetaData()
    metadata.reflect(database)
    row = link_values()
    table = metadata.tables["hoimsystem_ai_document_rule_link"]
    database.execute(table.insert(), row)
    stored = database.execute(table.select()).mappings().one()
    assert stored["link_json"] == row["link_json"] and len(stored["link_json"].encode()) > 65535
    assert stored["recorded_at"].microsecond == 123456
    apply(database, "downgrade")
    assert snapshot(database) == before and not NAMES & set(sa.inspect(database).get_table_names())
    apply(database, "upgrade")
    assert snapshot(database) == before and NAMES <= set(sa.inspect(database).get_table_names())


@pytest.mark.parametrize(
    "changes",
    [
        {"original_content_hash": "f" * 64},
        {"created_audit_event_id": 9},
        {"clinical_pathway_id": 0},
        {"risk_rule_profile_id": "unexpected second target"},
        {"dependency_review": "confirmed"},
        {"status": "published", "revision": 2},
        {"span_start": 1, "span_end": 1},
    ],
)
def test_actual_relational_or_review_contradictions_are_rejected(database, changes):
    apply(database, "upgrade")
    metadata = sa.MetaData()
    metadata.reflect(database)
    with pytest.raises(sa.exc.IntegrityError), database.begin_nested():
        database.execute(metadata.tables["hoimsystem_ai_document_rule_link"].insert(), {**link_values(), **changes})


def test_models_and_migration_columns_and_foreign_keys_match(database):
    apply(database, "upgrade")
    inspector = sa.inspect(database)
    for model in DOCUMENT_CHANGE_MODELS:
        table = model.__table__
        assert {column["name"]: (column["nullable"], bool(column["primary_key"])) for column in inspector.get_columns(table.name)} == {
            column.name: (column.nullable, column.primary_key) for column in table.columns
        }
        actual = {tuple(value["constrained_columns"]) for value in inspector.get_foreign_keys(table.name)}
        expected = {tuple(element.parent.name for element in value.elements) for value in table.foreign_key_constraints}
        assert actual == expected
    ddl = "\n".join(str(CreateTable(model.__table__).compile(dialect=mysql.dialect())) for model in DOCUMENT_CHANGE_MODELS)
    assert ddl.count("DATETIME(6)") == 6 and ddl.count("MEDIUMTEXT") == 2
    assert "hoimsystem_ai_audit_event" in ddl and "hoimsystem_ai_document_original" in ddl
