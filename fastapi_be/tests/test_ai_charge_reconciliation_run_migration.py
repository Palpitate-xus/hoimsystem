"""Actual incremental artifact DDL and bounded SQL storage, no worker claim."""

import hashlib
import importlib.util
import uuid
from io import StringIO
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import CheckConstraint, create_engine, inspect, text
from sqlalchemy.dialects import mysql
from sqlalchemy.exc import IntegrityError

from app.ai.charge_reconciliation_run_models import MAX_RESULT_BYTES, SHA_FIELDS, AIChargeRunArtifact
from app.ai.models import AIAuditEvent, AIRun
from app.database import Base
from tests.test_ai_charge_reconciliation_sources import NOW, draft
from tests.test_ai_charge_reconciliation_sources import charge_case as _charge_case
from tests.test_inpatient_support_migration import snapshot

charge_case = _charge_case


def migration():
    path = Path(__file__).resolve().parents[1] / "alembic/versions/20261021_charge_runs.py"
    spec = importlib.util.spec_from_file_location("isolated_charge_run_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_actual_artifact_upgrade_downgrade_upgrade_preserves_all_existing_ddl_and_rows(tmp_path):
    engine = create_engine("sqlite:///" + str(tmp_path / "charge-artifact.sqlite"))
    table = AIChargeRunArtifact.__table__
    Base.metadata.create_all(engine, tables=[t for t in Base.metadata.sorted_tables if t.name != table.name])
    names = set(inspect(engine).get_table_names())
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO hoimsystem_users(user_id,username,user_role) VALUES(90691,'charge_artifact_seed','super_admin')"))
        connection.execute(text("INSERT INTO hoimsystem_patient(patient_id,name) VALUES(90692,'原有合成收费患者🙂')"))
        original = snapshot(connection, names)
    for action in ("upgrade", "downgrade", "upgrade"):
        with engine.begin() as connection, Operations.context(MigrationContext.configure(connection)):
            getattr(migration(), action)()
        inspector = inspect(engine)
        assert set(inspector.get_table_names()) == names | ({table.name} if action == "upgrade" else set())
        with engine.connect() as connection:
            assert snapshot(connection, names) == original
        if action == "upgrade":
            assert {r["name"]: r["nullable"] for r in inspector.get_columns(table.name)} == {c.name: c.nullable for c in table.columns}
            assert {r["name"] for r in inspector.get_check_constraints(table.name)} == {c.name for c in table.constraints if isinstance(c, CheckConstraint)}
            assert {(tuple(r["constrained_columns"]), r["referred_table"], tuple(r["referred_columns"])) for r in inspector.get_foreign_keys(table.name)} == {
                (tuple(e.parent.name for e in f.elements), next(iter(f.elements)).column.table.name, tuple(e.column.name for e in f.elements)) for f in table.foreign_key_constraints
            }
    engine.dispose()


def test_actual_artifact_mysql_ddl_is_exact_utf8_bytes_and_single_incremental_table():
    module = migration()
    assert module.down_revision == "20261021_charge_cases" and len(module.revision) <= 32
    output = StringIO()
    with Operations.context(MigrationContext.configure(dialect=mysql.dialect(), opts={"as_sql": True, "output_buffer": output})):
        module.upgrade()
    ddl = output.getvalue()
    assert ddl.count("CREATE TABLE") == ddl.count("DATETIME(6)") == ddl.count("MEDIUMTEXT") == 1
    assert "length(CAST(result_json AS BINARY)) = result_bytes" in ddl
    assert ddl.count("FOREIGN KEY") == 4 and "AUTO_INCREMENT" not in ddl
    assert "8388608" in ddl and "HEX(input_hash)" in ddl and "HEX(schema_version)" in ddl
    output = StringIO()
    with Operations.context(MigrationContext.configure(dialect=mysql.dialect(), opts={"as_sql": True, "output_buffer": output})):
        module.downgrade()
    assert output.getvalue().strip() == "DROP TABLE hoimsystem_ai_charge_run_artifact;"


def artifact(case):
    db = case["db"]
    source = draft(case)
    run = AIRun(
        feature_key="charge_reconciliation",
        requested_by=case["super_admin_user"].user_id,
        patient_id=case["patient"].patient_id,
        prompt_hash="a" * 64,
        context_digest="b" * 64,
        input_json="{}",
        result_json="{}",
        evidence_json="[]",
        context_metadata_json="{}",
        status="queued",
        create_time=NOW,
    )
    db.add(run)
    db.flush()
    row = AIChargeRunArtifact(
        run_id=run.run_id,
        case_snapshot_id=source["case_snapshot_id"],
        requested_by=run.requested_by,
        schema_version="charge_run_artifact_v1",
        created_at=NOW,
        **{name: "a" * 64 for name in SHA_FIELDS},
    )
    db.add(row)
    db.commit()
    return row


def test_actual_artifact_queue_anchor_and_complete_unicode_result_roundtrip(charge_case):
    case, db = charge_case, charge_case["db"]
    row = artifact(case)
    assert row.result_json is row.result_hash is row.result_bytes is row.receipt_event_id is row.accepted_lease is None
    assert row.created_at.microsecond == 123456
    receipt = AIAuditEvent(actor_id=row.requested_by, action="charge.result.SQL_storage_test_only", target=row.run_id, detail_json="{}")
    db.add(receipt)
    db.flush()
    payload = "🙂" * (MAX_RESULT_BYTES // 4)
    row.result_json, row.result_hash, row.result_bytes = payload, hashlib.sha256(payload.encode()).hexdigest(), len(payload.encode())
    row.receipt_event_id, row.accepted_lease = receipt.event_id, str(uuid.uuid4())
    db.commit()
    db.expire_all()
    stored = db.get(AIChargeRunArtifact, row.run_id)
    assert stored.result_json == payload and stored.result_bytes == MAX_RESULT_BYTES
    assert stored.result_hash == hashlib.sha256(stored.result_json.encode()).hexdigest()
    assert stored.receipt_event_id == receipt.event_id


@pytest.mark.parametrize(
    "values",
    [
        {"schema_version": "CHARGE_RUN_ARTIFACT_V1"},
        *[{name: "A" * 64} for name in SHA_FIELDS],
        {"input_hash": "g" * 64},
        {"result_json": "🙂", "result_hash": "a" * 64, "result_bytes": 1},
        {"result_json": "{}", "result_hash": None, "result_bytes": 2},
        {"result_json": "{}", "result_hash": "G" * 64, "result_bytes": 2},
        {"result_json": "x" * (MAX_RESULT_BYTES + 1), "result_hash": "a" * 64, "result_bytes": MAX_RESULT_BYTES + 1},
        {"result_json": "", "result_hash": "a" * 64, "result_bytes": 0},
        {"accepted_lease": "A" * 8 + "-" + "b" * 4 + "-" + "c" * 4 + "-" + "d" * 4 + "-" + "e" * 12},
        {"accepted_lease": "not-a-lease"},
        {"receipt_event_id": 0},
        {"receipt_event_id": 2147483647},
        {"requested_by": 0},
        {"case_snapshot_id": str(uuid.uuid4())},
    ],
    ids=lambda values: ",".join(values),
)
def test_actual_artifact_sql_rejects_hash_tuple_utf8_capacity_lease_and_fk_faults(charge_case, values):
    row, db = artifact(charge_case), charge_case["db"]
    identifier = row.run_id
    db.rollback()
    previous_fk = db.scalar(text("PRAGMA foreign_keys"))
    db.execute(text("PRAGMA foreign_keys=ON"))
    assert db.scalar(text("PRAGMA foreign_keys")) == 1
    try:
        with pytest.raises(IntegrityError), db.begin_nested():
            db.execute(AIChargeRunArtifact.__table__.update().where(AIChargeRunArtifact.run_id == identifier).values(**values))
    finally:
        db.rollback()
        db.execute(text("PRAGMA foreign_keys=" + ("ON" if previous_fk else "OFF")))
        db.commit()
