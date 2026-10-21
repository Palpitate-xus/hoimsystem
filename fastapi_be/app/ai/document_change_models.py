"""Additive immutable rule links and complete two-original comparison captures."""

from sqlalchemy import CheckConstraint, Column, ForeignKey, ForeignKeyConstraint, Index, Integer, String, UniqueConstraint

from app.ai.document_evidence_models import ReviewColumns, medium_text, utc6
from app.database import Base


def review_constraints(prefix):
    return (
        CheckConstraint(
            "privacy_review IN ('unknown','confirmed','not_confirmed') AND faithfulness_review IN ('unknown','confirmed','not_confirmed') AND dependency_review IN ('unknown','confirmed','not_confirmed') AND "
            "((reviewed_by IS NULL AND reviewed_at IS NULL AND review_basis_note = '' AND privacy_review = 'unknown' AND faithfulness_review = 'unknown' AND dependency_review = 'unknown' AND review_audit_event_id IS NULL) OR "
            "(reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL AND review_basis_note <> '' AND privacy_review <> 'unknown' AND faithfulness_review <> 'unknown' AND dependency_review <> 'unknown' AND review_audit_event_id IS NOT NULL))",
            name=f"ck_doc_change_{prefix}_review",
        ),
        CheckConstraint(
            "(status = 'draft' AND revision = 1 AND reviewed_by IS NULL AND revoked_by IS NULL AND revoked_at IS NULL AND revoke_reason = '') OR "
            "(status IN ('published','rejected') AND revision = 2 AND reviewed_by IS NOT NULL AND revoked_by IS NULL AND revoked_at IS NULL AND revoke_reason = '') OR "
            "(status = 'revoked' AND revoked_by IS NOT NULL AND revoked_at IS NOT NULL AND revoke_reason <> '' AND ((revision = 2 AND reviewed_by IS NULL) OR (revision = 3 AND reviewed_by IS NOT NULL)))",
            name=f"ck_doc_change_{prefix}_states",
        ),
        CheckConstraint(
            "status <> 'published' OR (privacy_review = 'confirmed' AND faithfulness_review = 'confirmed' AND dependency_review = 'confirmed')",
            name=f"ck_doc_change_{prefix}_published",
        ),
        CheckConstraint(
            "status <> 'rejected' OR privacy_review <> 'confirmed' OR faithfulness_review <> 'confirmed' OR dependency_review <> 'confirmed'",
            name=f"ck_doc_change_{prefix}_rejected",
        ),
        CheckConstraint(
            "(reviewed_at IS NULL OR reviewed_at >= recorded_at) AND (revoked_at IS NULL OR revoked_at >= recorded_at) AND (reviewed_at IS NULL OR revoked_at IS NULL OR revoked_at >= reviewed_at)",
            name=f"ck_doc_change_{prefix}_clocks",
        ),
        CheckConstraint("(revoked_by IS NULL AND revoke_audit_event_id IS NULL) OR (revoked_by IS NOT NULL AND revoke_audit_event_id IS NOT NULL)", name=f"ck_doc_change_{prefix}_revoke_audit"),
        CheckConstraint(
            "created_audit_event_id > 0 AND (review_audit_event_id IS NULL OR review_audit_event_id > 0) AND (revoke_audit_event_id IS NULL OR revoke_audit_event_id > 0)",
            name=f"ck_doc_change_{prefix}_audit_ids",
        ),
        CheckConstraint("length(review_basis_note) <= 4000 AND length(revoke_reason) <= 1000", name=f"ck_doc_change_{prefix}_notes"),
    )


class ChangeReviewColumns(ReviewColumns):
    dependency_review = Column(String(20), nullable=False)
    created_audit_event_id = Column(Integer, ForeignKey("hoimsystem_ai_audit_event.event_id"), nullable=False)
    review_audit_event_id = Column(Integer, ForeignKey("hoimsystem_ai_audit_event.event_id"), nullable=True)
    revoke_audit_event_id = Column(Integer, ForeignKey("hoimsystem_ai_audit_event.event_id"), nullable=True)


