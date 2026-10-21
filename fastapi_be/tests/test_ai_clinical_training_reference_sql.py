"""Actual current SQL reference checks; synthetic stored manual publications only."""

import datetime as dt
import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import event, text

from app.ai import clinical_training_contract as c
from app.ai import clinical_training_references as r
from app.ai.clinical_training_models import AITrainingWriteGate
from app.ai.models import AIKnowledgeDocument
from app.models import User
from tests.test_ai_document_evidence_sources import document_case as document_case
from tests.test_ai_document_evidence_sources import published_chain


@pytest.fixture
def reference_case(db_session, seed_data):
    db = db_session
    db.rollback()
    if db.query(AITrainingWriteGate).filter_by(gate_id=1).one_or_none() is None:
        db.add(AITrainingWriteGate(gate_id=1, revision=1))
    actor = seed_data["super_admin_user"]
    reviewer = User(username="training-ref-reviewer-" + uuid.uuid4().hex, password="synthetic-only", user_role="super_admin")
    db.add(reviewer)
    db.flush()
    now = dt.datetime.now(dt.UTC).replace(tzinfo=None)
    content = "\ufeff完整合成培训参考 😀\r\n\x00 尾部  "
    documents = [AIKnowledgeDocument(document_id=str(uuid.uuid4()), title="合成参考" + uuid.uuid4().hex, version="v1", source_uri="manual:synthetic-only", source_kind=None, source_reference_id=None, source_snapshot_hash=None, category="training", content=content + str(i), content_hash=c.content_hash(content + str(i)), feature_keys_json='["clinical_training"]', department_id=None, status="published", effective_from=None, effective_to=None, reviewed_by=reviewer.user_id, reviewed_at=now - dt.timedelta(seconds=1), created_by=actor.user_id, create_time=now - dt.timedelta(seconds=2)) for i in range(2)]
    db.add_all(documents)
    db.flush()
    yield db, actor, reviewer, documents
    db.rollback()


def capture(case):
    db, actor, reviewer, documents = case
    return r.capture_for_author(db, actor, str(uuid.uuid4()), sorted(item.document_id for item in documents))


def body_observer(db):
    columns = []

    def observe(conn, cursor, statement, parameters, context, many):
        if statement.lstrip().lower().startswith("select"):
            columns.extend(column[0] for column in cursor.description or [])

    event.listen(db.get_bind(), "after_cursor_execute", observe)
    return columns, observe


def assert_no_reference_body(columns):
    assert not any(key == "content" or key.endswith("_content") for key in columns)


def test_real_complete_sql_selection_preserves_literal_and_requires_all_current_metadata_first(reference_case):
    db, actor, reviewer, documents = reference_case
    frozen = capture(reference_case)
    assert {item.content for item in frozen.references} == {item.content for item in documents}
    assert all(item.author.user_id == actor.user_id and item.reviewer.user_id == reviewer.user_id for item in frozen.references)
    assert r.verify_current(db, actor.user_id, frozen) == frozen


