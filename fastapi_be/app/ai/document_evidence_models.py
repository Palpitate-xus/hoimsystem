"""Three additive exact-text evidence tables; existing knowledge TEXT stays unchanged."""

from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, ForeignKeyConstraint, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import declared_attr

from app.database import Base


def utc6():
    return DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql")


def medium_text():
    return Text().with_variant(mysql.MEDIUMTEXT(), "mysql")


class ReviewColumns:
    status = Column(String(16), nullable=False)
    revision = Column(Integer, nullable=False)
    privacy_review = Column(String(20), nullable=False)
    faithfulness_review = Column(String(20), nullable=False)
    reviewed_at = Column(utc6(), nullable=True)
    review_basis_note = Column(Text, nullable=False)
    revoked_at = Column(utc6(), nullable=True)
    revoke_reason = Column(String(1000), nullable=False)

    @declared_attr
    def reviewed_by(cls):  # noqa: N805
        return Column(Integer, ForeignKey("hoimsystem_users.user_id"), nullable=True)

    @declared_attr
    def revoked_by(cls):  # noqa: N805
        return Column(Integer, ForeignKey("hoimsystem_users.user_id"), nullable=True)


def review_constraints(prefix, approved):
    return (
        CheckConstraint(
            "privacy_review IN ('unknown','confirmed','not_confirmed') AND faithfulness_review IN ('unknown','confirmed','not_confirmed') AND "
            "((reviewed_by IS NULL AND reviewed_at IS NULL AND review_basis_note = '' AND privacy_review = 'unknown' AND faithfulness_review = 'unknown') OR "
            "(reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL AND review_basis_note <> '' AND privacy_review <> 'unknown' AND faithfulness_review <> 'unknown'))",
            name=f"ck_doc_{prefix}_review_signature",
        ),
        CheckConstraint(
            f"(status = 'draft' AND revision = 1 AND reviewed_by IS NULL AND revoked_by IS NULL AND revoked_at IS NULL AND revoke_reason = '') OR "
            f"(status IN ('{approved}','rejected') AND revision = 2 AND reviewed_by IS NOT NULL AND revoked_by IS NULL AND revoked_at IS NULL AND revoke_reason = '') OR "
            "(status = 'revoked' AND revoked_by IS NOT NULL AND revoked_at IS NOT NULL AND revoke_reason <> '' AND ((revision = 2 AND reviewed_by IS NULL) OR (revision = 3 AND reviewed_by IS NOT NULL)))",
            name=f"ck_doc_{prefix}_governance",
        ),
        CheckConstraint(f"status <> '{approved}' OR (privacy_review = 'confirmed' AND faithfulness_review = 'confirmed')", name=f"ck_doc_{prefix}_approved_reviews"),
        CheckConstraint("status <> 'rejected' OR privacy_review <> 'confirmed' OR faithfulness_review <> 'confirmed'", name=f"ck_doc_{prefix}_rejected_review"),
        CheckConstraint(
            "(reviewed_at IS NULL OR reviewed_at >= recorded_at) AND (revoked_at IS NULL OR revoked_at >= recorded_at) AND (reviewed_at IS NULL OR revoked_at IS NULL OR revoked_at >= reviewed_at)",
            name=f"ck_doc_{prefix}_clocks",
        ),
        CheckConstraint("length(review_basis_note) <= 4000 AND length(revoke_reason) <= 4000", name=f"ck_doc_{prefix}_basis_bytes"),
    )


class AIDocumentOriginal(ReviewColumns, Base):
    __tablename__ = "hoimsystem_ai_document_original"
    __table_args__ = review_constraints("original", "published") + (
        UniqueConstraint("original_id", "content_hash", name="uq_doc_original_hash"),
        CheckConstraint("raw_bytes_length > 0 AND raw_bytes_length <= 4194304 AND codepoint_length > 0 AND codepoint_length <= 4194304", name="ck_doc_original_raw_bounds"),
        CheckConstraint("length(original_text) > 0 AND length(original_text) <= 4194304 AND length(identity_json) > 0 AND length(identity_json) <= 65535", name="ck_doc_original_storage"),
        Index("idx_doc_original_governance", "status", "recorded_at", "original_id"),
    )
    original_id = Column(String(36), primary_key=True)
    identity_json = Column(Text, nullable=False)
    original_text = Column(medium_text(), nullable=False)
    raw_bytes_hash = Column(String(64), nullable=False)
    raw_bytes_length = Column(Integer, nullable=False)
    codepoint_length = Column(Integer, nullable=False)
    content_hash = Column(String(64), nullable=False)
    created_by = Column(Integer, ForeignKey("hoimsystem_users.user_id"), nullable=False)
    recorded_at = Column(utc6(), nullable=False)


