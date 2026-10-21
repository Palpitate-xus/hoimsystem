"""Actual FK/storage/migration capacity only; no Task authorization or model execution."""

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

from app.ai.models import AIAuditEvent, AIProvider, AIRun
from app.ai.operations_support_run_models import ARTIFACT_SCHEMA, OPERATIONS_RUN_MODELS, RESULT_SCHEMA, AIOperationsRunArtifact, AIOperationsRunResult
from tests.test_ai_operations_support_cases import collection as collection  # noqa: F401
from tests.test_ai_operations_support_registry import source as source  # noqa: F401
from tests.test_ai_operations_support_releases import actors as actors  # noqa: F401

NOW = dt.datetime(2026, 10, 21, 18, 0, 0, 123456)
MIGRATION = Path(__file__).resolve().parents[1] / "alembic/versions/20261021_operations_support_runs.py"


def receipt(db, actor):
    row = AIAuditEvent(actor_id=actor, action="synthetic_ops_run_model_only", target="synthetic:" + str(uuid.uuid4()), detail_json="{}", create_time=NOW.replace(microsecond=0))
    db.add(row)
    db.flush()
    return row.event_id


@pytest.fixture
def rows(collection):
    identities, original, release, case = collection
    db, registrar, creator, reviewer, admin = identities
    provider = AIProvider(name="synthetic-ops-" + uuid.uuid4().hex, kind="chat", api_base="https://synthetic-ops.invalid/v1", model="synthetic", created_by=registrar.user_id)
    db.add(provider)
    db.flush()
    run = AIRun(
        feature_key="operations_support",
        requested_by=admin.user_id,
        provider_id=provider.provider_id,
        provider_revision=1,
        prompt_hash="a" * 64,
        context_digest="b" * 64,
        create_time=NOW.replace(microsecond=0),
    )
    db.add(run)
    db.flush()
    fields = dict(
        run_id=run.run_id,
        schema_version=ARTIFACT_SCHEMA,
        case_id=case["case_id"],
        case_requested_by=admin.user_id,
        case_private_hash=case["private_hash"],
        case_public_hash=case["public_hash"],
        case_membership_hash=case["member_bindings_hash"],
        requested_by=admin.user_id,
        actor_token_invalid_before=None,
        recorded_at=NOW,
        objective="prepare_reviewed_checks",
        source_binding_hash="c" * 64,
        source_json="{}",
        source_bytes=2,
        source_projection_hash=case["public_hash"],
        prompt_id=None,
        prompt_version=0,
        prompt_snapshot_json="{}",
        prompt_snapshot_hash="d" * 64,
        provider_id=provider.provider_id,
        provider_revision=1,
        config_revision=1,
        execution_snapshot_json="{}",
        execution_snapshot_hash="e" * 64,
        instructions_digest="f" * 64,
        input_hash="1" * 64,
        evidence_hash="2" * 64,
        metadata_hash="3" * 64,
        run_header_hash="4" * 64,
        created_audit_event_id=receipt(db, admin.user_id),
        claim_event_id=None,
        dispatch_event_id=None,
        usage_event_id=None,
    )
    return db, admin, fields


def artifact(rows, **changes):
    db, actor, fields = rows
    row = AIOperationsRunArtifact(**{**fields, **changes})
    db.add(row)
    db.flush()
    return row


def result(rows, **changes):
    db, actor, fields = rows
    values = dict(
        run_id=fields["run_id"],
        schema_version=RESULT_SCHEMA,
        lease_token=str(uuid.uuid4()),
        accepted_at=NOW,
        result_json="{}",
        result_bytes=2,
        result_hash="5" * 64,
        source_binding_hash=fields["source_binding_hash"],
        instructions_digest=fields["instructions_digest"],
        accept_audit_event_id=receipt(db, actor.user_id),
    )
    row = AIOperationsRunResult(**{**values, **changes})
    db.add(row)
    db.flush()
    return row


def test_mysql_ddl_uses_three_utc6_and_four_mediumtext_without_old_table_mutation():
    ddl = [str(CreateTable(model.__table__).compile(dialect=mysql.dialect())) for model in OPERATIONS_RUN_MODELS]
    assert sum(value.count("DATETIME(6)") for value in ddl) == 3
    assert sum(value.count("MEDIUMTEXT") for value in ddl) == 4
    assert "CAST(source_json AS BINARY)" in ddl[0] and "CAST(result_json AS BINARY)" in ddl[1]
    assert all(len(constraint.name or "") <= 64 for model in OPERATIONS_RUN_MODELS for constraint in model.__table__.constraints)


def test_actual_source_case_composite_and_all_concrete_event_fks(rows):
    db, actor, fields = rows
    row = artifact(rows)
    accepted = result(rows)
    assert row.actor_token_invalid_before is None and row.recorded_at.microsecond == accepted.accepted_at.microsecond == 123456
    assert accepted.accept_audit_event_id != row.created_audit_event_id


@pytest.mark.parametrize(
    "field,value",
    [
        ("case_private_hash", "0" * 64),
        ("case_public_hash", "0" * 64),
        ("case_requested_by", 999999),
        ("created_audit_event_id", 999999),
        ("claim_event_id", 999999),
        ("source_bytes", 1),
        ("schema_version", "wrong_schema"),
    ],
)
def test_wrong_case_or_actual_fk_or_whole_byte_count_is_rejected_physically(rows, field, value):
    db, _, _ = rows
    with pytest.raises(IntegrityError), db.begin_nested():
        artifact(rows, **{field: value})


