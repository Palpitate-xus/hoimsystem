"""Real isolated SQLite task DDL/rows and independent MySQL DDL compilation.

These are schema constraints, not successful model calls or task authorization.
No clinical schema or existing Source migration byte is changed.
"""

import datetime as dt
import hashlib
import sys
import types
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.config import Config
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy.dialects import mysql
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import declarative_base

from tests import test_ai_rca_evidence_migration as source
from tests.test_ai_rca_evidence_migration import database as database

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "alembic/versions/20261021_rca_evidence_runs.py"
migration = source.module(PATH, "synthetic_rca_task_migration")
ARTIFACT = "hoimsystem_ai_rca_evidence_run_artifact"
RESULT = "hoimsystem_ai_rca_evidence_run_result"
RUN = "00000000-0000-0000-0000-000000000030"
RUN2 = "00000000-0000-0000-0000-000000000031"
LEASE = "00000000-0000-0000-0000-000000000032"
CASE = "00000000-0000-0000-0000-000000000020"
NOW = source.NOW


@pytest.fixture
def task_database(database):
    source.apply(database, "upgrade")
    database.execute(sa.insert(source.table(database, source.TABLES[0])), [source.grant(1), source.grant(2, permission_kind="associated_patient_processing")])
    database.execute(sa.insert(source.table(database, source.TABLES[2])), source.case())
    database.exec_driver_sql("CREATE TABLE hoimsystem_ai_run (run_id VARCHAR(36) PRIMARY KEY, feature_key VARCHAR(64), status VARCHAR(24), input_json TEXT)")
    for identifier in (RUN, RUN2):
        database.execute(sa.text("INSERT INTO hoimsystem_ai_run VALUES (:id,'incident_rca','queued','{}')"), {"id": identifier})
    database.commit()
    return database


def apply(db, name):
    from alembic.migration import MigrationContext

    with Operations.context(MigrationContext.configure(db)):
        getattr(migration, name)()
    db.commit()


def artifact(**changes):
    raw = '{"released":"' + "原文🙂\ufeff" * 12000 + '"}'
    return {
        "run_id": RUN,
        "case_id": CASE,
        "event_id": 1,
        "patient_id_at_capture": 1,
        "requested_by": 1,
        "schema_version": "rca_evidence_run_artifact_v1",
        "recorded_at": NOW,
        "source_json": raw,
        "source_bytes": len(raw.encode()),
        "binding_json": "{}",
        "binding_bytes": 2,
        **{name: "a" * 64 for name in migration.ANCHOR_FIELDS},
        "source_hash": hashlib.sha256(raw.encode()).hexdigest(),
        "create_event_id": 5,
        "claim_event_id": None,
        "claim_lease": None,
        "claimed_at": None,
        "dispatch_event_id": None,
        "dispatched_at": None,
        "usage_event_id": None,
        **changes,
    }


def claimed(**changes):
    return artifact(claim_event_id=6, claim_lease=LEASE, claimed_at=NOW + dt.timedelta(microseconds=1), **changes)


def accepted(**changes):
    raw = '{"draft":"' + "精确引文😀" * 15000 + '"}'
    return {
        "run_id": RUN,
        "schema_version": "rca_evidence_run_result_v1",
        "source_hash": artifact()["source_hash"],
        "instructions_digest": "a" * 64,
        "accepted_lease": LEASE,
        "accepted_at": NOW + dt.timedelta(microseconds=3),
        "result_json": raw,
        "result_bytes": len(raw.encode()),
        "result_hash": hashlib.sha256(raw.encode()).hexdigest(),
        "accept_audit_event_id": 9,
        **changes,
    }


def existing_snapshot(db):
    names = (*source.LEGACY, *source.TABLES, "hoimsystem_ai_run")
    return {
        name: {
            "ddl": db.scalar(sa.text("SELECT sql FROM sqlite_master WHERE type='table' AND name=:name"), {"name": name}),
            "rows": [list(row) for row in db.execute(sa.text("SELECT * FROM " + name + " ORDER BY 1"))],
        }
        for name in names
    }