class AIDocumentSpanCandidate(ReviewColumns, Base):
    __tablename__ = "hoimsystem_ai_document_span_candidate"
    __table_args__ = review_constraints("candidate", "approved") + (
        ForeignKeyConstraint(
            ["original_id", "original_content_hash"], ["hoimsystem_ai_document_original.original_id", "hoimsystem_ai_document_original.content_hash"], name="fk_doc_candidate_original_hash"
        ),
        UniqueConstraint("candidate_id", "original_id", "content_hash", name="uq_doc_candidate_original_hash"),
        CheckConstraint("span_start >= 0 AND span_end > span_start AND span_end <= 4194304 AND length(candidate_json) > 0 AND length(candidate_json) <= 131072", name="ck_doc_candidate_span_storage"),
        Index("idx_doc_candidate_original", "original_id", "status", "recorded_at"),
    )
    candidate_id = Column(String(36), primary_key=True)
    original_id = Column(String(36), nullable=False)
    original_content_hash = Column(String(64), nullable=False)
    original_governance_hash = Column(String(64), nullable=False)
    span_start = Column(Integer, nullable=False)
    span_end = Column(Integer, nullable=False)
    candidate_json = Column(medium_text(), nullable=False)
    content_hash = Column(String(64), nullable=False)
    created_by = Column(Integer, ForeignKey("hoimsystem_users.user_id"), nullable=False)
    recorded_at = Column(utc6(), nullable=False)


class AIDocumentKnowledgePublication(Base):
    __tablename__ = "hoimsystem_ai_document_knowledge_publication"
    __table_args__ = (
        ForeignKeyConstraint(
            ["original_id", "original_content_hash"], ["hoimsystem_ai_document_original.original_id", "hoimsystem_ai_document_original.content_hash"], name="fk_doc_publication_original_hash"
        ),
        ForeignKeyConstraint(
            ["candidate_id", "original_id", "candidate_content_hash"],
            ["hoimsystem_ai_document_span_candidate.candidate_id", "hoimsystem_ai_document_span_candidate.original_id", "hoimsystem_ai_document_span_candidate.content_hash"],
            name="fk_doc_publication_candidate_hash",
        ),
        UniqueConstraint("candidate_id", name="uq_doc_publication_candidate"),
        UniqueConstraint("knowledge_document_id", name="uq_doc_publication_knowledge"),
        CheckConstraint("length(publication_json) > 0 AND length(publication_json) <= 196608", name="ck_doc_publication_storage"),
        CheckConstraint(
            "(status = 'active' AND revision = 1 AND revoked_by IS NULL AND revoked_at IS NULL AND revoke_reason = '') OR "
            "(status = 'revoked' AND revision = 2 AND revoked_by IS NOT NULL AND revoked_at IS NOT NULL AND revoked_at >= published_at AND revoke_reason <> '')",
            name="ck_doc_publication_governance",
        ),
        Index("idx_doc_publication_original", "original_id", "status"),
    )
    publication_id = Column(String(36), primary_key=True)
    original_id = Column(String(36), nullable=False)
    original_content_hash = Column(String(64), nullable=False)
    candidate_id = Column(String(36), nullable=False)
    candidate_content_hash = Column(String(64), nullable=False)
    knowledge_document_id = Column(String(36), ForeignKey("hoimsystem_ai_knowledge_document.document_id"), nullable=False)
    publication_json = Column(medium_text(), nullable=False)
    content_hash = Column(String(64), nullable=False)
    published_by = Column(Integer, ForeignKey("hoimsystem_users.user_id"), nullable=False)
    published_at = Column(utc6(), nullable=False)
    status = Column(String(16), nullable=False)
    revision = Column(Integer, nullable=False)
    revoked_by = Column(Integer, ForeignKey("hoimsystem_users.user_id"), nullable=True)
    revoked_at = Column(utc6(), nullable=True)
    revoke_reason = Column(String(1000), nullable=False)


DOCUMENT_EVIDENCE_MODELS = (AIDocumentOriginal, AIDocumentSpanCandidate, AIDocumentKnowledgePublication)
