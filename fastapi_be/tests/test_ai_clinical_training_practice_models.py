"""Actual practice physical UTF8 constraints/FKs and incremental migration."""

import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import MetaData, create_engine, inspect, text
from sqlalchemy.dialects import mysql
from sqlalchemy.exc import IntegrityError
from sqlalchemy.schema import CreateTable

from app.ai import clinical_training_practice as practice
from app.ai.clinical_training_practice_models import AITrainingSubmission
from app.database import Base
from tests.test_ai_clinical_training_practice import practice_case as practice_case
from tests.test_ai_clinical_training_practice import request
from tests.test_ai_clinical_training_reference_sql import reference_case as reference_case
from tests.test_ai_clinical_training_reviews import reviewed_case as reviewed_case


@pytest.fixture
def physical(practice_case):
    db = practice_case[0]
    db.commit()
    before = db.execute(text("PRAGMA foreign_keys")).scalar_one()
    db.commit()
    db.execute(text("PRAGMA foreign_keys=ON"))
    ack = practice.submit_practice(db, practice_case[-1], request(practice_case))
    row = db.get(AITrainingSubmission, ack["submission_id"])
    yield db, row
    db.rollback()
    db.execute(text("PRAGMA foreign_keys=" + str(before)))
    db.commit()


@pytest.mark.parametrize("prefix,limit", [("submission", 131072), ("feedback", 8388608)])
def test_actual_whole_literal_utf8_nul_exact_capacity_and_plus_one_without_truncation(physical, prefix, limit):
    db, row = physical
    raw = "\x00" + "😀" * ((limit - 4) // 4) + "尾"
    assert len(raw.encode()) == limit
    with db.begin_nested() as savepoint:
        setattr(row, prefix + "_json", raw)
        setattr(row, prefix + "_bytes", limit)
        db.flush()
        assert db.execute(text("SELECT length(CAST(" + prefix + "_json AS BLOB)) FROM hoimsystem_ai_training_submission WHERE submission_id=:key"), {"key": row.submission_id}).scalar_one() == limit
        savepoint.rollback()
    with pytest.raises(IntegrityError), db.begin_nested():
        setattr(row, prefix + "_json", raw + "a")
        setattr(row, prefix + "_bytes", limit + 1)
        db.flush()


@pytest.mark.parametrize("fault", ["review_hash", "private_hash", "public_hash", "references_hash", "foreign_audit", "actor_role", "size", "counts"])
def test_actual_closed_compound_review_fk_counts_actor_and_exact_bytes(physical, fault):
    db, row = physical
    with pytest.raises(IntegrityError), db.begin_nested():
        if fault in {"review_hash", "private_hash", "public_hash", "references_hash"}:
            setattr(row, fault if fault == "review_hash" else "lesson_" + fault, "f" * 64)
        elif fault == "foreign_audit":
            row.creation_event_id = 2147483647
        elif fault == "actor_role":
            row.actor_role = "patient"
        elif fault == "size":
            row.submission_bytes -= 1
        else:
            row.matching_count += 1
        db.flush()


def test_mysql_compilation_has_two_complete_mediumtext_two_utc6_and_exact_six_field_review_fk():
    sql = str(CreateTable(AITrainingSubmission.__table__).compile(dialect=mysql.dialect()))
    assert sql.count("MEDIUMTEXT") == 2 and sql.count("DATETIME(6)") == 2
    assert "fk_training_submission_exact_review" in sql and "lesson_references_hash" in sql
    assert "length(CAST(submission_json AS BINARY))" in sql and "length(CAST(feedback_json AS BINARY))" in sql
    assert sql.count("REFERENCES hoimsystem_ai_audit_event") == 1


def test_actual_submission_migration_up_down_up_preserves_all_registered_old_ddl_rows_and_gate_seed():
    engine = create_engine("sqlite:///:memory:")
    new_name = AITrainingSubmission.__tablename__
    from app.ai.clinical_training_run_models import TRAINING_RUN_MODELS
    later_names = {model.__tablename__ for model in TRAINING_RUN_MODELS}
    old = MetaData()
    for name, table in Base.metadata.tables.items():
        if name != new_name and name not in later_names:
            table.to_metadata(old)
    old.create_all(engine)
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO hoimsystem_users (user_id,username,password,user_role) VALUES (71001,'synthetic-training-practice-migration','synthetic-only','super_admin')"))
        connection.execute(text("INSERT INTO hoimsystem_ai_training_write_gate (gate_id,revision) VALUES (1,1)"))

    def proof():
        with engine.connect() as connection:
            return {name: (connection.execute(text("SELECT sql FROM sqlite_master WHERE type='table' AND name=:name"), {"name": name}).scalar_one(), connection.execute(text('SELECT * FROM "' + name + '"')).all()) for name in sorted(old.tables)}

    before = proof()
    path = Path(__file__).resolve().parents[1] / "alembic/versions/20261021_clinical_training_practice.py"
    spec = importlib.util.spec_from_file_location("training_practice_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    for step in ("up", "down", "up"):
        with engine.begin() as connection, Operations.context(MigrationContext.configure(connection)):
            migration.downgrade() if step == "down" else migration.upgrade()
        assert proof() == before
        assert (new_name in inspect(engine).get_table_names()) == (step != "down")
    engine.dispose()