def test_actual_up_down_up_and_complete_unicode_readback_keep_existing_ddl_and_rows(task_database):
    db = task_database
    before = existing_snapshot(db)
    for operation in ("upgrade", "downgrade", "upgrade"):
        apply(db, operation)
        assert existing_snapshot(db) == before
    row = claimed(dispatch_event_id=7, dispatched_at=NOW + dt.timedelta(microseconds=2), usage_event_id=8)
    db.execute(sa.insert(source.table(db, ARTIFACT)), row)
    result = accepted()
    db.execute(sa.insert(source.table(db, RESULT)), result)
    db.commit()
    actual = dict(db.execute(sa.select(source.table(db, ARTIFACT))).mappings().one())
    actual_result = dict(db.execute(sa.select(source.table(db, RESULT))).mappings().one())
    assert actual == row and actual_result == result
    assert actual["source_bytes"] > 65535 and actual_result["result_bytes"] > 65535
    assert actual["claimed_at"].microsecond == 123457 and actual_result["accepted_at"].microsecond == 123459


@pytest.mark.parametrize(
    "changes",
    [
        {"schema_version": "RCA_evidence_run_artifact_v1"},
        {"requested_by": 0},
        {"patient_id_at_capture": 0},
        {"source_bytes": 0},
        {"source_bytes": 8388609},
        {"binding_bytes": 65536},
        {"binding_bytes": 1},
        {"source_hash": "A" * 64},
        {"input_hash": "x" * 64},
        {"create_event_id": None},
        {"claim_event_id": 6},
        {"claim_lease": LEASE},
        {"claimed_at": NOW},
        {"claim_event_id": 5, "claim_lease": LEASE, "claimed_at": NOW},
        {"claim_event_id": 6, "claim_lease": LEASE, "claimed_at": NOW - dt.timedelta(microseconds=1)},
        {"claim_event_id": 6, "claim_lease": "bad-lease", "claimed_at": NOW},
        {"dispatch_event_id": 7, "dispatched_at": NOW},
        {"dispatch_event_id": 7},
        {"dispatched_at": NOW},
        {"usage_event_id": 5},
        {"usage_event_id": -1},
        {"event_id": 999999},
        {"case_id": "00000000-0000-0000-0000-000000000099"},
    ],
)
def test_incomplete_claim_dispatch_wrong_anchor_or_nonexistent_parent_is_rejected(task_database, changes):
    db = task_database
    apply(db, "upgrade")
    with pytest.raises(IntegrityError):
        db.execute(sa.insert(source.table(db, ARTIFACT)), artifact(**changes))
        db.commit()
    db.rollback()
    assert db.scalar(sa.select(sa.func.count()).select_from(source.table(db, ARTIFACT))) == 0


@pytest.mark.parametrize(
    "changes",
    [
        {"accepted_lease": "00000000-0000-0000-0000-000000000033"},
        {"source_hash": "b" * 64},
        {"instructions_digest": "b" * 64},
        {"result_bytes": 1},
        {"result_bytes": 8388609},
        {"result_hash": "X" * 64},
        {"schema_version": "generic_result"},
        {"accept_audit_event_id": 999999},
    ],
)
def test_result_requires_the_actual_claim_and_whole_source_and_independent_audit(task_database, changes):
    db = task_database
    apply(db, "upgrade")
    db.execute(sa.insert(source.table(db, ARTIFACT)), claimed())
    db.commit()
    with pytest.raises(IntegrityError):
        db.execute(sa.insert(source.table(db, RESULT)), accepted(**changes))
        db.commit()
    db.rollback()
    assert db.scalar(sa.select(sa.func.count()).select_from(source.table(db, RESULT))) == 0
    assert db.scalar(sa.select(sa.func.count()).select_from(source.table(db, ARTIFACT))) == 1


