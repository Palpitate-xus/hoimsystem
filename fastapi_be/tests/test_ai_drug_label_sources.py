"""Synthetic real SQL release/signature/currentness and atomic action acceptance."""

import copy

import pytest
from fastapi import HTTPException
from sqlalchemy import text

from app.ai import document_evidence_contract as d
from app.ai import document_evidence_sources as documents
from app.ai import drug_label_contract as c
from app.ai import drug_label_sources as s
from app.ai.drug_label_models import AIDrugLabelProfessionalReview, AIDrugLabelSource
from app.ai.models import AIAuditEvent
from app.models import Pharmaceutical, User
from tests.test_ai_document_evidence_contract import NOW
from tests.test_ai_document_evidence_contract import request as original_request
from tests.test_ai_document_evidence_sources import review as original_review

NOTE = "已逐字阅读本次完整说明书原文及目录身份，保留临床含义与官方覆盖未知。"


def cas(value):
    return dict(expected_revision=value.governance.revision, expected_content_hash=value.content_hash, expected_governance_hash=value.governance_hash)


@pytest.fixture
def label_case(db_session, seed_data, monkeypatch):
    monkeypatch.setattr(documents, "utcnow", lambda: d.clock(NOW))
    monkeypatch.setattr(s, "utcnow", lambda: d.clock(NOW))
    db = db_session
    sku = Pharmaceutical(name="合成药品73", barcode=None, stock=5, status=0)
    db.add(sku)
    db.commit()
    body = original_request("\ufeff成分：合成成分。\r\n规格：未提供。😀e\u0301\n2026-10-21T12:00:00.123456Z")
    body["metadata"]["document_kind"] = "drug_label"
    original = documents.create_original(db, seed_data["super_admin_user"], body)
    db.commit()
    original = documents.review_original(db, seed_data["super_admin_user"], original.snapshot.original_id, original_review(original))
    db.commit()
    return db, seed_data, sku, original


def create(label_case):
    db, users, sku, original = label_case
    value = s.create_source(
        db,
        users["super_admin_user"],
        dict(
            pharmaceutical_id=sku.pharmaceutical_id,
            expected_identity_hash=d.digest(s.identity(sku)),
            original=dict(original_id=original.snapshot.original_id, content_hash=original.content_hash, governance_hash=original.governance_hash),
            basis_note=NOTE,
        ),
    )
    db.commit()
    return value


def sign(label_case, value, **changes):
    db, users, _, _ = label_case
    value = s.sign_source(
        db, users["pharmacist_user"], value.snapshot.source_binding_id, dict(**cas(value), catalog_match_review="confirmed", provided_text_version_review="confirmed", basis_note=NOTE, **changes)
    )
    db.commit()
    return value


def publish(label_case):
    db, users, _, _ = label_case
    value = sign(label_case, create(label_case))
    review = value.professional_review
    value = s.review_source(
        db,
        users["super_admin_user"],
        value.snapshot.source_binding_id,
        dict(
            **cas(value),
            decision="approve",
            professional=dict(professional_review_id=review.snapshot.professional_review_id, content_hash=review.content_hash, governance_hash=review.governance_hash),
            basis_note=NOTE,
        ),
    )
    db.commit()
    return value


def test_release_signature_and_technical_publication_are_distinct(label_case):
    db, users, _, original = label_case
    value = create(label_case)
    assert not value.eligible and not value.signer_current
    assert not value.can_sign and value.can_review
    pharm = s.source_current(db, users["pharmacist_user"], value.snapshot.source_binding_id)
    assert pharm.can_sign and not pharm.can_review
    assert pharm.snapshot.original.snapshot.text == original.snapshot.text
    assert pharm.snapshot.original.snapshot.raw_bytes_hash == d.bytes_hash(original.snapshot.text)
    with pytest.raises(HTTPException) as denied:
        documents.original_detail(db, users["pharmacist_user"], original.snapshot.original_id)
    assert denied.value.status_code == 403
    db.rollback()
    signed = sign(label_case, value)
    assert not signed.eligible and signed.signer_current and not signed.can_sign
    assert signed.professional_review.snapshot.signed_by == users["pharmacist_user"].user_id
    assert signed.clinical_validation == signed.licensure_verification == "not_provided"
    assert not db.query(AIDrugLabelSource).filter_by(status="published").count()


def test_full_published_source_raw_unicode_current_and_explicit_frozen_audit(label_case):
    db, users, _, _ = label_case
    value = publish(label_case)
    assert value.eligible
    assert s.verify_source_wrapper(value.model_dump(mode="json"))
    assert "\ufeff" in value.snapshot.original.snapshot.text and "\r\n" in value.snapshot.original.snapshot.text
    assert not value.professional_review.snapshot.signed_by == value.governance.reviewed_by
    audit = s.source_current(db, users["super_admin_user"], value.snapshot.source_binding_id, audit_only=True)
    assert audit.audit_only and not audit.eligible and not any((audit.can_sign, audit.can_review, audit.can_revoke))
    with pytest.raises(HTTPException):
        s.source_current(db, users["pharmacist_user"], value.snapshot.source_binding_id, audit_only=True)


