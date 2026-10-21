"""Actual synthetic SQL lineage and rollback, not real MySQL lock evidence."""

import datetime as dt

import pytest
from fastapi import HTTPException
from sqlalchemy import event, text
from sqlalchemy.dialects import mysql

from app.ai import document_change_contract as c
from app.ai import document_change_sources as s
from app.ai import document_evidence_sources as originals
from app.ai import risk_rule_profiles
from app.ai.document_change_models import AIDocumentChangeScope, AIDocumentRuleLink
from app.ai.document_change_targets import CaseBudget, target_snapshot
from app.ai.document_evidence_models import AIDocumentKnowledgePublication, AIDocumentOriginal, AIDocumentSpanCandidate
from app.ai.models import AIAuditEvent, AIKnowledgeDocument, AIRiskRuleProfile
from app.models import ClinicalPathway
from tests.test_ai_document_evidence_contract import NOTE, NOW
from tests.test_ai_document_evidence_sources import approved_candidate, approved_original, cas, publish, review


@pytest.fixture
def change_case(db_session, seed_data, monkeypatch):
    db = db_session
    db.query(AIDocumentChangeScope).delete(synchronize_session=False)
    db.query(AIDocumentRuleLink).delete(synchronize_session=False)
    db.query(AIDocumentKnowledgePublication).delete(synchronize_session=False)
    db.query(AIDocumentSpanCandidate).delete(synchronize_session=False)
    db.query(AIDocumentOriginal).delete(synchronize_session=False)
    db.query(AIKnowledgeDocument).delete(synchronize_session=False)
    db.query(AIAuditEvent).filter(AIAuditEvent.action.like("document%")).delete(synchronize_session=False)
    db.query(ClinicalPathway).delete(synchronize_session=False)
    db.commit()
    monkeypatch.setattr(s, "utcnow", lambda: c.e.clock(NOW))
    monkeypatch.setattr(originals, "utcnow", lambda: c.e.clock(NOW))
    actor = seed_data["super_admin_user"]
    first = approved_original(db, actor)
    second = approved_original(db, actor, "\ufeff第二原件\r\n😀原文保持不变")
    pathway = ClinicalPathway(
        name="私有目标标题禁止外发",
        disease_code=None,
        disease_name=None,
        steps='{"raw":"private rule body"}',
        expected_days=0,
        status=0,
        source_revision=1,
        create_time=dt.datetime(2020, 1, 2, 3, 4, 5, 123456),
    )
    db.add(pathway)
    db.commit()
    return db, actor, first, second, pathway, seed_data


def reference(original):
    return s.original_ref(original).model_dump(mode="json")


def target(pathway):
    return c.PathwayReference(kind="clinical_pathway", target_id=pathway.pathway_id)


def link_request(case):
    db, _, first, _, pathway, _ = case
    frozen = target_snapshot(db, target(pathway))
    return {
        "original": reference(first),
        "span": {"start": 0, "end": first.snapshot.codepoint_length, "quote": first.snapshot.text},
        "target": frozen.target.model_dump(mode="json"),
        "expected_target_hash": c.e.digest(frozen),
        "dependency_kind": "declared_implementation",
        "basis_note": NOTE,
        "provenance": "unverified_human_submission",
    }


def scope_request(case, *, declared=True):
    _, _, first, second, pathway, _ = case
    return {
        "baseline_original": reference(first),
        "candidate_original": reference(second),
        "relationship": {"kind": "comparison_only", "same_guideline_family": "unknown", "basis_note": NOTE},
        "declared_targets": [target(pathway).model_dump(mode="json")] if declared else [],
        "rule_link_coverage": "unknown",
        "declaration_basis_note": NOTE,
    }


def change_review(record, **values):
    return {**review(record), "dependency_review": "confirmed", **values}


def draft_scope(case, **values):
    db, actor, *_ = case
    body = {**scope_request(case), **values}
    capture = s.capture_scope(db, actor, body)
    result = s.create_scope(db, actor, {**body, "expected_inventory_hash": capture["inventory_hash"]})
    db.commit()
    return result


def published_scope(case):
    db, actor, *_ = case
    record = draft_scope(case)
    record = s.review_scope(db, actor, record.snapshot.scope_id, change_review(record))
    db.commit()
    return record


