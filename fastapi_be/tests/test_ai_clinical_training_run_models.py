"""Physical Task bounds/FKs and additive migration; no runtime receipt proof."""

import datetime as dt
import importlib.util
import uuid
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import MetaData, create_engine, inspect, text
from sqlalchemy.dialects import mysql
from sqlalchemy.exc import IntegrityError
from sqlalchemy.schema import CreateTable

from app.ai import clinical_training_configuration as cfg
from app.ai import clinical_training_contract as c
from app.ai.clinical_training_run_models import ARTIFACT_HASHES, ARTIFACT_SCHEMA, RESULT_SCHEMA, TRAINING_RUN_MODELS, AITrainingRunArtifact, AITrainingRunResult
from app.ai.models import AIAuditEvent, AIRun
from app.database import Base
from tests.test_ai_clinical_training_configuration import configured as configured
from tests.test_ai_clinical_training_configuration import selected
from tests.test_ai_clinical_training_practice import practice_case as practice_case
from tests.test_ai_clinical_training_reference_sql import reference_case as reference_case
from tests.test_ai_clinical_training_reviews import reviewed_case as reviewed_case


@pytest.fixture
def physical(configured):
    case, db = configured, configured["db"]
    context = cfg.prepare_context(db, case["actor"], selected(case))
    # Physical rows here intentionally do not claim the future native worker's
    # specific create/claim/accept receipt semantics. Source itself is genuine.
    source, binding = c.whole(context.source), context.binding()
    requester_id, provider_id = context.actor.user_id, context.provider.provider_id
    db.commit()
    previous = db.execute(text("PRAGMA foreign_keys")).scalar_one()
    db.commit()
    db.execute(text("PRAGMA foreign_keys=ON"))
    db.commit()
    run = AIRun(feature_key="clinical_training", requested_by=requester_id, provider_id=provider_id, prompt_hash="a" * 64, context_digest="b" * 64)
    db.add(run)
    db.flush()
    events = [AIAuditEvent(actor_id=requester_id, action="synthetic.physical.training." + str(index), target=run.run_id, detail_json="{}") for index in range(3)]
    db.add_all(events)
    db.flush()
    now = dt.datetime.now(dt.UTC).replace(tzinfo=None)
    values = dict(run_id=run.run_id, schema_version=ARTIFACT_SCHEMA, submission_id=binding["submission_id"], review_id=binding["review_id"], lesson_id=binding["lesson_id"], review_hash=binding["review_hash"], lesson_private_hash=binding["lesson_private_hash"], lesson_public_hash=binding["lesson_public_hash"], lesson_references_hash=binding["lesson_references_hash"], requested_by=requester_id, actor_role=context.actor.user_role, actor_epoch=context.actor.token_invalid_before, recorded_at=now, submission_hash=binding["submission_hash"], feedback_hash=binding["feedback_hash"], reference_state_hash=binding["reference_state_hash"], lesson_creation_event_id=binding["lesson_creation_event_id"], review_creation_event_id=binding["review_creation_event_id"], submission_creation_event_id=binding["submission_creation_event_id"], objective=context.selection.objective, source_binding_json=cfg.bounded_frame(binding), source_binding_hash=c.content_hash(binding), source_json=source, source_bytes=len(source.encode()), source_projection_hash=c.content_hash(context.source), prompt_id=None, prompt_version=0, prompt_snapshot_json=cfg.bounded_frame(context.prompt), prompt_snapshot_hash=c.content_hash(context.prompt), provider_id=provider_id, provider_revision=context.provider.revision, config_revision=context.config.revision, execution_snapshot_json=cfg.bounded_frame(context.execution), execution_snapshot_hash=c.content_hash(context.execution), instructions_digest=context.prompt["instructions_digest"], input_hash="c" * 64, evidence_hash="d" * 64, metadata_hash="e" * 64, run_header_hash="f" * 64, created_audit_event_id=events[0].event_id)
    row = AITrainingRunArtifact(**values)
    db.add(row)
    db.flush()
    try:
        yield db, row, events, now
    finally:
        db.rollback()
        db.execute(text("DELETE FROM hoimsystem_ai_feature_config WHERE feature_key='clinical_training'"))
        db.commit()
        db.execute(text("PRAGMA foreign_keys=" + str(previous)))
        db.commit()


