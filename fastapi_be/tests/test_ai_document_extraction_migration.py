"""Real SQLite migration/constraints and MySQL DDL; no MySQL runtime claim."""

import hashlib
import importlib.util
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.dialects import mysql
from sqlalchemy.exc import IntegrityError
from sqlalchemy.schema import CheckConstraint, CreateTable

from app.ai import document_evidence_contract as c
from app.ai.document_evidence_models import AIDocumentOriginal
from app.ai.document_extraction_models import ANCHOR_HASH_FIELDS, ANCHOR_SCHEMA, AIDocumentExtractionRunAnchor
from app.ai.models import AIRun
from app.database import Base
from app.models import User
from tests.test_ai_document_evidence_contract import NOW, original

PATH = Path(__file__).parents[1] / "alembic/versions/20261021_document_extraction_runs.py"
SPEC = importlib.util.spec_from_file_location("isolated_document_extraction_migration", PATH)
migration = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(migration)
NAME = AIDocumentExtractionRunAnchor.__tablename__


def snapshot(connection):
    tables = sorted(name for name in inspect(connection).get_table_names() if name != NAME)
    return {
        name: (
            connection.scalar(text("SELECT sql FROM sqlite_master WHERE type='table' AND name=:name"), {"name": name}),
            [tuple(row) for row in connection.execute(text("SELECT * FROM " + name))],
        )
        for name in tables
    }


def apply(connection, direction):
    with Operations.context(MigrationContext.configure(connection)):
        getattr(migration, direction)()


@pytest.fixture
def anchor_db():
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def foreign_keys(connection, record):
        connection.execute("PRAGMA foreign_keys=ON")

    with engine.begin() as connection:
        Base.metadata.create_all(connection, tables=[table for table in Base.metadata.sorted_tables if table.name != NAME])
        connection.execute(User.__table__.insert().values(user_id=1, username="doc_anchor_test", user_role="super_admin"))
        immutable = original()
        connection.execute(
            AIDocumentOriginal.__table__.insert().values(
                original_id=immutable.original_id,
                identity_json=c.canonical_json(immutable.model_dump(mode="json", exclude={"text"})),
                original_text=immutable.text,
                raw_bytes_hash=immutable.raw_bytes_hash,
                raw_bytes_length=immutable.raw_bytes_length,
                codepoint_length=immutable.codepoint_length,
                content_hash=c.digest(immutable),
                created_by=1,
                recorded_at=c.clock(NOW),
                status="draft",
                revision=1,
                privacy_review="unknown",
                faithfulness_review="unknown",
                review_basis_note="",
                revoke_reason="",
            )
        )
        input_json = c.canonical_json({"text": "\ufeff原文\r\n😀e\u0301", "original_id": immutable.original_id})
        evidence_json = c.canonical_json([{"source_id": "exact-source"}])
        metadata_json = c.canonical_json({"original": "原件"})
        run_id = "00000000-0000-0000-0000-000000000072"
        connection.execute(
            AIRun.__table__.insert().values(
                run_id=run_id,
                feature_key="guideline_ingestion",
                requested_by=1,
                prompt_hash="a" * 64,
                context_digest="b" * 64,
                status="queued",
                input_json=input_json,
                evidence_json=evidence_json,
                context_metadata_json=metadata_json,
                create_time=c.clock(NOW),
            )
        )
        values = {
            "run_id": run_id,
            "original_id": immutable.original_id,
            "requested_by": 1,
            "schema_version": ANCHOR_SCHEMA,
            "recorded_at": c.clock(NOW),
            "original_content_hash": c.digest(immutable),
            "original_governance_hash": "c" * 64,
            "source_digest": "d" * 64,
            "prompt_hash": "a" * 64,
            "context_digest": "b" * 64,
            "input_hash": hashlib.sha256(input_json.encode()).hexdigest(),
            "evidence_hash": hashlib.sha256(evidence_json.encode()).hexdigest(),
            "metadata_hash": hashlib.sha256(metadata_json.encode()).hexdigest(),
        }
        yield connection, values
    engine.dispose()


def test_single_revision_fits_existing_version_column_and_follows_document_source():
    assert migration.revision == "20261021_doc_extraction_runs" and len(migration.revision) <= 32
    assert migration.down_revision == "20261021_document_evidence"
    config = Config(str(PATH.parents[2] / "alembic.ini"))
    config.set_main_option("script_location", str(PATH.parent.parent))
    script = ScriptDirectory.from_config(config)
    heads = script.get_heads()
    assert len(heads) == 1
    assert migration.revision in {value.revision for value in script.walk_revisions(base="base", head=heads[0])}


