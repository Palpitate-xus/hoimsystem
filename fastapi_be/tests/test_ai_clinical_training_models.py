"""Real additive DDL/UTF8 constraints, not a publication or learner access proof."""

import datetime as dt
import hashlib
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

from app.ai import clinical_training_contract as c
from app.ai.clinical_training_models import TRAINING_SOURCE_MODELS, AITrainingLesson, AITrainingReview
from app.ai.models import AIAuditEvent
from app.database import Base
from app.models import User
from tests.test_ai_clinical_training_contract import lesson


@pytest.fixture
def physical(db_session, seed_data):
    db = db_session
    db.commit()
    prior = db.execute(text("PRAGMA foreign_keys")).scalar_one()
    db.execute(text("PRAGMA foreign_keys=ON"))
    actor = db.query(User).filter_by(username="super01").one()
    identifier = str(uuid.uuid4())
    when = dt.datetime(2026, 10, 21, 20, 0, 0, 123456)
    private = {**lesson(), "lesson_id": identifier, "created_by": actor.user_id, "created_at": when.strftime("%Y-%m-%dT%H:%M:%S.%fZ")}
    private_json = c.whole(private)
    public_json = c.whole(c.project_lesson(private))
    references_json = c.whole({"schema_version": "synthetic_physical_fixture_only_not_actual_references", "refs": [q["reference_ids"] for q in private["questions"]]})
    audit = AIAuditEvent(actor_id=actor.user_id, action="training.physical.fixture.only", target=identifier, detail_json="{}", create_time=when.replace(microsecond=0))
    db.add(audit)
    db.flush()
    ids_json = c.canonical_json(sorted({key for question in private["questions"] for key in question["reference_ids"]}))
    row = AITrainingLesson(lesson_id=identifier, schema_version="clinical_training_private_lesson_v1", title=private["title"], version_label=private["version_label"], reference_ids_json=ids_json, reference_ids_hash=hashlib.sha256(ids_json.encode()).hexdigest(), reference_ids_bytes=len(ids_json.encode()), reference_state_hash="0" * 64, created_by=actor.user_id, author_role="super_admin", author_epoch=None, created_at=when, creation_event_id=audit.event_id, status="active", revision=1, revoke_reason="", **{key: value for prefix, value in [("private", private_json), ("public", public_json), ("references", references_json)] for key, value in [(prefix + "_json", value), (prefix + "_hash", hashlib.sha256(value.encode()).hexdigest()), (prefix + "_bytes", len(value.encode()))]})
    db.add(row)
    db.flush()
    yield db, row, actor, when
    db.rollback()
    db.execute(text("PRAGMA foreign_keys=" + str(prior)))
    db.commit()


