"""Synthetic actual SQL/migration/writer boundaries; SQLite is not a locking proof."""

import importlib.util
from io import StringIO
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import HTTPException
from sqlalchemy import CheckConstraint, create_engine, event, inspect, text
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Query

from app.ai import satisfaction_write_guard as guard
from app.ai.models import AIReviewExcerpt
from app.ai.review_curation import create_excerpt, review_excerpt
from app.ai.satisfaction_models import SATISFACTION_MODELS, AISatisfactionWriteGate
from app.ai.schemas import ReviewExcerptReview, ReviewExcerptWrite
from app.database import Base
from app.dependencies import VALID_USER_ROLES
from app.models import Review, User
from app.routers.patient import create_review
from app.schemas import ReviewCreateRequest
from tests.test_ai_review_curation import source_case  # noqa: F401
from tests.test_inpatient_support_migration import snapshot


def module():
    path = Path(__file__).resolve().parents[1] / "alembic/versions/20261021_satisfaction_sources.py"
    spec = importlib.util.spec_from_file_location("isolated_satisfaction_migration", path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def test_additive_up_down_up_preserves_all_old_rows_ddl_and_matches_models(tmp_path):
    tables = {m.__tablename__ for m in SATISFACTION_MODELS}
    engine = create_engine("sqlite:///" + str(tmp_path / "satisfaction.sqlite"))
    Base.metadata.create_all(engine, tables=[t for t in Base.metadata.sorted_tables if t.name not in tables])
    names = set(inspect(engine).get_table_names())
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO hoimsystem_users(user_id,username,user_role) VALUES(90701,'synthetic-review','super_admin')"))
        conn.execute(text("INSERT INTO hoimsystem_review(review_id,score,comment) VALUES(90702,-2,'未伪造成有效满意度')"))
        old = snapshot(conn, names)
    for action in ("upgrade", "downgrade", "upgrade"):
        with engine.begin() as conn, Operations.context(MigrationContext.configure(conn)):
            getattr(module(), action)()
        assert set(inspect(engine).get_table_names()) == names | (tables if action == "upgrade" else set())
        with engine.connect() as conn:
            assert snapshot(conn, names) == old
        if action == "upgrade":
            for model in SATISFACTION_MODELS:
                table = model.__table__
                assert {c["name"]: c["nullable"] for c in inspect(engine).get_columns(table.name)} == {c.name: c.nullable for c in table.columns}
                assert {c["name"]: " ".join(c["sqltext"].split()) for c in inspect(engine).get_check_constraints(table.name)} == {
                    c.name: " ".join(str(c.sqltext).split()) for c in table.constraints if isinstance(c, CheckConstraint)
                }
    engine.dispose()


def test_mysql_ddl_no_autoincrement_singleton_and_explicit_utc6_mediumtext():
    output = StringIO()
    migration = module()
    assert migration.down_revision == "20261021_coding_evidence"
    with Operations.context(MigrationContext.configure(dialect=mysql.dialect(), opts={"as_sql": True, "output_buffer": output})):
        migration.upgrade()
    ddl = output.getvalue()
    assert "AUTO_INCREMENT" not in ddl
    assert ddl.count("DATETIME(6)") == 3 and ddl.count("MEDIUMTEXT") == 2
    assert "8388608" in ddl and "revoke_reason VARCHAR(1000)" in ddl
    sql = str(guard.current_satisfaction_rows(Query(User).filter_by(user_id=1), shared=True).statement.compile(dialect=mysql.dialect()))
    assert sql.endswith("LOCK IN SHARE MODE")


def test_gate_actor_current_expiration_no_autoflush_and_rollback(db_session, seed_data):
    db, actor = db_session, seed_data["super_admin_user"]
    db.query(AISatisfactionWriteGate).delete()
    db.commit()
    db.expire(actor)
    statements = []

    def collect(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(db.get_bind(), "before_cursor_execute", collect)
    try:
        assert guard.lock_satisfaction_write(db, actor, allowed_roles={"super_admin"}) is actor
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", collect)
    reads = [s for s in statements if s.startswith("SELECT")]
    assert "satisfaction_write_gate" in reads[0] and "hoimsystem_users" in reads[1]
    assert len(reads) == 2
    uid = actor.user_id
    db.execute(text("UPDATE hoimsystem_users SET user_role='patient' WHERE user_id=:id"), {"id": uid})
    with pytest.raises(HTTPException) as error:
        guard.lock_satisfaction_write(db, actor, allowed_roles={"super_admin"})
    assert error.value.status_code == 403 and actor.user_role == "patient"
    db.rollback()
    assert db.query(AISatisfactionWriteGate).count() == 0


@pytest.mark.parametrize("writer", ["create", "review"])
def test_curation_gate_first_rechecks_role_before_raw_original_read(db_session, seed_data, source_case, writer):  # noqa: F811
    db, actor = db_session, seed_data["super_admin_user"]
    uid = actor.user_id
    db.execute(text("UPDATE hoimsystem_users SET user_role='admin' WHERE user_id=:id"), {"id": uid})
    count = db.query(AIReviewExcerpt).count()
    with pytest.raises(HTTPException) as error:
        if writer == "create":
            create_excerpt(db, actor, ReviewExcerptWrite(review_id=source_case[0].review_id, expected_source_hash="0" * 64, redacted_text="合成审核摘录", change_note="合成版本依据"))
        else:
            review_excerpt(db, actor, "00000000-0000-0000-0000-000000000001", ReviewExcerptReview(expected_revision=1, status="rejected", review_note="合成拒绝依据"))
    assert error.value.status_code == 403
    assert db.query(AIReviewExcerpt).count() == count
    db.rollback()


def test_legacy_patient_writer_preserves_ownership_and_duplicate_rules(db_session, seed_data):
    db = db_session
    visit, doctor = seed_data["medical_record"], seed_data["doctor"]
    db.query(AIReviewExcerpt).delete()
    db.query(Review).delete()
    db.commit()
    request = ReviewCreateRequest(doctor_id=doctor.doctor_id, visit_id=visit.medical_record_id, score=5, comment="合成评价")
    assert create_review(request, seed_data["patient2_user"], db)["code"] == 403
    assert create_review(request, seed_data["patient_user"], db)["code"] == 200
    assert create_review(request, seed_data["patient_user"], db)["msg"] == "该就诊已评价"
    assert db.query(Review).filter_by(visit_id=visit.medical_record_id).count() == 1
    assert db.query(AISatisfactionWriteGate).count() == 1
    # Authenticated business authorization remains the actual patient/visit match.
    assert guard.lock_satisfaction_write(db, seed_data["admin_user"], allowed_roles=VALID_USER_ROLES).user_role == "admin"