def test_actual_link_and_scope_explicit_review_full_projection_and_audit(change_case):
    db, actor, first, _, pathway, _ = change_case
    link = s.create_link(db, actor, link_request(change_case))
    db.commit()
    assert not link.eligible and link.original_current and link.target_current
    link = s.review_link(db, actor, link.snapshot.link_id, change_review(link))
    db.commit()
    assert link.eligible
    candidate = approved_candidate(db, actor, first)
    publication = originals.publish_candidate(db, actor, candidate.snapshot.candidate_id, publish(candidate))
    db.commit()
    scope = published_scope(change_case)
    assert scope.eligible and scope.snapshot.inventory.member_count == 7
    record, public = s.authorize_scope(db, actor, scope.snapshot.scope_id)
    assert record == scope and public.member_count == 7
    assert public.publications[0].publication_id == publication.snapshot.publication_id
    raw = c.e.canonical_json(public)
    assert first.snapshot.text in c.e.canonical_json(public).replace("\\r\\n", "\r\n") or public.baseline.text == first.snapshot.text
    assert pathway.name not in raw and pathway.steps not in raw and NOTE not in raw
    assert public.targets[0].within_declared_scope and public.rule_links[0].current
    assert db.query(AIAuditEvent).filter(AIAuditEvent.action.like("document_change.%")).count() == 4
    assert len({link.audit_event_ids.created, link.audit_event_ids.reviewed, scope.audit_event_ids.created, scope.audit_event_ids.reviewed}) == 4
    assert public.hospital_wide_rule_inventory == "not_provided"


def test_all_links_including_draft_revoked_and_outside_scope_retained(change_case):
    db, actor, *_ = change_case
    draft = s.create_link(db, actor, link_request(change_case))
    db.commit()
    revoked = s.revoke_link(db, actor, draft.snapshot.link_id, {**cas(draft), "basis_note": NOTE})
    db.commit()
    body = scope_request(change_case, declared=False)
    capture = s.capture_scope(db, actor, body)
    inventory = c.Inventory.model_validate(capture["inventory"])
    assert len(inventory.rule_links) == len(inventory.targets) == 1
    assert inventory.rule_links[0] == revoked and not revoked.eligible
    scope = s.create_scope(db, actor, {**body, "expected_inventory_hash": capture["inventory_hash"]})
    db.commit()
    public = s.public_source(scope)
    assert not public.rule_links[0].within_declared_scope and not public.targets[0].within_declared_scope


@pytest.mark.parametrize("mutation", ["target", "new_link", "new_publication", "original", "knowledge"])
def test_all_dependency_changes_invalidate_published_scope(change_case, mutation):
    db, actor, first, _, pathway, _ = change_case
    candidate = approved_candidate(db, actor, first)
    publication = originals.publish_candidate(db, actor, candidate.snapshot.candidate_id, publish(candidate))
    db.commit()
    prior = published_scope(change_case)
    if mutation == "target":
        pathway.steps = '{"updated":true}'
        pathway.source_revision += 1
    elif mutation == "new_link":
        s.create_link(db, actor, link_request(change_case))
    elif mutation == "new_publication":
        second = approved_candidate(db, actor, first)
        originals.publish_candidate(db, actor, second.snapshot.candidate_id, publish(second))
    elif mutation == "original":
        originals.revoke_original(db, actor, first.snapshot.original_id, {**cas(first), "basis_note": NOTE})
    else:
        knowledge = db.get(AIKnowledgeDocument, publication.snapshot.knowledge_document_id)
        knowledge.content += "different"
    db.commit()
    record = s.scope_detail(db, actor, prior.snapshot.scope_id)
    assert not record.inventory_current and not record.eligible
    assert record.snapshot == prior.snapshot
    with pytest.raises(HTTPException) as error:
        s.authorize_scope(db, actor, prior.snapshot.scope_id)
    assert error.value.status_code == 409


def test_capture_cas_includes_new_nonwinner_link(change_case):
    db, actor, *_ = change_case
    body = scope_request(change_case)
    prior = s.capture_scope(db, actor, body)
    s.create_link(db, actor, link_request(change_case))
    db.commit()
    count = db.query(AIAuditEvent).count()
    with pytest.raises(HTTPException) as error:
        s.create_scope(db, actor, {**body, "expected_inventory_hash": prior["inventory_hash"]})
    assert error.value.status_code == 409
    assert db.query(AIDocumentChangeScope).count() == 0 and db.query(AIAuditEvent).count() == count