@pytest.mark.parametrize("decision", ["unknown", "not_confirmed"])
def test_unknown_or_unconfirmed_professional_outcome_is_preserved_and_cannot_publish(label_case, decision):
    db, users, _, _ = label_case
    value = create(label_case)
    body = {**cas(value), "catalog_match_review": decision, "provided_text_version_review": "confirmed", "basis_note": NOTE}
    value = s.sign_source(db, users["pharmacist_user"], value.snapshot.source_binding_id, body)
    db.commit()
    assert value.professional_review.snapshot.catalog_match_review == decision
    ref = value.professional_review
    with pytest.raises(HTTPException):
        s.review_source(
            db,
            users["super_admin_user"],
            value.snapshot.source_binding_id,
            {
                **cas(value),
                "decision": "approve",
                "professional": {"professional_review_id": ref.snapshot.professional_review_id, "content_hash": ref.content_hash, "governance_hash": ref.governance_hash},
                "basis_note": NOTE,
            },
        )
    assert db.get(AIDrugLabelSource, value.snapshot.source_binding_id).status == "draft"


@pytest.mark.parametrize("role", ["super_admin", "admin", "doctor", "director", "cashier"])
def test_non_pharmacist_cannot_sign_even_if_legacy_pharmacy_role(label_case, role):
    db, users, _, _ = label_case
    value = create(label_case)
    actor = User(username="role73_" + role, user_role=role)
    db.add(actor)
    db.commit()
    with pytest.raises(HTTPException):
        s.sign_source(db, actor, value.snapshot.source_binding_id, dict(**cas(value), catalog_match_review="confirmed", provided_text_version_review="confirmed", basis_note=NOTE))
    assert db.query(AIDrugLabelProfessionalReview).filter_by(source_binding_id=value.snapshot.source_binding_id).count() == 0


def test_cross_role_self_signature_is_not_independent(label_case):
    db, users, _, _ = label_case
    value = create(label_case)
    actor = users["super_admin_user"]
    db.query(User).filter_by(user_id=actor.user_id).update({"user_role": "pharmacist"}, synchronize_session=False)
    db.commit()
    db.expire(actor)
    with pytest.raises(HTTPException) as denied:
        s.sign_source(db, actor, value.snapshot.source_binding_id, dict(**cas(value), catalog_match_review="confirmed", provided_text_version_review="confirmed", basis_note=NOTE))
    assert denied.value.status_code == 409
    db.query(User).filter_by(user_id=actor.user_id).update({"user_role": "super_admin"}, synchronize_session=False)
    db.commit()


@pytest.mark.parametrize("field,value", [("name", "另一真实目录名"), ("barcode", "changed73"), ("status", 1), ("status", None)])
def test_compared_identity_change_blocks_ordinary_read_but_not_super_frozen(label_case, field, value):
    db, users, sku, _ = label_case
    published = publish(label_case)
    setattr(sku, field, value)
    db.commit()
    with pytest.raises(HTTPException) as denied:
        s.source_current(db, users["pharmacist_user"], published.snapshot.source_binding_id)
    assert denied.value.status_code == 409
    audit = s.source_current(db, users["super_admin_user"], published.snapshot.source_binding_id, audit_only=True)
    assert not audit.identity_current and not audit.eligible and audit.snapshot.identity.name == "合成药品73"


def test_inventory_price_and_non_identity_changes_do_not_change_declared_scope(label_case):
    db, users, sku, _ = label_case
    value = publish(label_case)
    sku.stock, sku.price, sku.supplier, sku.remark, sku.antibiotic_level = 100, "9.99", "新供应商", "新库存说明", 3
    db.commit()
    current = s.source_current(db, users["pharmacist_user"], value.snapshot.source_binding_id, execution=True)
    assert current.eligible and current.snapshot.identity_hash == value.snapshot.identity_hash
    assert list(current.snapshot.identity.model_dump()) == list(c.COMPARISON_FIELDS)


