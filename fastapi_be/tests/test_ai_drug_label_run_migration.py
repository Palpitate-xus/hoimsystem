"""Additive task-artifact SQL constraints and precise UTF8 capacity, no model IO."""

import datetime
import importlib.util
import uuid
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.dialects import mysql
from sqlalchemy.exc import IntegrityError
from sqlalchemy.schema import CreateTable

from app.ai.drug_label_run_models import ARTIFACT_SCHEMA, HASH_FIELDS, MAX_RESULT_BYTES
from app.ai.drug_label_run_models import AIDrugLabelRunArtifact as Artifact
from app.ai.models import AIAuditEvent, AIRun
from app.database import Base
from app.models import User
from tests.test_ai_drug_label_sources import label_case as _label_case
from tests.test_ai_drug_label_sources import publish

label_case = _label_case

PATH = Path(__file__).parents[1] / "alembic/versions/20261021_drug_label_runs.py"
spec = importlib.util.spec_from_file_location("drug_label_run_migration", PATH)
migration = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migration)
UID = "00000000-0000-0000-0000-000000000073"
H = "ab" * 32
NOW = datetime.datetime(2026, 10, 21, 12, 0, 0, 123456)


def test_up_down_up_changes_only_the_new_table():
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        Base.metadata.create_all(conn, tables=[t for t in Base.metadata.sorted_tables if t.name != Artifact.__tablename__])
        conn.execute(User.__table__.insert().values(user_id=1, username="artifact-synthetic", user_role="super_admin"))

        def snapshot():
            return dict(conn.execute(text("SELECT name,sql FROM sqlite_master WHERE type='table' ORDER BY name")).all())

        before = snapshot()
        with Operations.context(MigrationContext.configure(conn)):
            migration.upgrade()
        first = snapshot()
        assert set(first) - set(before) == {Artifact.__tablename__}
        assert {k: v for k, v in first.items() if k != Artifact.__tablename__} == before
        actual = inspect(conn)
        assert {c["name"] for c in actual.get_columns(Artifact.__tablename__)} == set(Artifact.__table__.c.keys())
        assert {c["name"] for c in actual.get_check_constraints(Artifact.__tablename__)} == {c.name for c in Artifact.__table__.constraints if c.__class__.__name__ == "CheckConstraint"}
        assert len(actual.get_foreign_keys(Artifact.__tablename__)) == 6
        with Operations.context(MigrationContext.configure(conn)):
            migration.downgrade()
        assert snapshot() == before
        assert conn.execute(text("SELECT username FROM hoimsystem_users WHERE user_id=1")).scalar_one() == "artifact-synthetic"
        with Operations.context(MigrationContext.configure(conn)):
            migration.upgrade()
        assert snapshot() == first
    engine.dispose()


def test_mysql_ddl_has_two_utc6_one_mediumtext_and_exact_binary_bytes():
    sql = str(CreateTable(Artifact.__table__).compile(dialect=mysql.dialect()))
    assert sql.count("DATETIME(6)") == 2 and sql.count("MEDIUMTEXT") == 1
    assert "CAST(result_json AS BINARY)" in sql
    assert "ON DELETE CASCADE" not in sql
    assert migration.down_revision == "20261021_drug_label_sources"
    assert len(migration.revision) <= 32
    assert set(HASH_FIELDS) == {"input_hash", "evidence_hash", "metadata_hash", "prompt_hash", "context_digest", "source_binding_hash"}


@pytest.fixture
def artifact_data(label_case):
    db, users, *_ = label_case
    source = publish(label_case)
    actor = users["pharmacist_user"].user_id
    run = AIRun(run_id=str(uuid.uuid4()), feature_key="drug_label_extraction", requested_by=actor, prompt_hash=H, context_digest=H)
    db.add(run)
    events = [AIAuditEvent(actor_id=actor, action="synthetic-artifact", target=run.run_id) for _ in range(3)]
    db.add_all(events)
    db.commit()
    return (
        db,
        dict(
            run_id=run.run_id,
            source_binding_id=source.snapshot.source_binding_id,
            requested_by=actor,
            schema_version=ARTIFACT_SCHEMA,
            created_at=NOW,
            mapping_seed=H,
            create_event_id=events[0].event_id,
            **{key: H for key in HASH_FIELDS},
        ),
        [e.event_id for e in events],
    )


@pytest.mark.parametrize(
    "change",
    [
        {"mapping_seed": "A" * 64},
        {"input_hash": "z" * 64},
        {"run_id": UID.upper()},
        {"requested_by": 0},
        {"schema_version": ARTIFACT_SCHEMA.upper()},
        {"create_event_id": 0},
        {"accepted_at": NOW},
        {"accepted_lease": UID},
        {"result_hash": H},
        {"result_json": "{}"},
    ],
)
def test_database_rejects_invalid_immutable_or_partial_acceptance(artifact_data, change):
    db, values, _ = artifact_data
    if change.get("run_id") == UID:
        change = {"run_id": "ABCDEF00-0000-0000-0000-000000000073"}
    db.add(Artifact(**{**values, **change}))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


@pytest.mark.parametrize("mode", ["small_emoji", "ascii_limit", "emoji_limit"])
def test_database_preserves_whole_utf8_result_and_utc6(artifact_data, mode):
    text_value = {"small_emoji": lambda: "😀", "ascii_limit": lambda: "a" * MAX_RESULT_BYTES, "emoji_limit": lambda: "😀" * (MAX_RESULT_BYTES // 4)}[mode]()
    db, values, events = artifact_data
    row = Artifact(**values, result_json=text_value, result_hash=H, result_bytes=len(text_value.encode()), accepted_lease=UID, accepted_at=NOW, receipt_event_id=events[1], accept_event_id=events[2])
    db.add(row)
    db.commit()
    db.expire_all()
    actual = db.get(Artifact, values["run_id"])
    assert actual.result_json == text_value and actual.result_bytes == len(text_value.encode())
    assert actual.created_at == actual.accepted_at == NOW
    assert actual.mapping_seed == H


@pytest.mark.parametrize("axis", ["oversize", "characters_not_bytes", "same_audit", "early_clock", "lease_format"])
def test_complete_acceptance_checks_cannot_be_bypassed(artifact_data, axis):
    db, values, events = artifact_data
    extra = dict(result_json="😀", result_hash=H, result_bytes=4, accepted_lease=UID, accepted_at=NOW, receipt_event_id=events[1], accept_event_id=events[2])
    if axis == "oversize":
        extra.update(result_json="a" * (MAX_RESULT_BYTES + 1), result_bytes=MAX_RESULT_BYTES + 1)
    elif axis == "characters_not_bytes":
        extra["result_bytes"] = 1
    elif axis == "same_audit":
        extra["accept_event_id"] = events[1]
    elif axis == "early_clock":
        extra["accepted_at"] = NOW - datetime.timedelta(microseconds=1)
    else:
        extra["accepted_lease"] = "Z" * 36
    db.add(Artifact(**values, **extra))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()