def test_actual_up_down_up_preserves_every_old_table_ddl_and_complete_seed_rows(anchor_db):
    connection, values = anchor_db
    before = snapshot(connection)
    apply(connection, "upgrade")
    assert snapshot(connection) == before
    connection.execute(AIDocumentExtractionRunAnchor.__table__.insert().values(**values))
    stored = connection.execute(AIDocumentExtractionRunAnchor.__table__.select()).mappings().one()
    assert dict(stored) == values and stored["recorded_at"].microsecond == 123456
    apply(connection, "downgrade")
    assert NAME not in inspect(connection).get_table_names() and snapshot(connection) == before
    apply(connection, "upgrade")
    assert snapshot(connection) == before and connection.execute(AIDocumentExtractionRunAnchor.__table__.select()).first() is None


def test_actual_columns_constraints_three_foreign_keys_and_indexes_match_model(anchor_db):
    connection, _ = anchor_db
    apply(connection, "upgrade")
    inspector = inspect(connection)
    table = AIDocumentExtractionRunAnchor.__table__
    assert {column["name"]: column["nullable"] for column in inspector.get_columns(NAME)} == {column.name: column.nullable for column in table.columns}
    assert {row["name"] for row in inspector.get_check_constraints(NAME)} == {row.name for row in table.constraints if isinstance(row, CheckConstraint)}
    assert {(tuple(row["constrained_columns"]), row["referred_table"], tuple(row["referred_columns"])) for row in inspector.get_foreign_keys(NAME)} == {
        (tuple(element.parent.name for element in fk.elements), fk.elements[0].column.table.name, tuple(element.column.name for element in fk.elements)) for fk in table.foreign_key_constraints
    }
    assert {row["name"] for row in inspector.get_indexes(NAME)} == {row.name for row in table.indexes}
    assert inspector.get_pk_constraint(NAME)["constrained_columns"] == ["run_id"]


@pytest.mark.parametrize("field", ANCHOR_HASH_FIELDS)
@pytest.mark.parametrize("invalid", ["g" * 64, "A" * 64, " " * 64, "a" * 63, "a" * 65])
def test_all_eight_hashes_reject_nonhex_uppercase_or_wrong_length(anchor_db, field, invalid):
    connection, values = anchor_db
    apply(connection, "upgrade")
    with pytest.raises(IntegrityError), connection.begin_nested():
        connection.execute(AIDocumentExtractionRunAnchor.__table__.insert().values(**{**values, field: invalid}))
    assert connection.execute(AIDocumentExtractionRunAnchor.__table__.select()).first() is None


@pytest.mark.parametrize("field", ["run_id", "original_id", "requested_by"])
def test_actual_foreign_keys_reject_missing_parent(anchor_db, field):
    connection, values = anchor_db
    apply(connection, "upgrade")
    missing = 99999 if field == "requested_by" else "00000000-0000-0000-0000-000000009999"
    with pytest.raises(IntegrityError), connection.begin_nested():
        connection.execute(AIDocumentExtractionRunAnchor.__table__.insert().values(**{**values, field: missing}))


@pytest.mark.parametrize("changes", [{"requested_by": 0}, {"schema_version": "generic"}, {"input_hash": None}])
def test_schema_positive_actor_and_required_whole_json_hashes_are_closed(anchor_db, changes):
    connection, values = anchor_db
    apply(connection, "upgrade")
    with pytest.raises(IntegrityError), connection.begin_nested():
        connection.execute(AIDocumentExtractionRunAnchor.__table__.insert().values(**{**values, **changes}))


def test_one_immutable_anchor_per_run_and_parent_deletion_is_restricted(anchor_db):
    connection, values = anchor_db
    apply(connection, "upgrade")
    connection.execute(AIDocumentExtractionRunAnchor.__table__.insert().values(**values))
    with pytest.raises(IntegrityError), connection.begin_nested():
        connection.execute(AIDocumentExtractionRunAnchor.__table__.insert().values(**values))
    for table, key, value in [(AIRun.__table__, "run_id", values["run_id"]), (AIDocumentOriginal.__table__, "original_id", values["original_id"])]:
        with pytest.raises(IntegrityError), connection.begin_nested():
            connection.execute(table.delete().where(table.c[key] == value))


def test_mysql_ddl_one_utc6_eight_hashes_no_blob_and_old_run_text_unchanged():
    compiled = str(CreateTable(AIDocumentExtractionRunAnchor.__table__).compile(dialect=mysql.dialect()))
    assert compiled.count("DATETIME(6)") == 1 and compiled.count("VARCHAR(64)") == 8
    assert "MEDIUMTEXT" not in compiled and "ON DELETE CASCADE" not in compiled
    assert "MEDIUMTEXT" not in str(CreateTable(AIRun.__table__).compile(dialect=mysql.dialect()))
    assert ANCHOR_HASH_FIELDS == migration.HASH_FIELDS and len(ANCHOR_HASH_FIELDS) == 8
