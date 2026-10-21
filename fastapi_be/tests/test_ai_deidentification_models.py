"""Actual SQL storage boundaries and MySQL compilation, not MySQL execution."""

import datetime as dt
import uuid

import pytest
from sqlalchemy import ForeignKeyConstraint, text
from sqlalchemy.dialects import mysql
from sqlalchemy.exc import IntegrityError
from sqlalchemy.schema import CreateTable

from app.ai.deidentification_models import DEIDENTIFICATION_MODELS, AIDeidentificationCase, AIDeidentificationExportRelease, AIDeidentificationReview
from tests.test_ai_research_cohort_models import draft, scope_row


@pytest.fixture(autouse=True)
def actual_fk_enforcement(db_session):
    previous = db_session.execute(text("PRAGMA foreign_keys")).scalar_one()
    db_session.execute(text("PRAGMA foreign_keys=ON"))
    assert db_session.execute(text("PRAGMA foreign_keys")).scalar_one() == 1
    try:
        yield
    finally:
        db_session.rollback()
        db_session.execute(text("PRAGMA foreign_keys=" + str(previous)))
        db_session.commit()


def test_actual_three_tables_compile_explicit_clock_json_and_real_foreign_keys():
    ddls = [str(CreateTable(m.__table__).compile(dialect=mysql.dialect())) for m in DEIDENTIFICATION_MODELS]
    assert sum(d.count("DATETIME(6)") for d in ddls) == 14
    assert sum(d.count("MEDIUMTEXT") for d in ddls) == 5
    assert sum(isinstance(c, ForeignKeyConstraint) for m in DEIDENTIFICATION_MODELS for c in m.__table__.constraints) == 16
    assert all(len(c.name or "") <= 64 for m in DEIDENTIFICATION_MODELS for c in m.__table__.constraints)
    assert all("REGEXP" not in ddl and "AUTO_INCREMENT" not in ddl for ddl in ddls)


def original_case(db, seed_data):
    scope = scope_row(seed_data["admin_user"].user_id)
    db.add(scope)
    db.flush()
    row = AIDeidentificationCase(
        case_id=str(uuid.uuid4()),
        scope_id=scope.scope_id,
        patient_id=seed_data["patient"].patient_id,
        schema_version="deidentification_case_v1",
        snapshot_json="{}",
        content_hash="a" * 64,
        collection_digest="b" * 64,
        parent_binding_hash="c" * 64,
        manifest_hash="d" * 64,
        **draft(seed_data["admin_user"].user_id),
    )
    db.add(row)
    db.flush()
    return row


@pytest.mark.parametrize("kind", ["positive_null_actor", "self", "missing_json"])
def test_review_independent_manual_tuple_has_no_sql_null_acceptance_hole(db_session, seed_data, kind):
    db, creator = db_session, seed_data["admin_user"].user_id
    row = original_case(db, seed_data)
    review = AIDeidentificationReview(
        review_id=str(uuid.uuid4()),
        case_id=row.case_id,
        schema_version="deidentification_review_v1",
        review_json="{}",
        content_hash="e" * 64,
        output_json="{}",
        output_hash="f" * 64,
        output_bytes=2,
        manual_status="reviewed_residual_risk_remains",
        manual_reviewed_by=None if kind == "positive_null_actor" else creator if kind == "self" else seed_data["director_user"].user_id,
        manual_reviewed_at=row.created_at + dt.timedelta(seconds=1),
        manual_review_json=None if kind == "missing_json" else "{}",
        **draft(creator),
    )
    db.add(review)
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


def test_release_download_counter_requires_actual_specific_audit_and_clock_tuple(db_session, seed_data):
    db, creator = db_session, seed_data["admin_user"].user_id
    case = original_case(db, seed_data)
    review = AIDeidentificationReview(
        review_id=str(uuid.uuid4()),
        case_id=case.case_id,
        schema_version="deidentification_review_v1",
        review_json="{}",
        content_hash="e" * 64,
        output_json="{}",
        output_hash="f" * 64,
        output_bytes=2,
        manual_status="unknown",
        manual_reviewed_by=None,
        manual_reviewed_at=None,
        manual_review_json=None,
        **draft(creator),
    )
    db.add(review)
    db.flush()
    release = AIDeidentificationExportRelease(
        release_id=str(uuid.uuid4()),
        review_id=review.review_id,
        schema_version="deidentification_release_v1",
        release_json="{}",
        content_hash="e" * 64,
        artifact_json="{}",
        artifact_hash="f" * 64,
        artifact_bytes=2,
        valid_from=None,
        valid_until=None,
        maximum_downloads=1,
        download_count=1,
        last_download_event_id=None,
        last_download_at=None,
        manual_status="unknown",
        manual_reviewed_by=None,
        manual_reviewed_at=None,
        manual_review_json=None,
        **draft(creator),
    )
    db.add(release)
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


def test_storage_exact_utf8_cap_refuses_whole_oversize_without_truncating(db_session, seed_data):
    db = db_session
    row = original_case(db, seed_data)
    raw = '{"text":"' + "汉" * 2796199 + '"}'
    assert len(raw.encode("utf-8")) == 8388608
    row.snapshot_json = raw
    db.commit()
    db.refresh(row)
    assert row.snapshot_json == raw
    row.snapshot_json = raw[:-1] + " }"
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


@pytest.mark.parametrize("foreign", ["scope_id", "patient_id"])
def test_actual_missing_scope_or_patient_fk_is_rejected(db_session, seed_data, foreign):
    db = db_session
    row = original_case(db, seed_data)
    setattr(row, foreign, str(uuid.uuid4()) if foreign == "scope_id" else 2147483647)
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()