def test_duplicate_claim_audit_and_lease_cannot_be_reused_for_a_second_run(task_database):
    db = task_database
    apply(db, "upgrade")
    db.execute(sa.insert(source.table(db, ARTIFACT)), claimed())
    db.commit()
    for changes in ({"claim_event_id": 6, "claim_lease": "00000000-0000-0000-0000-000000000039"}, {"claim_event_id": 10, "claim_lease": LEASE}):
        with pytest.raises(IntegrityError):
            db.execute(sa.insert(source.table(db, ARTIFACT)), artifact(run_id=RUN2, create_event_id=11, claimed_at=NOW, **changes))
            db.commit()
        db.rollback()


def test_single_actual_descendant_preserves_both_source_and_shared_parent_ancestry():
    scripts = ScriptDirectory.from_config(Config(str(ROOT / "alembic.ini")))
    assert len(scripts.get_heads()) == 1
    assert migration.revision == "20261021_rca_evidence_runs" and len(migration.revision) <= 32
    assert migration.down_revision == "20261021_rca_evidence"
    chain = [row.revision for row in scripts.walk_revisions()]
    assert len(chain) == len(set(chain))
    assert chain.index(migration.revision) < chain.index(migration.down_revision) < chain.index("20261021_native_shared_merge")


def test_independent_models_match_actual_migration_mysql_mediumtext_utc6_and_constraints(monkeypatch, task_database):
    base = declarative_base()
    stub = types.ModuleType("app.database")
    stub.Base = base
    with monkeypatch.context() as patch:
        patch.setitem(sys.modules, "app.database", stub)
        source_models = source.module(ROOT / "app/ai/rca_evidence_models.py", "synthetic_rca_task_source_models")
        patch.setitem(sys.modules, "app.ai.rca_evidence_models", source_models)
        models = source.module(ROOT / "app/ai/rca_evidence_run_models.py", "synthetic_rca_task_models")
    assert len(models.RCA_EVIDENCE_RUN_MODELS) == 2
    for name, key in (("hoimsystem_ai_run", "run_id"), ("hoimsystem_ai_rca_evidence_case", "case_id")):
        if name not in base.metadata.tables:
            sa.Table(name, base.metadata, sa.Column(key, sa.String(36), primary_key=True))
    for name, key in (("hoimsystem_adverse_event", "event_id"), ("hoimsystem_patient", "patient_id"), ("hoimsystem_users", "user_id"), ("hoimsystem_ai_audit_event", "event_id")):
        if name not in base.metadata.tables:
            sa.Table(name, base.metadata, sa.Column(key, sa.Integer, primary_key=True))
    sql = []
    engine = sa.create_mock_engine("mysql+pymysql://", lambda query, *a, **kw: sql.append(str(query.compile(dialect=mysql.dialect()))))
    with Operations.context(__import__("alembic.migration", fromlist=["MigrationContext"]).MigrationContext.configure(engine)):
        migration.upgrade()
    assert sum("MEDIUMTEXT" in statement for statement in sql) == 2
    assert "\n".join(sql).count("DATETIME(6)") == 4
    assert "FOREIGN KEY(run_id, accepted_lease)" in "\n".join(sql)
    assert "FOREIGN KEY(run_id, source_hash, instructions_digest)" in "\n".join(sql)
    assert "AUTO_INCREMENT" not in "\n".join(sql)
    db = task_database
    apply(db, "upgrade")
    for model in models.RCA_EVIDENCE_RUN_MODELS:
        actual = source.table(db, model.__tablename__)
        assert set(actual.columns.keys()) == set(model.__table__.columns.keys())
        expected_checks = {
            str(check.sqltext.compile(dialect=sa.dialects.sqlite.dialect(), compile_kwargs={"literal_binds": True, "include_table": False}))
            for check in model.__table__.constraints
            if isinstance(check, sa.CheckConstraint)
        }
        actual_checks = {str(check.sqltext) for check in actual.constraints if isinstance(check, sa.CheckConstraint)}
        assert expected_checks == actual_checks
