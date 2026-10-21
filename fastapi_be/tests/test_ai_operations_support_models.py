"""Actual additive storage constraints; no service authorization or MySQL wait claim."""

import datetime as dt
import importlib.util
import io
import uuid
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.dialects import mysql
from sqlalchemy.exc import IntegrityError
from sqlalchemy.schema import CreateTable

from app.ai.models import AIAuditEvent
from app.ai.operations_support_models import OPERATIONS_SOURCE_MODELS, AIOperationsCase, AIOperationsOriginal, AIOperationsRelease

NOW = dt.datetime(2026, 10, 21, 17, 0, 0, 123456)
MIGRATION = Path(__file__).resolve().parents[1] / "alembic/versions/20261021_operations_support_sources.py"


@pytest.fixture(autouse=True)
def actual_foreign_keys(db_session, seed_data):
    db_session.commit()
    previous = db_session.execute(text("PRAGMA foreign_keys")).scalar_one()
    db_session.execute(text("PRAGMA foreign_keys=ON"))
    assert db_session.execute(text("PRAGMA foreign_keys")).scalar_one() == 1
    yield
    db_session.rollback()
    db_session.execute(text("PRAGMA foreign_keys=" + str(previous)))
    db_session.commit()


def audit(db, actor):
    event = AIAuditEvent(actor_id=actor, action="synthetic_ops_schema_only", target="synthetic:" + str(uuid.uuid4()), detail_json="{}", create_time=NOW)
    db.add(event)
    db.flush()
    return event.event_id


def original_row(db, actor, **values):
    body = "完整合成原件😀\ufeff\r\n\x00" * 5000
    fields = dict(
        original_id=str(uuid.uuid4()),
        identity_json='{"synthetic":"schema-only"}',
        content_text=body,
        content_hash="a" * 64,
        raw_text_sha256="b" * 64,
        raw_bytes_length=len(body.encode()),
        codepoint_length=len(body),
        captured_by=actor,
        captured_at=NOW,
        creation_event_id=audit(db, actor),
        status="active",
        revision=1,
        revoked_by=None,
        revoked_at=None,
        revoke_reason="",
        revocation_event_id=None,
    )
    fields.update(values)
    row = AIOperationsOriginal(**fields)
    db.add(row)
    db.flush()
    return row


def release_row(db, parent, actor, **values):
    fields = dict(
        release_id=str(uuid.uuid4()),
        original_id=parent.original_id,
        original_content_hash=parent.content_hash,
        original_captured_by=parent.captured_by,
        draft_json='{"synthetic":"draft-column-only"}',
        content_hash="c" * 64,
        created_by=actor,
        recorded_at=NOW,
        creation_event_id=audit(db, actor),
        status="draft",
        revision=1,
        review_decision=None,
        privacy_reviewed=None,
        faithfulness_reviewed=None,
        applicability_reviewed=None,
        model_processing_allowed=None,
        reviewed_by=None,
        reviewed_at=None,
        review_basis="",
        review_event_id=None,
        published_review_json=None,
        published_review_hash=None,
        revoked_by=None,
        revoked_at=None,
        revoke_reason="",
        revocation_event_id=None,
    )
    fields.update(values)
    row = AIOperationsRelease(**fields)
    db.add(row)
    db.flush()
    return row


def published_values(db, reviewer, **values):
    fields = dict(
        status="published",
        revision=2,
        review_decision="published",
        privacy_reviewed=1,
        faithfulness_reviewed=1,
        applicability_reviewed=1,
        model_processing_allowed=0,
        reviewed_by=reviewer,
        reviewed_at=NOW,
        review_basis="合成物理列约束，不代表实际权限审核",
        review_event_id=audit(db, reviewer),
        published_review_json='{"synthetic":"published-column-only"}',
        published_review_hash="d" * 64,
    )
    fields.update(values)
    return fields


def case_row(db, actor, **values):
    fields = dict(
        case_id=str(uuid.uuid4()),
        requested_by=actor,
        assembled_at=NOW,
        member_bindings_json='[{"synthetic":true}]',
        member_bindings_hash="e" * 64,
        private_json='{"synthetic":"private-column-only"}',
        private_hash="f" * 64,
        public_json='{"synthetic":"public-column-only"}',
        public_hash="a" * 64,
        source_count=1,
        creation_event_id=audit(db, actor),
        status="active",
        revision=1,
        revoked_by=None,
        revoked_at=None,
        revoke_reason="",
        revocation_event_id=None,
    )
    fields.update(values)
    row = AIOperationsCase(**fields)
    db.add(row)
    db.flush()
    return row


def test_actual_four_table_mysql_ddl_has_complete_capacity_and_microseconds():
    ddls = [str(CreateTable(m.__table__).compile(dialect=mysql.dialect())) for m in OPERATIONS_SOURCE_MODELS]
    assert sum(s.count("DATETIME(6)") for s in ddls) == 7
    assert sum(s.count("MEDIUMTEXT") for s in ddls) == 6
    assert "AUTO_INCREMENT" not in ddls[0]
    assert "CAST(content_text AS BINARY)" in ddls[1]
    assert all(len(c.name or "") <= 64 for m in OPERATIONS_SOURCE_MODELS for c in m.__table__.constraints)