@pytest.mark.parametrize("prefix", ["private", "public", "references"])
def test_actual_utf8_nul_full8mib_and_plus_one_without_codepoint_counting(physical, prefix):
    db, row, actor, when = physical
    raw = "\x00" + "😀" * ((8388608 - 4) // 4) + "尾"
    assert len(raw.encode()) == 8388608
    with db.begin_nested() as savepoint:
        setattr(row, prefix + "_json", raw)
        setattr(row, prefix + "_bytes", 8388608)
        db.flush()
        assert db.execute(text("SELECT length(CAST(" + prefix + "_json AS BLOB)) FROM hoimsystem_ai_training_lesson WHERE lesson_id=:key"), {"key": row.lesson_id}).scalar_one() == 8388608
        savepoint.rollback()
    with pytest.raises(IntegrityError), db.begin_nested():
        setattr(row, prefix + "_json", raw + "a")
        setattr(row, prefix + "_bytes", 8388609)
        db.flush()


@pytest.mark.parametrize("fault", ["size", "fake_publication", "revision", "author_role", "audit_reuse"])
def test_actual_invalid_physical_headers_are_rejected(physical, fault):
    db, row, actor, when = physical
    with pytest.raises(IntegrityError), db.begin_nested():
        if fault == "size":
            row.private_bytes -= 1
        elif fault == "fake_publication":
            row.status = "published"
        elif fault == "revision":
            row.revision = 2
        elif fault == "author_role":
            row.author_role = "admin"
        else:
            row.status, row.revision, row.revoked_by, row.revoked_at, row.revoke_reason, row.revocation_event_id = "revoked", 2, actor.user_id, when, "实际撤回", row.creation_event_id
        db.flush()


def test_review_compound_lesson_identity_and_independent_flags_are_physical_constraints(physical):
    db, lesson_row, actor, when = physical
    audit = AIAuditEvent(actor_id=actor.user_id, action="training.physical.review.only", target=lesson_row.lesson_id, detail_json="{}")
    db.add(audit)
    db.flush()
    values = dict(review_id=str(uuid.uuid4()), lesson_id=lesson_row.lesson_id, lesson_private_hash=lesson_row.private_hash, lesson_public_hash=lesson_row.public_hash, lesson_references_hash=lesson_row.references_hash, review_json="{}", review_hash="0" * 64, reviewed_by=actor.user_id, reviewer_role="super_admin", reviewer_epoch=None, reviewed_at=when, synthetic_material_checked=1, answer_key_checked=1, reference_applicability_checked=1, model_processing_allowed=0, creation_event_id=audit.event_id, status="published", revision=1, revoke_reason="")
    for change in [dict(lesson_private_hash="f" * 64), dict(answer_key_checked=0), dict(model_processing_allowed=2), dict(status="rejected", model_processing_allowed=1)]:
        with pytest.raises(IntegrityError), db.begin_nested():
            db.add(AITrainingReview(**{**values, **change}))
            db.flush()
    db.add(AITrainingReview(**values))
    db.flush()
    assert db.query(AITrainingReview).filter_by(review_id=values["review_id"]).one().reviewed_at.microsecond == 123456


def test_mysql_compilation_has_complete_mediumtext_utf8_checks_six_utc6_and_concrete_audit_fks():
    sql = "\n".join(str(CreateTable(model.__table__).compile(dialect=mysql.dialect())) for model in TRAINING_SOURCE_MODELS)
    assert sql.count("MEDIUMTEXT") == 4 and sql.count("DATETIME(6)") == 6
    assert "length(CAST(private_json AS BINARY))" in sql and "fk_training_review_exact_lesson" in sql
    assert sql.count("REFERENCES hoimsystem_ai_audit_event") == 4


def test_actual_additive_sqlite_migration_up_down_up_keeps_all_old_ddl_and_rows():
    engine = create_engine("sqlite:///:memory:")
    new_names = {model.__tablename__ for model in TRAINING_SOURCE_MODELS}
    old = MetaData()
    for name, table in Base.metadata.tables.items():
        if name not in new_names:
            table.to_metadata(old)
    old.create_all(engine)
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO hoimsystem_users (user_id,username,password,user_role) VALUES (70001,'synthetic-training-migration','synthetic-only','super_admin')"))
    def proof():
        with engine.connect() as connection:
            return {name: (connection.execute(text("SELECT sql FROM sqlite_master WHERE type='table' AND name=:name"), {"name": name}).scalar_one(), connection.execute(text('SELECT * FROM "' + name + '"')).all()) for name in sorted(old.tables)}
    before = proof()
    path = Path(__file__).resolve().parents[1] / "alembic/versions/20261021_clinical_training_sources.py"
    spec = importlib.util.spec_from_file_location("training_source_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    for step in ("up", "down", "up"):
        with engine.begin() as connection, Operations.context(MigrationContext.configure(connection)):
            migration.downgrade() if step == "down" else migration.upgrade()
        assert proof() == before
        assert new_names.isdisjoint(inspect(engine).get_table_names()) if step == "down" else new_names.issubset(inspect(engine).get_table_names())
    engine.dispose()
