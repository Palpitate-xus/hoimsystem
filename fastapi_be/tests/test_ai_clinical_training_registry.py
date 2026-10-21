"""Actual audited lesson registration and current source read/rollback boundaries."""

import datetime as dt

import pytest
from fastapi import HTTPException
from sqlalchemy import event, text

from app.ai import clinical_training_contract as c
from app.ai import clinical_training_registry as r
from app.ai.clinical_training_models import AITrainingLesson
from app.ai.models import AIAuditEvent
from tests.test_ai_clinical_training_contract import lesson
from tests.test_ai_clinical_training_reference_sql import reference_case as reference_case


def request(case):
    value = lesson()
    for question, document in zip(value["questions"], case[3], strict=True):
        question["reference_ids"] = [document.document_id]
    return dict(**{key: value[key] for key in ("title", "version_label", "scenario_text", "learning_objectives", "questions")}, synthetic_material_declared=True)


def observe_bodies(db):
    columns = []

    def observer(conn, cursor, statement, params, context, many):
        if statement.lstrip().lower().startswith("select"):
            columns.extend(column[0] for column in cursor.description or [])

    event.listen(db.get_bind(), "after_cursor_execute", observer)
    return columns, observer


def assert_zero_bodies(columns):
    assert not any(name == key or name.endswith("_" + key) for name in columns for key in ("private_json", "public_json", "references_json", "content"))


def test_actual_server_owned_lesson_audit_three_complete_packets_and_original_question_reference_union(reference_case):
    db, actor, reviewer, documents = reference_case
    value = request(reference_case)
    metadata = r.register_lesson(db, actor, value)
    assert metadata["lesson_id"] and metadata["created_by"] == actor.user_id and metadata["creation_event_id"] > 0
    assert metadata["status"] == "active" and metadata["revision"] == 1
    stored = r.get_lesson(db, actor, metadata["lesson_id"], include_body=True)
    assert stored["private"]["scenario_text"].encode() == value["scenario_text"].encode()
    assert stored["private"]["questions"] == value["questions"]
    assert stored["public"] == c.project_lesson(stored["private"]).model_dump()
    assert "correct_option_ids" not in c.whole(stored["public"])
    assert [item["metadata"]["document_id"] for item in stored["references"]["references"]] == sorted(document.document_id for document in documents)
    receipt = db.get(AIAuditEvent, metadata["creation_event_id"])
    assert receipt.action == "training_lesson_create" and receipt.target == metadata["lesson_id"]
    header = r.lesson_header(db, metadata["lesson_id"])
    assert receipt.detail_json == c.canonical_json(r.detail(header, r.ORIGIN_COLUMNS))
    assert "correct_option_ids" not in receipt.detail_json and "PRIVATE_REVIEWED_RATIONALE_SENTINEL" not in receipt.detail_json


@pytest.mark.parametrize("fault", ["requester_role", "requester_epoch", "author_role", "author_epoch", "reference_retired", "reference_epoch", "reference_metadata", "wrong_specific_pk"])
def test_actual_current_authority_or_specific_receipt_change_refuses_before_any_source_body(reference_case, fault):
    db, actor, reviewer, documents = reference_case
    metadata = r.register_lesson(db, actor, request(reference_case))
    # Keep an independently current Super for source-author changes.
    requester = reviewer if fault.startswith("author_") else actor
    if fault in {"requester_role", "author_role"}:
        db.execute(text("UPDATE hoimsystem_users SET user_role='admin' WHERE user_id=:key"), {"key": actor.user_id})
    elif fault in {"requester_epoch", "author_epoch", "reference_epoch"}:
        key = reviewer.user_id if fault == "reference_epoch" else actor.user_id
        db.execute(text("UPDATE hoimsystem_users SET token_invalid_before=:clock WHERE user_id=:key"), {"key": key, "clock": dt.datetime.now(dt.UTC).replace(tzinfo=None)})
    elif fault == "reference_retired":
        documents[0].status = "retired"
        db.flush()
    elif fault == "reference_metadata":
        documents[0].title += " changed"
        db.flush()
    else:
        foreign = AIAuditEvent(actor_id=actor.user_id, action="unrelated_actual_event", target=metadata["lesson_id"], detail_json="{}")
        db.add(foreign)
        db.flush()
        db.execute(text("UPDATE hoimsystem_ai_training_lesson SET creation_event_id=:event WHERE lesson_id=:key"), {"key": metadata["lesson_id"], "event": foreign.event_id})
    columns, observer = observe_bodies(db)
    try:
        with pytest.raises(HTTPException) as error:
            r.get_lesson(db, requester, metadata["lesson_id"], include_body=True)
        assert error.value.status_code in {403, 409}
    finally:
        event.remove(db.get_bind(), "after_cursor_execute", observer)
    assert_zero_bodies(columns)


@pytest.mark.parametrize("fault", ["reference", "author"])
def test_after_actual_lesson_insert_source_mutation_rolls_back_entire_lesson_audit_and_mutation(reference_case, fault):
    db, actor, reviewer, documents = reference_case
    value = request(reference_case)
    document_id, actor_id = documents[0].document_id, actor.user_id
    db.commit()
    before = {model.__tablename__: db.query(model).count() for model in (AITrainingLesson, AIAuditEvent)}
    statement = "UPDATE hoimsystem_ai_knowledge_document SET status='retired' WHERE document_id='" + document_id + "';" if fault == "reference" else "UPDATE hoimsystem_users SET user_role='admin' WHERE user_id=" + str(actor_id) + ";"
    trigger = "training_after_lesson_insert_" + fault
    db.execute(text("CREATE TEMP TRIGGER " + trigger + " AFTER INSERT ON hoimsystem_ai_training_lesson BEGIN " + statement + " END"))
    try:
        with pytest.raises(HTTPException) as error:
            r.register_lesson(db, actor, value)
        assert error.value.status_code in {403, 409}
        assert {model.__tablename__: db.query(model).count() for model in (AITrainingLesson, AIAuditEvent)} == before
        assert db.execute(text("SELECT status FROM hoimsystem_ai_knowledge_document WHERE document_id=:key"), {"key": document_id}).scalar_one() == "published"
        assert db.execute(text("SELECT user_role FROM hoimsystem_users WHERE user_id=:key"), {"key": actor_id}).scalar_one() == "super_admin"
    finally:
        db.execute(text("DROP TRIGGER IF EXISTS " + trigger))
        db.commit()


def test_changed_private_key_with_rehashed_header_still_cannot_replace_concrete_creation_receipt(reference_case):
    db, actor, reviewer, documents = reference_case
    metadata = r.register_lesson(db, actor, request(reference_case))
    row = db.get(AITrainingLesson, metadata["lesson_id"])
    value = c.parse_packet(row.private_json)
    value["questions"][0]["correct_option_ids"] = [value["questions"][0]["options"][1]["option_id"]]
    raw = c.whole(value)
    row.private_json, row.private_hash, row.private_bytes = raw, r.raw_sha(raw), len(raw.encode())
    db.flush()
    columns, observer = observe_bodies(db)
    try:
        with pytest.raises(HTTPException) as error:
            r.get_lesson(db, actor, metadata["lesson_id"], include_body=True)
        assert error.value.status_code == 409
    finally:
        event.remove(db.get_bind(), "after_cursor_execute", observer)
    assert_zero_bodies(columns)
