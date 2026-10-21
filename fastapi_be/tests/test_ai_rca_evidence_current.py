"""Actual same-transaction Root closure and savepoint rollback; no MySQL claim."""

import pytest
from fastapi import HTTPException
from sqlalchemy import Select, event, inspect

from app.ai import rca_evidence_cases as k
from app.ai import rca_evidence_current as current
from app.ai import rca_evidence_directory as d
from app.ai import rca_evidence_grants as g
from app.ai import rca_evidence_sources as s
from app.ai.rca_evidence_models import AIRcaEvidenceOriginal
from tests.test_ai_rca_evidence_cases import NOTE
from tests.test_ai_rca_evidence_grants import body as grant_body
from tests.test_ai_rca_evidence_grants import both
from tests.test_ai_rca_evidence_grants import grant_case as grant_case
from tests.test_ai_rca_evidence_sources import body


def uncommitted_original(case):
    return s.create_original(case["db"], case["actor"], body(case))


def ids(case):
    return [member.record.immutable.original_id for member in k.capture_event(case["db"], case["actor"], case["event_id"]).originals]


def test_actual_writer_staged_grants_original_case_visible_before_commit_and_roll_back_together(grant_case):
    case, db = grant_case, grant_case["db"]
    for kind in ("event_investigation", "associated_patient_processing"):
        g.create_grant(db, case["actor"], grant_body(case, kind))
    original = uncommitted_original(case)
    assert ids(case) == [original.immutable.original_id]
    capture = k.capture_event(db, case["actor"], case["event_id"])
    created = k.create_case(db, case["actor"], {"event_id": case["event_id"], "expected_event_patient_id": case["patient_id"], "expected_collection_hash": capture.collection_hash, "basis_note": NOTE})
    assert d.directory(db, case["actor"], case["event_id"], "cases").items[0].case_id == created.immutable.case_id
    db.rollback()
    assert current._KEY not in db.info
    with pytest.raises(HTTPException) as error:
        k.capture_event(db, case["actor"], case["event_id"])
    assert error.value.status_code == 403
    assert db.query(AIRcaEvidenceOriginal).filter_by(event_id=case["event_id"]).count() == 0


def test_real_savepoint_rollback_does_not_leave_phantom_source_hint(grant_case):
    case, db = grant_case, grant_case["db"]
    both(case)
    savepoint = db.begin_nested()
    original = uncommitted_original(case)
    assert ids(case) == [original.immutable.original_id]
    savepoint.rollback()
    assert ids(case) == []
    assert db.query(AIRcaEvidenceOriginal).filter_by(event_id=case["event_id"]).count() == 0


def test_savepoint_commit_retains_real_own_root_until_outer_commit_then_registry_clears(grant_case):
    case, db = grant_case, grant_case["db"]
    both(case)
    with db.begin_nested():
        original = uncommitted_original(case)
    assert ids(case) == [original.immutable.original_id]
    db.commit()
    assert current._KEY not in db.info
    assert ids(case) == [original.immutable.original_id]


def test_rollback_nested_review_does_not_erase_outer_created_root_hint(grant_case):
    case, db = grant_case, grant_case["db"]
    both(case)
    original = uncommitted_original(case)
    nested = db.begin_nested()
    from tests.test_ai_rca_evidence_http import published_review

    s.review_original(db, case["actor"], original.immutable.original_id, published_review(original))
    nested.rollback()
    assert ids(case) == [original.immutable.original_id]
    assert s.original_detail(db, case["actor"], original.immutable.original_id).governance.status == "draft"
    db.rollback()
    assert current._KEY not in db.info


def test_only_real_flushed_same_session_rows_can_register_own_keys(grant_case):
    case, db = grant_case, grant_case["db"]
    with pytest.raises(ValueError):
        current.remember_flushed(db, AIRcaEvidenceOriginal(original_id="00000000-0000-0000-0000-000000000001", event_id=case["event_id"]))
    both(case)
    original = uncommitted_original(case)
    row = db.get(AIRcaEvidenceOriginal, original.immutable.original_id)
    db.expunge(row)
    assert inspect(row).detached
    with pytest.raises(ValueError):
        current.remember_flushed(db, row)


def test_discovery_selects_only_two_opaque_columns_without_lock_or_body_and_metadata_is_pk_current(grant_case):
    case, db = grant_case, grant_case["db"]
    both(case)
    original = uncommitted_original(case)
    statements = []

    def observe(state):
        if state.is_select and isinstance(state.statement, Select):
            statements.append(state.statement)

    event.listen(db, "do_orm_execute", observe)
    try:
        identifiers = current.discover(db, AIRcaEvidenceOriginal, "original_id", case["event_id"])
    finally:
        event.remove(db, "do_orm_execute", observe)
    assert identifiers == [original.immutable.original_id]
    assert len(statements) == 1 and [col.key for col in statements[0].selected_columns] == ["original_id", "event_id"]
    assert statements[0]._for_update_arg is None
    with pytest.raises(HTTPException) as error:
        current.current_metadata(db, AIRcaEvidenceOriginal, "original_id", original.immutable.original_id, case["event_id"] + 1, (AIRcaEvidenceOriginal.original_id, AIRcaEvidenceOriginal.event_id))
    assert error.value.status_code == 409
