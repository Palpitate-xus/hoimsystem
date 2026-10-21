"""Independent boundary outcomes: unchanged unknowns, version kind, session epoch."""

import datetime as dt

import pytest
from fastapi import HTTPException
from sqlalchemy import text

from app.ai import document_evidence_sources as documents
from app.ai import drug_label_sources as sources
from app.ai.drug_label_models import AIDrugLabelSource
from app.ai.models import AIAuditEvent
from tests.test_ai_drug_label_sources import NOTE, NOW, cas, create
from tests.test_ai_drug_label_sources import label_case as _label_case
from tests.test_ai_drug_label_sources import sign as sign_binding

label_case = _label_case


def test_unknown_professional_review_can_be_rejected_without_rewriting_its_outcome(label_case):
    db, users, _, _ = label_case
    value = create(label_case)
    value = sources.sign_source(
        db, users["pharmacist_user"], value.snapshot.source_binding_id, {**cas(value), "catalog_match_review": "unknown", "provided_text_version_review": "not_confirmed", "basis_note": NOTE}
    )
    db.commit()
    prof = value.professional_review
    rejected = sources.review_source(
        db,
        users["super_admin_user"],
        value.snapshot.source_binding_id,
        {
            **cas(value),
            "decision": "reject",
            "professional": {"professional_review_id": prof.snapshot.professional_review_id, "content_hash": prof.content_hash, "governance_hash": prof.governance_hash},
            "basis_note": NOTE,
        },
    )
    db.commit()
    assert rejected.governance.status == "rejected" and not rejected.eligible
    assert rejected.professional_review.snapshot.catalog_match_review == "unknown"
    assert rejected.professional_review.snapshot.provided_text_version_review == "not_confirmed"
    assert rejected.governance.professional is None


def test_signature_clock_cannot_predate_released_source(label_case, monkeypatch):
    db, users, _, _ = label_case
    value = create(label_case)
    before = db.query(AIAuditEvent).count()
    monkeypatch.setattr(sources, "utcnow", lambda: documents.c.clock(NOW) - dt.timedelta(microseconds=1))
    with pytest.raises(HTTPException):
        sign_binding(label_case, value)
    assert db.query(AIAuditEvent).count() == before


def test_actual_after_audit_token_epoch_change_rejects_and_rolls_back_source(label_case):
    db, users, _, _ = label_case
    before = db.query(AIAuditEvent).count(), db.query(AIDrugLabelSource).count()
    uid = users["super_admin_user"].user_id
    db.execute(
        text(
            f"CREATE TRIGGER label_epoch AFTER INSERT ON hoimsystem_ai_audit_event WHEN NEW.action='drug_label.source.create' BEGIN UPDATE hoimsystem_users SET token_invalid_before='2026-10-21 12:00:01' WHERE user_id={uid}; END"
        )
    )
    db.commit()
    try:
        with pytest.raises(HTTPException) as denied:
            create(label_case)
        assert denied.value.status_code == 403
        assert (db.query(AIAuditEvent).count(), db.query(AIDrugLabelSource).count()) == before
        db.expire_all()
        assert users["super_admin_user"].token_invalid_before is None
    finally:
        db.rollback()
        db.execute(text("DROP TRIGGER label_epoch"))
        db.commit()
