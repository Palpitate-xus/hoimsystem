"""Actual synthetic SQL: whole lineage, explicit review and atomic acceptance."""

import datetime as dt

import pytest
from fastapi import HTTPException
from sqlalchemy import event

from app.ai import document_evidence_contract as c
from app.ai import document_evidence_sources as s
from app.ai.document_evidence_models import AIDocumentKnowledgePublication, AIDocumentOriginal, AIDocumentSpanCandidate
from app.ai.models import AIAuditEvent, AIKnowledgeDocument
from app.models import User
from tests.test_ai_document_evidence_contract import NOTE, NOW, request


def cas(record):
    return dict(expected_revision=record.governance.revision, expected_content_hash=record.content_hash, expected_governance_hash=record.governance_hash)


def review(record, **changes):
    return {**cas(record), "decision": "approve", "privacy_review": "confirmed", "faithfulness_review": "confirmed", "basis_note": NOTE, **changes}


def publish(record):
    return {
        **cas(record),
        "knowledge": {
            "title": "合成引文" + record.snapshot.candidate_id,
            "version": "v1",
            "category": "clinical",
            "feature_keys": ["guideline_ingestion", "guideline_change_review"],
            "department_id": None,
            "effective_from": None,
            "effective_to": None,
        },
        "basis_note": NOTE,
    }


def candidate_request(parent, start=0, end=None):
    end = parent.snapshot.codepoint_length if end is None else end
    return {
        "original": {"original_id": parent.snapshot.original_id, "content_hash": parent.content_hash, "governance_hash": parent.governance_hash},
        "proposed_heading": "待审原文候选",
        "clause_kind": "recommendation",
        "start": start,
        "end": end,
        "quote": parent.snapshot.text[start:end],
        "provenance": "unverified_submission",
    }


@pytest.fixture
def document_case(db_session, seed_data, monkeypatch):
    monkeypatch.setattr(s, "utcnow", lambda: c.clock(NOW))
    ids = [row[0] for row in db_session.query(AIDocumentKnowledgePublication.knowledge_document_id).all()]
    db_session.query(AIDocumentKnowledgePublication).delete(synchronize_session=False)
    db_session.query(AIDocumentSpanCandidate).delete(synchronize_session=False)
    db_session.query(AIDocumentOriginal).delete(synchronize_session=False)
    if ids:
        db_session.query(AIKnowledgeDocument).filter(AIKnowledgeDocument.document_id.in_(ids)).delete(synchronize_session=False)
    db_session.query(AIAuditEvent).filter(AIAuditEvent.action.like("document.%")).delete(synchronize_session=False)
    db_session.commit()
    return db_session, seed_data["super_admin_user"], seed_data


def approved_original(db, actor, text=None):
    row = s.create_original(db, actor, request() if text is None else request(text))
    db.commit()
    result = s.review_original(db, actor, row.snapshot.original_id, review(row))
    db.commit()
    return result


def approved_candidate(db, actor, parent):
    row = s.create_candidate(db, actor, candidate_request(parent))
    db.commit()
    result = s.review_candidate(db, actor, row.snapshot.candidate_id, review(row))
    db.commit()
    return result


def published_chain(case):
    db, actor, _ = case
    original = approved_original(db, actor)
    candidate = approved_candidate(db, actor, original)
    publication = s.publish_candidate(db, actor, candidate.snapshot.candidate_id, publish(candidate))
    db.commit()
    return db, actor, original, candidate, publication, db.get(AIKnowledgeDocument, publication.snapshot.knowledge_document_id)


def test_publication_preserves_actual_microseconds_and_explicit_legacy_knowledge_seconds(document_case):
    db, actor, original, candidate, publication, knowledge = published_chain(document_case)
    assert publication.snapshot.published_at == NOW
    assert publication.snapshot.knowledge_recorded_at == "2026-10-21T12:00:00.000000Z"
    assert publication.snapshot.knowledge_clock_basis == "legacy_utc_second_storage"
    assert knowledge.reviewed_at == knowledge.create_time == c.clock(publication.snapshot.knowledge_recorded_at)
    db.expire_all()
    assert s.publication_detail(db, actor, publication.snapshot.publication_id).eligible
    changed = publication.snapshot.model_dump(mode="json")
    changed["knowledge_recorded_at"] = NOW
    with pytest.raises(ValueError, match="whole-second"):
        c.PublicationImmutable.model_validate(changed)