@pytest.mark.parametrize("which", ["content_hash", "governance_hash", "revision"])
def test_review_exact_cas_and_explicit_dependency_rejection(change_case, which):
    db, actor, *_ = change_case
    draft = draft_scope(change_case)
    body = change_review(draft)
    key = "expected_" + which
    body[key] = body[key] + 1 if which == "revision" else "f" * 64
    with pytest.raises(HTTPException) as error:
        s.review_scope(db, actor, draft.snapshot.scope_id, body)
    assert error.value.status_code == 409
    rejected = s.review_scope(db, actor, draft.snapshot.scope_id, change_review(draft, decision="reject", dependency_review="not_confirmed"))
    db.commit()
    assert rejected.governance.status == "rejected" and not rejected.eligible
    assert rejected.governance.faithfulness_review == "confirmed"


@pytest.mark.parametrize("kind", ["link", "scope"])
def test_actual_sql_audit_failure_rolls_back_all_source_and_audit(change_case, kind):
    db, actor, *_ = change_case
    body = link_request(change_case) if kind == "link" else scope_request(change_case)
    if kind == "scope":
        body["expected_inventory_hash"] = s.capture_scope(db, actor, body)["inventory_hash"]
    count = db.query(AIAuditEvent).count()
    db.execute(
        text(
            "CREATE TEMP TRIGGER reject_change_audit BEFORE INSERT ON hoimsystem_ai_audit_event WHEN NEW.action LIKE 'document_change.%' BEGIN SELECT RAISE(ABORT, 'actual synthetic SQL rejection'); END"
        )
    )
    db.commit()
    try:
        with pytest.raises(HTTPException):
            (s.create_link if kind == "link" else s.create_scope)(db, actor, body)
        assert db.query(AIAuditEvent).count() == count
        assert db.query(AIDocumentRuleLink).count() == db.query(AIDocumentChangeScope).count() == 0
    finally:
        db.execute(text("DROP TRIGGER reject_change_audit"))
        db.commit()


@pytest.mark.parametrize("kind", ["link", "scope"])
def test_postflush_parent_mutation_is_atomic_rejected(change_case, kind):
    db, actor, _, _, pathway, _ = change_case
    body = link_request(change_case) if kind == "link" else scope_request(change_case)
    if kind == "scope":
        body["expected_inventory_hash"] = s.capture_scope(db, actor, body)["inventory_hash"]
    count = db.query(AIAuditEvent).count()
    model = AIDocumentRuleLink if kind == "link" else AIDocumentChangeScope

    def changed(mapper, connection, row):
        connection.execute(ClinicalPathway.__table__.update().where(ClinicalPathway.pathway_id == pathway.pathway_id).values(status=1, source_revision=2))

    event.listen(model, "after_insert", changed)
    try:
        with pytest.raises(HTTPException):
            (s.create_link if kind == "link" else s.create_scope)(db, actor, body)
    finally:
        event.remove(model, "after_insert", changed)
    assert db.query(AIAuditEvent).count() == count
    assert db.query(AIDocumentRuleLink).count() == db.query(AIDocumentChangeScope).count() == 0
    assert db.get(ClinicalPathway, pathway.pathway_id).status == 0


def test_scope_revoke_preserves_frozen_public_and_current_exact_audit_pk(change_case):
    db, actor, *_ = change_case
    record = published_scope(change_case)
    revoked = s.revoke_scope(db, actor, record.snapshot.scope_id, {**cas(record), "basis_note": NOTE})
    db.commit()
    assert revoked.snapshot == record.snapshot and revoked.inventory_current and not revoked.eligible
    assert revoked.governance.revision == 3 and revoked.audit_event_ids.revoked
    event_row = db.get(AIAuditEvent, revoked.audit_event_ids.created)
    event_row.detail_json = "{}"
    db.commit()
    with pytest.raises(HTTPException):
        s.scope_detail(db, actor, record.snapshot.scope_id)