@pytest.mark.parametrize("field,limit", [("source_json", 8388608), ("source_binding_json", 262144), ("prompt_snapshot_json", 262144), ("execution_snapshot_json", 262144)])
def test_actual_complete_utf8_nul_capacity_and_plus_one(physical, field, limit):
    db, row, events, now = physical
    raw = "\x00" + "😀" * ((limit - 4) // 4) + "尾"
    assert len(raw.encode()) == limit
    with db.begin_nested() as savepoint:
        setattr(row, field, raw)
        if field == "source_json":
            row.source_bytes = limit
        db.flush()
        assert db.execute(text("SELECT " + field + " FROM hoimsystem_ai_training_run_artifact WHERE run_id=:key"), dict(key=row.run_id)).scalar_one().encode() == raw.encode()
        savepoint.rollback()
    with pytest.raises(IntegrityError), db.begin_nested():
        setattr(row, field, raw + "a")
        if field == "source_json":
            row.source_bytes = limit + 1
        db.flush()


@pytest.mark.parametrize("fault", ["submission_fk", "review_hash", "private_hash", "public_hash", "references_hash", "actor", "objective", "source_bytes", "prompt_origin", "provider_revision", "config_revision", "created_fk", "duplicate_original", "claim_event_only", "claim_clock_only", "lease_only", "dispatch_without_claim", "schema", "hash"])
def test_actual_source_foreign_keys_closed_claim_identity_and_specific_audit_fk_constraints(physical, fault):
    db, row, events, now = physical
    with pytest.raises(IntegrityError), db.begin_nested():
        if fault == "submission_fk":
            row.submission_id = str(uuid.uuid4())
        elif fault in {"review_hash", "private_hash", "public_hash", "references_hash"}:
            setattr(row, fault if fault == "review_hash" else "lesson_" + fault, "0" * 64)
        elif fault == "actor":
            row.actor_role = "patient"
        elif fault == "objective":
            row.objective = "recommend_treatment"
        elif fault == "source_bytes":
            row.source_bytes -= 1
        elif fault == "prompt_origin":
            row.prompt_version = 1
        elif fault in {"provider_revision", "config_revision"}:
            setattr(row, fault, 0)
        elif fault == "created_fk":
            row.created_audit_event_id = 2147483647
        elif fault == "duplicate_original":
            row.created_audit_event_id = row.submission_creation_event_id
        elif fault == "claim_event_only":
            row.claim_event_id = events[1].event_id
        elif fault == "claim_clock_only":
            row.claimed_at = now
        elif fault == "lease_only":
            row.lease_token = str(uuid.uuid4())
        elif fault == "dispatch_without_claim":
            row.dispatch_event_id = events[1].event_id
        elif fault == "schema":
            row.schema_version = ARTIFACT_SCHEMA.upper()
        else:
            row.feedback_hash = "a" * 63
        db.flush()


def claimed_result(physical):
    db, artifact, events, now = physical
    artifact.claim_event_id, artifact.claimed_at, artifact.lease_token = events[1].event_id, now + dt.timedelta(microseconds=1), str(uuid.uuid4())
    db.flush()
    row = AITrainingRunResult(run_id=artifact.run_id, schema_version=RESULT_SCHEMA, lease_token=artifact.lease_token, accepted_at=now + dt.timedelta(microseconds=2), result_json="{}", result_bytes=2, result_hash=c.content_hash({}), source_projection_hash=artifact.source_projection_hash, instructions_digest=artifact.instructions_digest, accept_audit_event_id=events[2].event_id)
    db.add(row)
    db.flush()
    return row


def test_actual_complete_result_capacity_nul_and_plus_one(physical):
    db = physical[0]
    row, limit = claimed_result(physical), 8388608
    raw = "\x00" + "😀" * ((limit - 4) // 4) + "尾"
    with db.begin_nested() as savepoint:
        row.result_json, row.result_bytes = raw, limit
        db.flush()
        assert db.execute(text("SELECT result_json FROM hoimsystem_ai_training_run_result WHERE run_id=:key"), dict(key=row.run_id)).scalar_one().encode() == raw.encode()
        savepoint.rollback()
    with pytest.raises(IntegrityError), db.begin_nested():
        row.result_json, row.result_bytes = raw + "x", limit + 1
        db.flush()


@pytest.mark.parametrize("fault", ["lease", "source", "instructions", "accept_fk", "size", "schema"])
def test_actual_result_binds_original_claim_and_complete_source_in_compound_fk(physical, fault):
    db, row = physical[0], claimed_result(physical)
    with pytest.raises(IntegrityError), db.begin_nested():
        if fault == "lease":
            row.lease_token = str(uuid.uuid4())
        elif fault in {"source", "instructions"}:
            setattr(row, "source_projection_hash" if fault == "source" else "instructions_digest", "0" * 64)
        elif fault == "accept_fk":
            row.accept_audit_event_id = 2147483647
        elif fault == "size":
            row.result_bytes = 1
        else:
            row.schema_version = RESULT_SCHEMA.upper()
        db.flush()


def test_mysql_compilation_has_five_medium_four_utc6_eight_audit_fks_and_full_claim_binding():
    sql = "\n".join(str(CreateTable(model.__table__).compile(dialect=mysql.dialect())) for model in TRAINING_RUN_MODELS)
    assert sql.count("MEDIUMTEXT") == 5 and sql.count("DATETIME(6)") == 4
    assert sql.count("REFERENCES hoimsystem_ai_audit_event") == 8
    assert "fk_training_run_exact_review" in sql and "fk_training_result_original_claim" in sql
    assert "length(CAST(source_json AS BINARY))" in sql and "length(CAST(result_json AS BINARY))" in sql
    assert len(ARTIFACT_HASHES) == 16


def test_actual_incremental_run_up_down_up_preserves_all_prior_registered_tables_rows_and_gate():
    engine = create_engine("sqlite:///:memory:")
    names = {model.__tablename__ for model in TRAINING_RUN_MODELS}
    old = MetaData()
    for name, table in Base.metadata.tables.items():
        if name not in names:
            table.to_metadata(old)
    old.create_all(engine)
    with engine.begin() as connection:
        connection.execute(Base.metadata.tables["hoimsystem_users"].insert().values(user_id=72001, username='synthetic-training-run-migration', password='synthetic-only', user_role='super_admin'))
        connection.execute(text("INSERT INTO hoimsystem_ai_training_write_gate (gate_id,revision) VALUES (1,1)"))

    def proof():
        with engine.connect() as connection:
            return {name: (connection.execute(text("SELECT sql FROM sqlite_master WHERE type='table' AND name=:name"), dict(name=name)).scalar_one(), connection.execute(text('SELECT * FROM "' + name + '"')).all()) for name in sorted(old.tables)}

    before = proof()
    path = Path(__file__).resolve().parents[1] / "alembic/versions/20261021_clinical_training_runs.py"
    spec = importlib.util.spec_from_file_location("training_run_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    assert migration.down_revision == "20261021_training_practice"
    for step in ("up", "down", "up"):
        with engine.begin() as connection, Operations.context(MigrationContext.configure(connection)):
            migration.downgrade() if step == "down" else migration.upgrade()
        assert proof() == before
        actual = set(inspect(engine).get_table_names())
        assert names.isdisjoint(actual) if step == "down" else names.issubset(actual)
    engine.dispose()