def test_original_candidate_approval_does_not_auto_publish_and_exact_codepoints(document_case):
    db, actor, _ = document_case
    draft = s.create_original(db, actor, request())
    db.commit()
    assert not draft.eligible and draft.governance.privacy_review == "unknown"
    with pytest.raises(HTTPException):
        s.create_candidate(db, actor, candidate_request(draft))
    original = s.review_original(db, actor, draft.snapshot.original_id, review(draft))
    db.commit()
    candidate = s.create_candidate(db, actor, candidate_request(original, 9, 12))
    db.commit()
    assert candidate.snapshot.proposal.quote == "😀e\u0301"
    with pytest.raises(HTTPException):
        s.publish_candidate(db, actor, candidate.snapshot.candidate_id, publish(candidate))
    candidate = s.review_candidate(db, actor, candidate.snapshot.candidate_id, review(candidate))
    db.commit()
    assert db.query(AIKnowledgeDocument).count() == 0
    publication = s.publish_candidate(db, actor, candidate.snapshot.candidate_id, publish(candidate))
    db.commit()
    knowledge = db.get(AIKnowledgeDocument, publication.snapshot.knowledge_document_id)
    assert publication.eligible and knowledge.content == "😀e\u0301"
    assert knowledge.content_hash == c.digest(knowledge.content) != c.bytes_hash(knowledge.content)
    assert knowledge.source_uri == c.URI_PREFIX + publication.snapshot.publication_id
    assert knowledge.source_kind == "document_span" and knowledge.source_reference_id is None
    assert s.published_bound_source_is_current(db, knowledge)
    assert original.snapshot.text.startswith("\ufeff") and "\r\n" in original.snapshot.text


@pytest.mark.parametrize("axis", ["privacy_review", "faithfulness_review"])
def test_unconfirmed_original_or_candidate_review_is_rejected(document_case, axis):
    db, actor, _ = document_case
    original = s.create_original(db, actor, request())
    db.commit()
    rejected = s.review_original(db, actor, original.snapshot.original_id, review(original, decision="reject", **{axis: "not_confirmed"}))
    db.commit()
    assert rejected.governance.status == "rejected" and not rejected.eligible
    with pytest.raises(HTTPException):
        s.review_original(db, actor, original.snapshot.original_id, review(rejected))
    parent = approved_original(db, actor)
    candidate = s.create_candidate(db, actor, candidate_request(parent))
    db.commit()
    rejected = s.review_candidate(db, actor, candidate.snapshot.candidate_id, review(candidate, decision="reject", **{axis: "not_confirmed"}))
    db.commit()
    with pytest.raises(HTTPException):
        s.publish_candidate(db, actor, candidate.snapshot.candidate_id, publish(rejected))


@pytest.mark.parametrize("mutation", ["quote", "utf16_start", "parent_hash", "parent_gov", "future_recording"])
def test_wrong_quote_coordinates_parent_and_recording_clock_are_not_reanchored(document_case, monkeypatch, mutation):
    db, actor, _ = document_case
    parent = approved_original(db, actor)
    body = candidate_request(parent, 9, 12)
    if mutation == "quote":
        body["quote"] = "😀eX"
    elif mutation == "utf16_start":
        body.update(start=10, end=13)
    elif mutation == "parent_hash":
        body["original"]["content_hash"] = "f" * 64
    elif mutation == "parent_gov":
        body["original"]["governance_hash"] = "f" * 64
    else:
        monkeypatch.setattr(s, "utcnow", lambda: c.clock(NOW) - dt.timedelta(microseconds=1))
    before = db.query(AIDocumentSpanCandidate).count()
    with pytest.raises(HTTPException):
        s.create_candidate(db, actor, body)
    assert db.query(AIDocumentSpanCandidate).count() == before