class AIDocumentRuleLink(ChangeReviewColumns, Base):
    __tablename__ = "hoimsystem_ai_document_rule_link"
    __table_args__ = review_constraints("link") + (
        ForeignKeyConstraint(
            ["original_id", "original_content_hash"], ["hoimsystem_ai_document_original.original_id", "hoimsystem_ai_document_original.content_hash"], name="fk_doc_change_link_original"
        ),
        UniqueConstraint("link_id", "content_hash", name="uq_doc_change_link_hash"),
        CheckConstraint(
            "(target_kind = 'risk_rule_profile' AND risk_rule_profile_id IS NOT NULL AND clinical_pathway_id IS NULL) OR "
            "(target_kind = 'clinical_pathway' AND risk_rule_profile_id IS NULL AND clinical_pathway_id IS NOT NULL AND clinical_pathway_id > 0)",
            name="ck_doc_change_link_target",
        ),
        CheckConstraint("span_start >= 0 AND span_end > span_start AND span_end <= 4194304", name="ck_doc_change_link_span"),
        CheckConstraint("length(link_json) > 0 AND length(link_json) <= 1048576", name="ck_doc_change_link_bytes"),
        Index("idx_doc_change_link_original", "original_id", "link_id"),
        Index("idx_doc_change_link_target", "target_kind", "risk_rule_profile_id", "clinical_pathway_id"),
    )
    link_id = Column(String(36), primary_key=True)
    original_id = Column(String(36), nullable=False)
    original_content_hash = Column(String(64), nullable=False)
    original_governance_hash = Column(String(64), nullable=False)
    target_kind = Column(String(32), nullable=False)
    # Historical links survive target deletion. Existence and exact current
    # typed snapshots are checked under current parent SHARE locks, not inferred
    # from a generic polymorphic FK or a retained technical identifier.
    risk_rule_profile_id = Column(String(36), nullable=True)
    clinical_pathway_id = Column(Integer, nullable=True)
    target_snapshot_hash = Column(String(64), nullable=False)
    span_start = Column(Integer, nullable=False)
    span_end = Column(Integer, nullable=False)
    link_json = Column(medium_text(), nullable=False)
    content_hash = Column(String(64), nullable=False)
    created_by = Column(Integer, ForeignKey("hoimsystem_users.user_id"), nullable=False)
    recorded_at = Column(utc6(), nullable=False)


class AIDocumentChangeScope(ChangeReviewColumns, Base):
    __tablename__ = "hoimsystem_ai_document_change_scope"
    __table_args__ = review_constraints("scope") + (
        ForeignKeyConstraint(
            ["baseline_original_id", "baseline_original_content_hash"],
            ["hoimsystem_ai_document_original.original_id", "hoimsystem_ai_document_original.content_hash"],
            name="fk_doc_change_scope_baseline",
        ),
        ForeignKeyConstraint(
            ["candidate_original_id", "candidate_original_content_hash"],
            ["hoimsystem_ai_document_original.original_id", "hoimsystem_ai_document_original.content_hash"],
            name="fk_doc_change_scope_candidate",
        ),
        CheckConstraint("baseline_original_id <> candidate_original_id", name="ck_doc_change_scope_two_sources"),
        CheckConstraint("member_count >= 2 AND member_count <= 8192", name="ck_doc_change_scope_members"),
        CheckConstraint("length(scope_json) > 0 AND length(scope_json) <= 8388608", name="ck_doc_change_scope_bytes"),
        Index("idx_doc_change_scope_originals", "baseline_original_id", "candidate_original_id", "recorded_at"),
    )
    scope_id = Column(String(36), primary_key=True)
    baseline_original_id = Column(String(36), nullable=False)
    baseline_original_content_hash = Column(String(64), nullable=False)
    baseline_original_governance_hash = Column(String(64), nullable=False)
    candidate_original_id = Column(String(36), nullable=False)
    candidate_original_content_hash = Column(String(64), nullable=False)
    candidate_original_governance_hash = Column(String(64), nullable=False)
    inventory_hash = Column(String(64), nullable=False)
    member_count = Column(Integer, nullable=False)
    scope_json = Column(medium_text(), nullable=False)
    content_hash = Column(String(64), nullable=False)
    created_by = Column(Integer, ForeignKey("hoimsystem_users.user_id"), nullable=False)
    recorded_at = Column(utc6(), nullable=False)


DOCUMENT_CHANGE_MODELS = (AIDocumentRuleLink, AIDocumentChangeScope)