@pytest.mark.parametrize("fault", ["missing", "draft", "retired", "wrong_feature", "department", "kind", "reference_id", "source_hash", "reserved_uri", "future", "expired", "author_role", "reviewer_role", "too_large"])
def test_one_bad_member_refuses_before_any_selected_reference_content(reference_case, fault):
    db, actor, reviewer, documents = reference_case
    item = documents[-1]
    if fault == "missing":
        identifiers = sorted([documents[0].document_id, str(uuid.uuid4())])
    else:
        identifiers = sorted(row.document_id for row in documents)
        if fault in {"draft", "retired"}:
            item.status = fault
        elif fault == "wrong_feature":
            item.feature_keys_json = '["patient_summary"]'
        elif fault == "department":
            item.department_id = 1
        elif fault == "kind":
            item.source_kind = "clinical_pathway"
        elif fault == "reference_id":
            item.source_reference_id = 1
        elif fault == "source_hash":
            item.source_snapshot_hash = "a" * 64
        elif fault == "reserved_uri":
            item.source_uri = "hoim://document-evidence/erased-markers"
        elif fault == "future":
            item.effective_from = dt.datetime.now(dt.UTC).replace(tzinfo=None) + dt.timedelta(days=1)
        elif fault == "expired":
            item.effective_to = dt.datetime.now(dt.UTC).replace(tzinfo=None) - dt.timedelta(days=1)
        elif fault == "author_role":
            # Keep the requesting Super current; change a selected author.
            item.created_by = reviewer.user_id
            reviewer.user_role = "admin"
        elif fault == "reviewer_role":
            reviewer.user_role = "admin"
        else:
            item.content = "\x00" + "😀" * 16384
            item.content_hash = c.content_hash(item.content)
        db.flush()
    columns, observe = body_observer(db)
    try:
        with pytest.raises(HTTPException) as error:
            r.capture_for_author(db, actor, str(uuid.uuid4()), identifiers)
        assert error.value.status_code in {403, 404, 409}
    finally:
        event.remove(db.get_bind(), "after_cursor_execute", observe)
    assert_no_reference_body(columns)


@pytest.mark.parametrize("fault", ["content_same_hash", "new_content_hash", "metadata", "author_epoch", "reviewer_epoch"])
def test_frozen_reference_does_not_restore_changed_content_metadata_or_epoch(reference_case, fault):
    db, actor, reviewer, documents = reference_case
    frozen = capture(reference_case)
    item = documents[0]
    if fault in {"content_same_hash", "new_content_hash"}:
        item.content += " changed"
        if fault == "new_content_hash":
            item.content_hash = c.content_hash(item.content)
    elif fault == "metadata":
        item.title += " changed"
    else:
        owner = actor if fault == "author_epoch" else reviewer
        db.execute(text("UPDATE hoimsystem_users SET token_invalid_before=:clock WHERE user_id=:key"), {"clock": dt.datetime.now(dt.UTC).replace(tzinfo=None), "key": owner.user_id})
    db.flush()
    columns, observe = body_observer(db)
    try:
        with pytest.raises(HTTPException) as error:
            r.verify_current(db, actor.user_id, frozen)
        assert error.value.status_code == 409
    finally:
        event.remove(db.get_bind(), "after_cursor_execute", observe)
    if fault != "content_same_hash":
        assert_no_reference_body(columns)


def test_whole_literal_content_hash_is_verified_after_current_authority(reference_case):
    db, actor, reviewer, documents = reference_case
    documents[0].content_hash = "0" * 64
    db.flush()
    with pytest.raises(HTTPException) as error:
        capture(reference_case)
    assert error.value.status_code == 409


def test_duplicate_or_noncanonical_selection_is_not_silently_normalized(reference_case):
    db, actor, reviewer, documents = reference_case
    key = documents[0].document_id
    for identifiers in ([key, key], [key.upper()], []):
        with pytest.raises(HTTPException) as error:
            r.capture_for_author(db, actor, str(uuid.uuid4()), identifiers)
        assert error.value.status_code == 409


def test_actual_native_publication_fk_remains_denial_after_all_mutable_markers_are_erased(document_case):
    db, actor, original, candidate, publication, knowledge = published_chain(document_case)
    db.add(AITrainingWriteGate(gate_id=1, revision=1))
    knowledge.source_kind = knowledge.source_reference_id = knowledge.source_snapshot_hash = None
    knowledge.source_uri = "manual:synthetic-erased-markers"
    knowledge.category = "training"
    knowledge.feature_keys_json = '["clinical_training"]'
    db.flush()
    columns, observe = body_observer(db)
    try:
        with pytest.raises(HTTPException) as error:
            r.capture_for_author(db, actor, str(uuid.uuid4()), [knowledge.document_id])
        assert error.value.status_code == 403
    finally:
        event.remove(db.get_bind(), "after_cursor_execute", observe)
        db.rollback()
    assert_no_reference_body(columns)