@pytest.mark.parametrize("parent", ["original", "candidate", "publication"])
def test_revocation_immediately_invalidates_bound_knowledge_but_preserves_full_originals(document_case, parent):
    db, actor, original, candidate, publication, knowledge = published_chain(document_case)
    record = {"original": original, "candidate": candidate, "publication": publication}[parent]
    function = {"original": s.revoke_original, "candidate": s.revoke_candidate, "publication": s.revoke_publication}[parent]
    function(db, actor, getattr(record.snapshot, parent + "_id"), {**cas(record), "basis_note": NOTE})
    db.commit()
    assert not s.published_bound_source_is_current(db, knowledge)
    retained = s.publication_detail(db, actor, publication.snapshot.publication_id)
    assert not retained.eligible and retained.snapshot.quote == original.snapshot.text
    assert s.original_detail(db, actor, original.snapshot.original_id).snapshot.text == original.snapshot.text


@pytest.mark.parametrize(
    "field", ["title", "version", "content", "source_kind", "source_uri", "source_snapshot_hash", "feature_keys_json", "reviewed_at", "reviewed_by", "department_id", "content_hash"]
)
def test_entire_published_knowledge_identity_is_checked_not_only_sha(document_case, field):
    db, actor, original, candidate, publication, knowledge = published_chain(document_case)
    changes = {
        "title": "篡改标题",
        "version": "changed",
        "content": "伪造引文",
        "source_kind": None,
        "source_uri": "synthetic://unbound",
        "source_snapshot_hash": "f" * 64,
        "feature_keys_json": '["clinical_training"]',
        "reviewed_at": c.clock(NOW) + dt.timedelta(microseconds=1),
        "reviewed_by": actor.user_id,
        "department_id": document_case[2]["department"].department_id,
        "content_hash": "e" * 64,
    }
    if field == "reviewed_by":
        changes[field] = document_case[2]["admin_user"].user_id
    db.query(AIKnowledgeDocument).filter_by(document_id=knowledge.document_id).update({field: changes[field]}, synchronize_session=False)
    db.commit()
    assert not s.published_bound_source_is_current(db, knowledge)
    audited = s.publication_detail(db, actor, publication.snapshot.publication_id)
    assert audited.snapshot.quote == original.snapshot.text
    assert getattr(audited.knowledge_current, field) == (c.utc_text(changes[field]) if field == "reviewed_at" else changes[field])


def test_stripping_both_uri_and_kind_does_not_hide_the_publication_fk(document_case):
    db, _, _, _, _, knowledge = published_chain(document_case)
    db.query(AIKnowledgeDocument).filter_by(document_id=knowledge.document_id).update({"source_kind": None, "source_uri": "synthetic://plain-document"}, synchronize_session=False)
    db.commit()
    db.refresh(knowledge)
    assert not s.is_document_bound_source(knowledge) and s.document_binding_exists(db, knowledge)
    assert s.bound_source_state(db, knowledge) == "invalid_binding"


def test_candidate_registration_cannot_predate_actual_original_publication(document_case, monkeypatch):
    db, actor, _ = document_case
    original = s.create_original(db, actor, request())
    db.commit()
    monkeypatch.setattr(s, "utcnow", lambda: c.clock(NOW) + dt.timedelta(hours=1))
    original = s.review_original(db, actor, original.snapshot.original_id, review(original))
    db.commit()
    monkeypatch.setattr(s, "utcnow", lambda: c.clock(NOW) + dt.timedelta(minutes=30))
    with pytest.raises(HTTPException) as denied:
        s.create_candidate(db, actor, candidate_request(original))
    assert denied.value.status_code == 409 and db.query(AIDocumentSpanCandidate).count() == 0


@pytest.mark.parametrize("target", ["original", "candidate", "publication"])
def test_stale_governance_cas_adds_no_audit_or_partial_transition(document_case, target):
    db, actor, original, candidate, publication, _ = published_chain(document_case)
    record = {"original": original, "candidate": candidate, "publication": publication}[target]
    function = {"original": s.revoke_original, "candidate": s.revoke_candidate, "publication": s.revoke_publication}[target]
    before = db.query(AIAuditEvent).count()
    with pytest.raises(HTTPException) as denied:
        function(db, actor, getattr(record.snapshot, target + "_id"), {**cas(record), "expected_governance_hash": "f" * 64, "basis_note": NOTE})
    assert denied.value.status_code == 409 and db.query(AIAuditEvent).count() == before