def test_large_unicode_nul_raw_text_roundtrips_without_text65535_limit(db_session, seed_data):
    row = original_row(db_session, seed_data["super_admin_user"].user_id)
    expected = row.content_text
    identifier = row.original_id
    assert len(expected.encode()) > 65535
    db_session.commit()
    db_session.expire_all()
    actual = db_session.get(AIOperationsOriginal, identifier)
    assert actual.content_text == expected and actual.raw_bytes_length == len(expected.encode()) and actual.codepoint_length == len(expected)
    assert actual.captured_at == NOW


@pytest.mark.parametrize("field", ["privacy_reviewed", "faithfulness_reviewed", "applicability_reviewed", "model_processing_allowed", "review_decision", "published_review_json", "review_event_id"])
def test_nullable_sql_values_cannot_bypass_a_complete_published_review(db_session, seed_data, field):
    creator = seed_data["super_admin_user"].user_id
    reviewer = seed_data["admin_user"].user_id
    parent = original_row(db_session, creator)
    values = published_values(db_session, reviewer, **{field: None})
    with pytest.raises(IntegrityError):
        release_row(db_session, parent, creator, **values)


def test_internal_publication_does_not_invent_model_processing_permission(db_session, seed_data):
    creator = seed_data["super_admin_user"].user_id
    reviewer = seed_data["admin_user"].user_id
    parent = original_row(db_session, creator)
    row = release_row(db_session, parent, creator, **published_values(db_session, reviewer, review_basis="字" * 4000))
    db_session.commit()
    db_session.refresh(row)
    assert row.status == "published" and row.model_processing_allowed == 0
    assert row.review_basis == "字" * 4000


@pytest.mark.parametrize("mutation", ["self_review", "parent_actor_mismatch", "parent_hash_mismatch", "reused_receipt"])
def test_actual_independence_parent_composite_and_unique_audit_fks(db_session, seed_data, mutation):
    creator = seed_data["super_admin_user"].user_id
    reviewer = seed_data["admin_user"].user_id
    parent = original_row(db_session, creator)
    values = published_values(db_session, reviewer)
    if mutation == "self_review":
        values["reviewed_by"] = creator
    elif mutation == "parent_actor_mismatch":
        values["original_captured_by"] = reviewer
    elif mutation == "parent_hash_mismatch":
        values["original_content_hash"] = "z" * 64
    else:
        values["review_event_id"] = values["creation_event_id"] = audit(db_session, creator)
    with pytest.raises(IntegrityError):
        release_row(db_session, parent, creator, **values)


@pytest.mark.parametrize("field,maximum", [("private_json", 8388608), ("public_json", 8388608), ("member_bindings_json", 262144)])
def test_real_utf8_storage_at_exact_bound_and_one_byte_more(db_session, seed_data, field, maximum):
    body = "字" * (maximum // 3) + "x" * (maximum % 3)
    assert len(body.encode()) == maximum
    actor = seed_data["super_admin_user"].user_id
    row = case_row(db_session, actor, **{field: body})
    identifier = row.case_id
    db_session.commit()
    db_session.expire_all()
    assert getattr(db_session.get(AIOperationsCase, identifier), field) == body
    with pytest.raises(IntegrityError):
        case_row(db_session, actor, **{field: body + "x"})


def migration():
    spec = importlib.util.spec_from_file_location("synthetic_ops_migration", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_actual_sqlite_incremental_up_down_up_preserves_two_fk_prerequisite_tables():
    engine = create_engine("sqlite:///:memory:")
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")
            connection.exec_driver_sql("CREATE TABLE hoimsystem_users (user_id INTEGER PRIMARY KEY, note TEXT NOT NULL)")
            connection.exec_driver_sql("CREATE TABLE hoimsystem_ai_audit_event (event_id INTEGER PRIMARY KEY, note TEXT NOT NULL)")
            connection.exec_driver_sql("INSERT INTO hoimsystem_users VALUES(1,'synthetic old user')")
            connection.exec_driver_sql("INSERT INTO hoimsystem_ai_audit_event VALUES(1,'synthetic old audit')")

            def old():
                return {
                    n: (connection.exec_driver_sql("SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (n,)).scalar_one(), connection.exec_driver_sql("SELECT * FROM " + n).all())
                    for n in ["hoimsystem_users", "hoimsystem_ai_audit_event"]
                }

            before = old()
            module = migration()
            module.op = Operations(MigrationContext.configure(connection))
            for turn in range(2):
                module.upgrade()
                assert set(inspect(connection).get_table_names()) == set(before) | {m.__tablename__ for m in OPERATIONS_SOURCE_MODELS}
                assert connection.exec_driver_sql("SELECT gate_id,revision FROM hoimsystem_ai_operations_write_gate").all() == [(1, 1)]
                assert old() == before
                if turn == 0:
                    module.downgrade()
                    assert set(inspect(connection).get_table_names()) == set(before)
    finally:
        engine.dispose()


def test_self_contained_mysql_migration_is_additive_and_drops_tables_in_dependency_order():
    stream = io.StringIO()
    module = migration()
    module.op = Operations(MigrationContext.configure(dialect_name="mysql", opts={"as_sql": True, "output_buffer": stream}))
    module.upgrade()
    up = stream.getvalue()
    assert up.count("CREATE TABLE") == 4 and up.count("MEDIUMTEXT") == 6 and up.count("DATETIME(6)") == 7
    assert "ALTER TABLE" not in up
    stream.seek(0)
    stream.truncate()
    module.downgrade()
    down = stream.getvalue()
    assert "DROP INDEX" not in down
    assert down.index("operations_case") < down.index("operations_release") < down.index("operations_original") < down.index("operations_write_gate")