@pytest.mark.parametrize("axis", ["original", "professional", "source", "signer_role"])
def test_parent_signature_source_revoke_or_current_signer_demotion_invalidates(label_case, axis):
    db, users, _, original = label_case
    value = publish(label_case)
    if axis == "original":
        documents.revoke_original(db, users["super_admin_user"], original.snapshot.original_id, {**cas(original), "basis_note": NOTE})
    elif axis == "professional":
        s.revoke_professional(db, users["pharmacist_user"], value.snapshot.source_binding_id, {**cas(value.professional_review), "basis_note": NOTE})
    elif axis == "source":
        s.revoke_source(db, users["super_admin_user"], value.snapshot.source_binding_id, {**cas(value), "basis_note": NOTE})
    else:
        db.query(User).filter_by(user_id=users["pharmacist_user"].user_id).update({"user_role": "patient"}, synchronize_session=False)
    db.commit()
    with pytest.raises(HTTPException):
        s.source_current(db, users["pharmacist_user"], value.snapshot.source_binding_id, execution=True)
    audit = s.source_current(db, users["super_admin_user"], value.snapshot.source_binding_id, audit_only=True)
    assert not audit.eligible and audit.snapshot == value.snapshot
    if axis == "signer_role":
        db.query(User).filter_by(user_id=users["pharmacist_user"].user_id).update({"user_role": "pharmacist"}, synchronize_session=False)
        db.commit()


def test_duplicate_signature_and_wrong_cas_cannot_rewrite_professional_decision(label_case):
    db, users, _, _ = label_case
    value = sign(label_case, create(label_case))
    with pytest.raises(HTTPException):
        s.sign_source(db, users["pharmacist_user"], value.snapshot.source_binding_id, dict(**cas(value), catalog_match_review="confirmed", provided_text_version_review="confirmed", basis_note=NOTE))
    assert db.query(AIDrugLabelProfessionalReview).filter_by(source_binding_id=value.snapshot.source_binding_id).count() == 1
    with pytest.raises(HTTPException):
        s.revoke_source(db, users["super_admin_user"], value.snapshot.source_binding_id, {**cas(value), "expected_content_hash": "f" * 64, "basis_note": NOTE})


@pytest.mark.parametrize("mutation", ["snapshot", "header", "professional", "governance"])
def test_actual_stored_proof_mutation_rejected_not_rehashed_into_source(label_case, mutation):
    db, users, _, _ = label_case
    value = publish(label_case)
    row = db.get(AIDrugLabelSource, value.snapshot.source_binding_id)
    if mutation == "snapshot":
        raw = d.parse_json(row.snapshot_json)
        raw["original"]["snapshot"]["text"] += "伪造"
        row.snapshot_json = d.canonical_json(raw)
    elif mutation == "header":
        row.identity_hash = "f" * 64
    elif mutation == "professional":
        db.query(AIDrugLabelProfessionalReview).filter_by(source_binding_id=row.source_binding_id).update({"content_hash": "f" * 64}, synchronize_session=False)
    else:
        row.professional_governance_hash = "f" * 64
    db.commit()
    with pytest.raises(HTTPException):
        s.source_current(db, users["super_admin_user"], value.snapshot.source_binding_id, audit_only=True)


@pytest.mark.parametrize("fault", ["delete_audit", "alter_source", "demote_signer"])
def test_actual_after_audit_sql_fault_rolls_back_signature_and_exact_action(label_case, fault):
    db, users, _, _ = label_case
    value = create(label_case)
    before = db.query(AIAuditEvent).count()
    if fault == "delete_audit":
        body = "DELETE FROM hoimsystem_ai_audit_event WHERE event_id=NEW.event_id;"
    elif fault == "alter_source":
        body = f"UPDATE hoimsystem_ai_drug_label_source SET identity_hash='{'f' * 64}' WHERE source_binding_id=NEW.target;"
    else:
        body = f"UPDATE hoimsystem_users SET user_role='patient' WHERE user_id={users['pharmacist_user'].user_id};"
    db.execute(text(f"CREATE TRIGGER drug_label_fault AFTER INSERT ON hoimsystem_ai_audit_event WHEN NEW.action='drug_label.professional.sign' BEGIN {body} END"))
    db.commit()
    try:
        with pytest.raises(HTTPException):
            sign(label_case, value)
        assert db.query(AIDrugLabelProfessionalReview).filter_by(source_binding_id=value.snapshot.source_binding_id).count() == 0
        assert db.query(AIAuditEvent).count() == before
        assert db.get(AIDrugLabelSource, value.snapshot.source_binding_id).identity_hash == value.snapshot.identity_hash
        db.expire_all()
        assert db.get(User, users["pharmacist_user"].user_id).user_role == "pharmacist"
    finally:
        db.rollback()
        db.execute(text("DROP TRIGGER drug_label_fault"))
        db.commit()


def test_full_object_budget_refuses_before_persist_or_audit(label_case, monkeypatch):
    db, users, _, _ = label_case
    before = db.query(AIDrugLabelSource).count(), db.query(AIAuditEvent).count()
    monkeypatch.setattr(c, "MAX_SOURCE_BYTES", 200)
    with pytest.raises(HTTPException):
        create(label_case)
    assert (db.query(AIDrugLabelSource).count(), db.query(AIAuditEvent).count()) == before


def test_self_rehash_cannot_remove_missing_authority_declarations(label_case):
    value = publish(label_case)
    altered = copy.deepcopy(value.model_dump(mode="json"))
    altered["missing_evidence"] = []
    assert not s.verify_source_wrapper(altered)