def test_actual_receipt_ids_cannot_alias_each_other(rows):
    db, actor, fields = rows
    with pytest.raises(IntegrityError), db.begin_nested():
        artifact(rows, claim_event_id=fields["created_audit_event_id"])
    claimed = receipt(db, actor.user_id)
    with pytest.raises(IntegrityError), db.begin_nested():
        artifact(rows, claim_event_id=claimed, dispatch_event_id=claimed)


@pytest.mark.parametrize("field,value", [("source_binding_hash", "0" * 64), ("instructions_digest", "0" * 64), ("accept_audit_event_id", 999999), ("result_bytes", 1)])
def test_result_fk_binds_exact_artifact_and_actual_receipt_before_body(rows, field, value):
    db, _, _ = rows
    artifact(rows)
    with pytest.raises(IntegrityError), db.begin_nested():
        result(rows, **{field: value})


def test_complete_non_bmp_bom_crlf_nul_and_more_than_text_capacity_roundtrip(rows):
    db, _, fields = rows
    body = "\ufeff😀原字面量\r\n\x00  " * 10000
    row = artifact(rows, source_json=body, source_bytes=len(body.encode()))
    db.expire(row)
    assert db.query(AIOperationsRunArtifact.source_json).filter_by(run_id=fields["run_id"]).scalar().encode() == body.encode()
    accepted = result(rows, result_json=body, result_bytes=len(body.encode()))
    assert accepted.result_bytes > 65535 and accepted.result_json.encode() == body.encode()


def test_exact_whole8m_source_result_and262144_frame_boundaries(rows):
    db, _, _ = rows
    source = "😀" * (8388608 // 4)
    frame = "😀" * (262144 // 4)
    row = artifact(rows, source_json=source, source_bytes=8388608, prompt_snapshot_json=frame, execution_snapshot_json=frame)
    assert len(row.source_json.encode()) == 8388608
    accepted = result(rows, result_json=source, result_bytes=8388608)
    assert len(accepted.result_json.encode()) == 8388608
    for column_name, body in [("source_json", source + "a"), ("prompt_snapshot_json", frame + "a"), ("execution_snapshot_json", frame + "a")]:
        values = {column_name: body}
        if column_name == "source_json":
            values["source_bytes"] = 8388609
        with pytest.raises(IntegrityError), db.begin_nested():
            db.query(AIOperationsRunArtifact).filter_by(run_id=row.run_id).update(values, synchronize_session=False)
            db.flush()
    with pytest.raises(IntegrityError), db.begin_nested():
        db.query(AIOperationsRunResult).filter_by(run_id=accepted.run_id).update({"result_json": source + "a", "result_bytes": 8388609}, synchronize_session=False)
        db.flush()


def test_self_contained_incremental_sqlite_up_down_up_preserves_every_synthetic_prerequisite_table():
    spec = importlib.util.spec_from_file_location("synthetic_ops_run_migration", MIGRATION)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        for statement in [
            "CREATE TABLE hoimsystem_users (user_id INTEGER PRIMARY KEY)",
            "CREATE TABLE hoimsystem_ai_run (run_id VARCHAR(36) PRIMARY KEY)",
            "CREATE TABLE hoimsystem_ai_provider (provider_id INTEGER PRIMARY KEY)",
            "CREATE TABLE hoimsystem_ai_prompt_version (prompt_id VARCHAR(36) PRIMARY KEY)",
            "CREATE TABLE hoimsystem_ai_audit_event (event_id INTEGER PRIMARY KEY)",
            "CREATE TABLE hoimsystem_ai_operations_case (case_id VARCHAR(36) PRIMARY KEY,private_hash VARCHAR(64) NOT NULL,public_hash VARCHAR(64) NOT NULL,requested_by INTEGER NOT NULL,UNIQUE(case_id,private_hash,public_hash,requested_by))",
        ]:
            conn.exec_driver_sql(statement)
        conn.exec_driver_sql("INSERT INTO hoimsystem_users VALUES (1)")

    def oldproof():
        with engine.connect() as conn:
            names = sorted(name for name in inspect(conn).get_table_names() if name not in {model.__tablename__ for model in OPERATIONS_RUN_MODELS})
            return {
                name: (conn.execute(text("SELECT sql FROM sqlite_master WHERE type='table' AND name=:name"), {"name": name}).scalar(), conn.exec_driver_sql("SELECT * FROM " + name).all())
                for name in names
            }

    baseline = oldproof()
    for down in [False, True, False]:
        with engine.begin() as conn:
            with Operations.context(MigrationContext.configure(conn)):
                migration.downgrade() if down else migration.upgrade()
        assert oldproof() == baseline
        assert all((model.__tablename__ not in inspect(engine).get_table_names()) == down for model in OPERATIONS_RUN_MODELS)
    buffer = io.StringIO()
    with Operations.context(MigrationContext.configure(dialect_name="mysql", opts={"as_sql": True, "output_buffer": buffer})):
        migration.upgrade()
        migration.downgrade()
    ddl = buffer.getvalue()
    assert "ALTER TABLE" not in ddl and "DROP INDEX" not in ddl
    assert ddl.count("DATETIME(6)") == 3 and ddl.count("MEDIUMTEXT") == 4
    assert "app.ai" not in MIGRATION.read_text() and "app.models" not in MIGRATION.read_text()
    engine.dispose()
