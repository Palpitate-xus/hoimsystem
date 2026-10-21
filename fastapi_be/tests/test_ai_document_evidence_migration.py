"""Actual isolated SQLite upgrade/down/up and MySQL DDL shape, not MySQL waits."""

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
from sqlalchemy.schema import CheckConstraint, CreateTable, ForeignKeyConstraint, UniqueConstraint

from app.ai.document_evidence_models import DOCUMENT_EVIDENCE_MODELS
from app.ai.models import AIKnowledgeDocument
from app.database import Base
from app.models import User

PATH = Path(__file__).parents[1] / "alembic/versions/20261021_document_evidence.py"
spec = importlib.util.spec_from_file_location("isolated_document_evidence_migration", PATH)
migration = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migration)
NAMES = {model.__tablename__ for model in DOCUMENT_EVIDENCE_MODELS}


def ddl_snapshot(connection, exclude=()):
    rows = connection.execute(text("SELECT name,sql FROM sqlite_master WHERE type='table' ORDER BY name")).all()
    return {name: sql for name, sql in rows if name not in exclude}


@pytest.fixture
def migration_db():
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, record):
        connection.execute("PRAGMA foreign_keys=ON")

    with engine.begin() as connection:
        # Existing application tables are parents, not changed by this migration.
        Base.metadata.create_all(connection, tables=[t for t in Base.metadata.tables.values() if t.name not in NAMES])
        connection.execute(User.__table__.insert().values(user_id=1, username="synthetic71", user_role="super_admin"))
        before = ddl_snapshot(connection)
        yield connection, before
    engine.dispose()


def apply(connection, direction):
    with Operations.context(MigrationContext.configure(connection)):
        getattr(migration, direction)()


def test_revision_is_actual_single_chain_after_coding_foundation():
    assert migration.revision == "20261021_document_evidence" and migration.down_revision == "20261021_coding_evidence"
    config = Config(str(PATH.parents[2] / "alembic.ini"))
    config.set_main_option("script_location", str(PATH.parent.parent))
    script = ScriptDirectory.from_config(config)
    assert script.get_heads() == [migration.revision]
    assert script.get_revision(migration.down_revision) is not None
    chain = [revision.revision for revision in script.walk_revisions()]
    assert len(chain) == len(set(chain)) and migration.down_revision in chain


def test_actual_upgrade_down_upgrade_preserves_all_old_ddl_and_rows(migration_db):
    connection, before = migration_db
    apply(connection, "upgrade")
    assert set(inspect(connection).get_table_names()) - set(before) == NAMES
    assert ddl_snapshot(connection, NAMES) == before
    assert connection.execute(text("SELECT username,user_role FROM hoimsystem_users WHERE user_id=1")).one() == ("synthetic71", "super_admin")
    first = ddl_snapshot(connection)
    apply(connection, "downgrade")
    assert ddl_snapshot(connection) == before
    apply(connection, "upgrade")
    assert ddl_snapshot(connection) == first


@pytest.mark.parametrize("model", DOCUMENT_EVIDENCE_MODELS)
def test_actual_migration_columns_constraints_and_composite_keys_match_models(migration_db, model):
    connection, _ = migration_db
    apply(connection, "upgrade")
    inspector = inspect(connection)
    actual = {column["name"]: column for column in inspector.get_columns(model.__tablename__)}
    assert set(actual) == set(model.__table__.columns.keys())
    for column in model.__table__.columns:
        assert actual[column.name]["nullable"] == column.nullable
    assert {row["name"] for row in inspector.get_unique_constraints(model.__tablename__)} == {row.name for row in model.__table__.constraints if isinstance(row, UniqueConstraint)}
    assert {row["name"] for row in inspector.get_check_constraints(model.__tablename__)} == {row.name for row in model.__table__.constraints if isinstance(row, CheckConstraint)}
    actual_fks = {(tuple(row["constrained_columns"]), row["referred_table"], tuple(row["referred_columns"])) for row in inspector.get_foreign_keys(model.__tablename__)}
    expected_fks = {
        (tuple(f.parent.name for f in constraint.elements), constraint.elements[0].column.table.name, tuple(f.column.name for f in constraint.elements))
        for constraint in model.__table__.constraints
        if isinstance(constraint, ForeignKeyConstraint)
    }
    assert actual_fks == expected_fks


def test_mysql_ddl_has_three_mediumtext_eight_utc6_and_unchanged_knowledge_text():
    compiled = "\n".join(str(CreateTable(model.__table__).compile(dialect=mysql.dialect())) for model in DOCUMENT_EVIDENCE_MODELS)
    assert compiled.count("MEDIUMTEXT") == 3 and compiled.count("DATETIME(6)") == 8
    assert "ON DELETE CASCADE" not in compiled
    assert "MEDIUMTEXT" not in str(CreateTable(AIKnowledgeDocument.__table__).compile(dialect=mysql.dialect()))
    assert "FOREIGN KEY(candidate_id, original_id, candidate_content_hash)" in compiled


def test_actual_sqlite_composite_original_hash_fk_rejects_orphan(migration_db):
    connection, _ = migration_db
    apply(connection, "upgrade")
    sql = """INSERT INTO hoimsystem_ai_document_span_candidate
    (candidate_id,original_id,original_content_hash,original_governance_hash,span_start,span_end,candidate_json,content_hash,created_by,recorded_at,status,revision,privacy_review,faithfulness_review,reviewed_by,reviewed_at,review_basis_note,revoked_by,revoked_at,revoke_reason)
    VALUES ('00000000-0000-0000-0000-000000000071','00000000-0000-0000-0000-000000000070',:sha,:sha,0,1,'{}',:sha,1,'2026-10-21 12:00:00','draft',1,'unknown','unknown',NULL,NULL,'',NULL,NULL,'')"""
    with pytest.raises(IntegrityError):
        with connection.begin_nested():
            connection.execute(text(sql), {"sha": "a" * 64})