@pytest.mark.parametrize("phase", ["create", "publish"])
@pytest.mark.parametrize("failure", ["audit", "role", "token", "parent"])
def test_postflush_sql_failures_rollback_source_knowledge_and_audit(document_case, monkeypatch, phase, failure):
    db, actor, _ = document_case
    parent = approved_original(db, actor)
    candidate = approved_candidate(db, actor, parent)
    models = (AIDocumentOriginal, AIDocumentSpanCandidate, AIDocumentKnowledgePublication, AIKnowledgeDocument, AIAuditEvent)
    before = tuple(db.query(m).count() for m in models)
    actual = s.audit

    def fail(session, actor_id, action, target, detail=None):
        actual(session, actor_id, action, target, detail)
        session.flush()
        if failure == "audit":
            raise HTTPException(409, "synthetic SQL audit rejection")
        if failure in {"role", "token"}:
            values = {"user_role": "nurse"} if failure == "role" else {"token_invalid_before": c.clock(NOW)}
            session.query(User).filter_by(user_id=actor_id).update(values, synchronize_session=False)
        else:
            original_id = parent.snapshot.original_id if phase == "publish" else target
            session.query(AIDocumentOriginal).filter_by(original_id=original_id).update({"original_text": "原文被改"}, synchronize_session=False)

    monkeypatch.setattr(s, "audit", fail)
    with pytest.raises(HTTPException):
        if phase == "create":
            s.create_original(db, actor, request())
        else:
            s.publish_candidate(db, actor, candidate.snapshot.candidate_id, publish(candidate))
    assert tuple(db.query(m).count() for m in models) == before
    db.refresh(actor)
    assert actor.user_role == "super_admin" and actor.token_invalid_before is None


def test_duplicate_candidate_publication_and_knowledge_version_are_atomic(document_case):
    db, actor, original, candidate, publication, _ = published_chain(document_case)
    before = db.query(AIAuditEvent).count()
    with pytest.raises(HTTPException):
        s.publish_candidate(db, actor, candidate.snapshot.candidate_id, publish(candidate))
    another = approved_candidate(db, actor, original)
    duplicate = publish(another)
    duplicate["knowledge"] = publication.snapshot.knowledge.model_dump(mode="json")
    with pytest.raises(HTTPException):
        s.publish_candidate(db, actor, another.snapshot.candidate_id, duplicate)
    assert db.query(AIDocumentKnowledgePublication).count() == 1 and db.query(AIKnowledgeDocument).count() == 1
    assert db.query(AIAuditEvent).count() == before + 2


def test_65535_utf8_exact_quote_publishes_and_larger_original_is_not_truncated(document_case):
    db, actor, _ = document_case
    parent = approved_original(db, actor, "汉" * 21845)
    candidate = approved_candidate(db, actor, parent)
    publication = s.publish_candidate(db, actor, candidate.snapshot.candidate_id, publish(candidate))
    db.commit()
    assert len(db.get(AIKnowledgeDocument, publication.snapshot.knowledge_document_id).content.encode()) == 65535
    larger = approved_original(db, actor, "汉" * 21846)
    with pytest.raises(HTTPException):
        s.create_candidate(db, actor, candidate_request(larger))


def test_sql_actor_read_precedes_first_write_and_current_role_rechecked(document_case, monkeypatch):
    db, actor, _ = document_case
    statements = []
    connection = db.connection()

    def collect(conn, cur, sql, parameters, context, many):
        statements.append(sql)

    event.listen(connection, "before_cursor_execute", collect)
    try:
        original = s.create_original(db, actor, request())
    finally:
        event.remove(connection, "before_cursor_execute", collect)
    assert any("hoimsystem_users" in q for q in statements[: next(i for i, q in enumerate(statements) if q.startswith("INSERT"))])
    db.commit()
    actual = s._row

    def after_lock(session, model, key, value, **kwargs):
        row = actual(session, model, key, value, **kwargs)
        session.query(User).filter_by(user_id=actor.user_id).update({"user_role": "doctor"}, synchronize_session=False)
        return row

    monkeypatch.setattr(s, "_row", after_lock)
    with pytest.raises(HTTPException) as denied:
        s.review_original(db, actor, original.snapshot.original_id, review(original))
    assert denied.value.status_code == 403
    db.refresh(actor)
    assert actor.user_role == "super_admin" and db.get(AIDocumentOriginal, original.snapshot.original_id).status == "draft"
