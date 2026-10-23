"""Adversarial captured-reference data and current SQL actor/Gate prerequisites."""

import copy
import hashlib
import uuid

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import event, text

from app.ai import clinical_training_contract as c
from app.ai import clinical_training_reference_contract as refs
from app.ai import clinical_training_write_guard as guard
from app.ai.clinical_training_models import AITrainingWriteGate


def snapshot():
    content = "\ufeff完整合成参考😀\r\n\x00 尾部  "
    return dict(
        schema_version="clinical_training_reference_snapshot_v1",
        lesson_id=str(uuid.uuid4()),
        captured_by=9,
        captured_at="2026-10-21T20:00:00.123456Z",
        selection_basis="exact_union_of_all_private_question_reference_ids",
        publication_claim="stored_manual_training_publication_and_current_actors_not_independent_content_truth",
        references=[dict(
            metadata=dict(document_id=str(uuid.uuid4()), title="合成参考标题", version="合成版本", source_uri="PRIVATE_ORIGIN_SENTINEL", source_kind=None, source_reference_id=None, source_snapshot_hash=None, category="training", content_hash=c.content_hash(content), feature_keys_json='["clinical_training"]', department_id=None, status="published", effective_from=None, effective_to=None, reviewed_by=8, reviewed_at="2026-10-21T19:00:00.000001Z", created_by=7, create_time="2026-10-21T18:00:00.000001Z"),
            author=dict(user_id=7, user_role="super_admin", token_invalid_before=None),
            reviewer=dict(user_id=8, user_role="super_admin", token_invalid_before="2026-10-21T17:00:00.000001Z"),
            content=content, content_utf8_sha256=hashlib.sha256(content.encode()).hexdigest(),
        )],
    )


def test_full_literal_reference_preserved_and_model_projection_excludes_private_governance():
    value = snapshot()
    parsed = refs.TrainingReferenceSnapshot.model_validate(value, strict=True)
    public = refs.model_projection(parsed)
    assert public["references"][0]["content"].encode() == value["references"][0]["content"].encode()
    assert set(public["references"][0]) == {"document_id", "title", "version", "content", "content_utf8_sha256"}
    assert all(key not in c.canonical_json(public) for key in ["PRIVATE_ORIGIN_SENTINEL", "token_invalid_before", "created_by", "reviewed_by", "captured_by", "feature_keys_json"])
    # A structurally valid snapshot alone still proves no SQL publication or
    # learner/submission authority; the explicit claim remains limited.
    assert parsed.publication_claim.startswith("stored_manual_training_publication")


@pytest.mark.parametrize("field,value", [("category", "clinical"), ("status", "draft"), ("department_id", 1), ("source_kind", "document_evidence"), ("source_reference_id", 1), ("source_snapshot_hash", "1" * 64), ("source_uri", "hoim://document-evidence/x"), ("source_uri", "HOIM://clinical-pathway/1"), ("feature_keys_json", '["patient_summary"]'), ("feature_keys_json", '["clinical_training","clinical_training"]'), ("feature_keys_json", '[1,"clinical_training"]')])
def test_nonmanual_nonglobal_wrong_scope_and_unpublished_references_cannot_be_normalized(field, value):
    packet = snapshot()
    packet["references"][0]["metadata"][field] = value
    with pytest.raises(ValidationError):
        refs.TrainingReferenceSnapshot.model_validate(packet, strict=True)


@pytest.mark.parametrize("fault", ["raw_sha", "knowledge_sha", "content", "author", "reviewer", "actor_role", "future_review", "expired", "future_effective", "duplicate"])
def test_tampered_exact_reference_hashes_actors_clocks_and_duplicate_members_reject_whole_packet(fault):
    packet = snapshot()
    reference = packet["references"][0]
    if fault in {"raw_sha", "knowledge_sha"}:
        if fault == "raw_sha":
            reference["content_utf8_sha256"] = "0" * 64
        else:
            reference["metadata"]["content_hash"] = "0" * 64
    elif fault == "content":
        reference["content"] += " changed"
    elif fault in {"author", "reviewer"}:
        reference[fault]["user_id"] += 100
    elif fault == "actor_role":
        reference["reviewer"]["user_role"] = "admin"
    elif fault == "future_review":
        reference["metadata"]["reviewed_at"] = "2026-10-22T00:00:00.000001Z"
    elif fault == "expired":
        reference["metadata"]["effective_to"] = packet["captured_at"]
    elif fault == "future_effective":
        reference["metadata"]["effective_from"] = "2026-10-22T00:00:00.000001Z"
    else:
        packet["references"].append(copy.deepcopy(reference))
    with pytest.raises(ValidationError):
        refs.TrainingReferenceSnapshot.model_validate(packet, strict=True)


def test_actual_legacy_knowledge_utf8_capacity_includes_nul_and_supplementary_characters():
    packet = snapshot()
    raw = "\x00" + "😀" * 16383 + "ab"
    assert len(raw.encode()) == 65535
    packet["references"][0].update(content=raw, content_utf8_sha256=hashlib.sha256(raw.encode()).hexdigest())
    packet["references"][0]["metadata"]["content_hash"] = c.content_hash(raw)
    refs.TrainingReferenceSnapshot.model_validate(packet, strict=True)
    raw += "a"
    packet["references"][0].update(content=raw, content_utf8_sha256=hashlib.sha256(raw.encode()).hexdigest())
    packet["references"][0]["metadata"]["content_hash"] = c.content_hash(raw)
    with pytest.raises(ValidationError):
        refs.TrainingReferenceSnapshot.model_validate(packet, strict=True)


@pytest.mark.parametrize("fault", ["missing_gate", "role", "epoch"])
def test_real_current_gate_role_and_epoch_prerequisites_refuse_before_any_lesson_or_reference_body(db_session, seed_data, fault):
    db = db_session
    actor = seed_data["super_admin_user"]
    db.rollback()
    db.query(AITrainingWriteGate).delete()
    if fault != "missing_gate":
        db.add(AITrainingWriteGate(gate_id=1, revision=1))
    db.commit()
    assert actor.user_role == "super_admin" and actor.token_invalid_before is None
    if fault != "missing_gate":
        assignment = "user_role='admin'" if fault == "role" else "token_invalid_before='2026-10-21 20:00:00.123456'"
        db.execute(text("UPDATE hoimsystem_users SET " + assignment + " WHERE user_id=:key"), {"key": actor.user_id})
    returned = []

    def observe(conn, cursor, statement, params, context, many):
        if statement.lstrip().lower().startswith("select"):
            returned.extend(column[0] for column in cursor.description or [])

    event.listen(db.get_bind(), "after_cursor_execute", observe)
    try:
        with pytest.raises(HTTPException) as error:
            guard.lock_training_write(db, actor, governance=True)
        assert error.value.status_code == (409 if fault == "missing_gate" else 403)
    finally:
        event.remove(db.get_bind(), "after_cursor_execute", observe)
        db.rollback()
    protected = ["private_json", "public_json", "references_json", "review_json", "content"]
    assert not any(name == key or name.endswith("_" + key) for name in returned for key in protected)
    if fault == "missing_gate":
        assert db.query(AITrainingWriteGate).count() == 0