def test_current_actor_rechecked_after_actual_sql_flush(change_case):
    db, actor, *_ = change_case

    def changed(mapper, connection, row):
        from app.models import User

        connection.execute(User.__table__.update().where(User.user_id == actor.user_id).values(user_role="doctor"))

    event.listen(AIDocumentRuleLink, "after_insert", changed)
    try:
        with pytest.raises(HTTPException) as error:
            s.create_link(db, actor, link_request(change_case))
        assert error.value.status_code == 403
    finally:
        event.remove(AIDocumentRuleLink, "after_insert", changed)
    assert db.query(AIDocumentRuleLink).count() == 0


def test_target_native_zero_null_and_naive_clock_retained_and_oversize_refused(change_case):
    db, _, _, _, pathway, _ = change_case
    value = target_snapshot(db, target(pathway))
    assert value.columns["expected_days"] == 0 and value.columns["disease_code"] is None
    assert value.columns["create_time"] == "2020-01-02 03:04:05.123456"
    with pytest.raises(ValueError):
        target_snapshot(db, target(pathway), CaseBudget(maximum=20, reserve=0))


def test_profile_locking_adapter_calls_real_helper_current_and_default_preserved(change_case):
    db, actor, *_ = change_case
    option = risk_rule_profiles.fixed_options()[0]
    row = risk_rule_profiles.create_profile(
        db,
        actor,
        {
            "name": "合成固定规则",
            "rule_id": option["rule_id"],
            "expected_recipe_digest": option["recipe_digest"],
            "evidence_reference": "合成明确实施来源",
            "rationale": "这是合成固定规则的明确实施审核依据，不构成临床验证结果。",
        },
    )
    db.commit()
    sql = []

    def reads(state):
        if AIRiskRuleProfile.__tablename__ in str(state.statement):
            sql.append(str(state.statement.compile(dialect=mysql.dialect())))

    event.listen(db, "do_orm_execute", reads)
    try:
        assert risk_rule_profiles.profile_detail(db, row)["status"] == "draft"
        assert not any("LOCK IN SHARE MODE" in value for value in sql)
        sql.clear()
        value = target_snapshot(db, c.RiskProfileReference(kind="risk_rule_profile", target_id=row.rule_profile_id))
        assert value.state == "inactive"
        assert len(sql) == 3 and all("LOCK IN SHARE MODE" in value for value in sql)
    finally:
        event.remove(db, "do_orm_execute", reads)


def test_target_deleted_is_retained_missing_in_current_set_and_frozen_audit_survives(change_case):
    db, actor, _, _, pathway, _ = change_case
    link = s.create_link(db, actor, link_request(change_case))
    db.commit()
    prior = published_scope(change_case)
    db.delete(pathway)
    db.commit()
    current = s.scope_detail(db, actor, prior.snapshot.scope_id)
    assert not current.inventory_current and current.snapshot == prior.snapshot
    assert s.link_detail(db, actor, link.snapshot.link_id).ineligibility_reasons == ["link_not_published", "target_changed"]
    with pytest.raises(HTTPException):
        s.capture_scope(db, actor, scope_request(change_case))


def test_actual_600_complete_link_sql_scope_publish_and_stored_read_use_same_budget(change_case):
    db, actor, *_ = change_case
    request = link_request(change_case)
    for _ in range(600):
        s.create_link(db, actor, request)
    db.commit()
    body = scope_request(change_case)
    capture = s.capture_scope(db, actor, body)
    assert capture["member_count"] == 603
    draft = s.create_scope(db, actor, {**body, "expected_inventory_hash": capture["inventory_hash"]})
    db.commit()
    row = db.get(AIDocumentChangeScope, draft.snapshot.scope_id)
    assert 65535 < len(row.scope_json.encode()) < c.MAX_CASE_BYTES
    # The inherited single-original parser cannot read this valid larger Case;
    # the independent comparison parser is required on both write and read.
    with pytest.raises(ValueError, match="structural budget"):
        c.e.parse_json(row.scope_json)
    published = s.review_scope(db, actor, draft.snapshot.scope_id, change_review(draft))
    db.commit()
    db.expire_all()
    read = s.scope_detail(db, actor, draft.snapshot.scope_id)
    assert read == published and read.eligible
    assert len(read.snapshot.inventory.rule_links) == 600
    assert s.authorize_scope(db, actor, draft.snapshot.scope_id)[1].member_count == 603
