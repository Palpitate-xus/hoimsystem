"""Actual full-root capacity and UTF8 early refusal; no truncated-success fixtures."""

import copy
import datetime

import pytest
from fastapi import HTTPException
from sqlalchemy import event

from app.ai.models import AIReviewExcerpt
from app.ai.satisfaction_models import MAX_BYTES
from app.ai.satisfaction_sources import capture_sources, hash_content, preview_input, verify_capture
from app.models import Review
from tests.test_ai_satisfaction_sources import period, satisfaction_case  # noqa: F401


def test_actual_8192_combined_roots_including_nonwinner_and_8193_refuses(db_session, satisfaction_case):  # noqa: F811
    db, case = db_session, satisfaction_case
    # Existing one Review + one actual published Excerpt; add8190independent rows.
    db.execute(
        Review.__table__.insert(),
        [{"doctor_id": case["doctor"].doctor_id, "score": 1 + i % 5, "comment": None, "review_time": datetime.datetime(2026, 10, 20)} for i in range(8190)],
    )
    db.commit()
    preview = preview_input(db, case["super_admin_user"], period(case))
    assert len(preview["safe_snapshot"]["member_manifest"]) == 8192
    assert len(preview["safe_snapshot"]["reviews"]) == 8191
    assert len(preview["excerpt_options"]) == 1
    assert hash_content(preview["safe_snapshot"]) == preview["safe_projection_hash"]
    db.add(Review(doctor_id=case["doctor"].doctor_id, score=1, review_time=datetime.datetime(2026, 10, 20)))
    db.commit()
    with pytest.raises(HTTPException) as error:
        capture_sources(db, case["super_admin_user"], period(case))
    assert error.value.status_code == 409 and "8192" in error.value.detail


def test_actual_multibyte_text_budget_refuses_before_full_legacy_text_load(db_session, satisfaction_case):  # noqa: F811
    db, case = db_session, satisfaction_case
    identifier = case["excerpt"].excerpt_id
    db.query(AIReviewExcerpt).filter_by(excerpt_id=identifier).update({"redacted_text": "🧪" * (MAX_BYTES // 4)}, synchronize_session=False)
    db.commit()
    statements = []

    def collect(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(db.get_bind(), "before_cursor_execute", collect)
    try:
        with pytest.raises(HTTPException) as error:
            capture_sources(db, case["super_admin_user"], period(case))
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", collect)
    assert error.value.status_code == 409
    assert not any(s.startswith("SELECT hoimsystem_ai_review_excerpt.excerpt_id, hoimsystem_ai_review_excerpt.review_id,") for s in statements)


def test_rehashed_foreign_parent_proof_cannot_become_a_legal_collection(db_session, satisfaction_case):  # noqa: F811
    c = capture_sources(db_session, satisfaction_case["super_admin_user"], period(satisfaction_case))
    altered = copy.deepcopy(c)
    parent = copy.deepcopy(altered["parents"]["patients"][0])
    parent["patient_id"] = 2147483647
    altered["parents"]["patients"].append(parent)
    altered["parents"]["patients"].sort(key=lambda r: r["patient_id"])
    altered["collection_digest"] = hash_content({k: altered[k] for k in ("schema_version", "request", "reviews", "excerpts", "parents")})
    with pytest.raises(HTTPException) as error:
        verify_capture(altered)
    assert error.value.status_code == 409
