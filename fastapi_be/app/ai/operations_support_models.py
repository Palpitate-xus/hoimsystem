"""Additive storage for reviewed operational documents and finite snapshots.

Actual current authority, immutable content and concrete audit validation remain
service responsibilities. The database also rejects impossible state/byte bounds.
"""

from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, ForeignKeyConstraint, Index, Integer, LargeBinary, String, Text, UniqueConstraint, and_, cast, func
from sqlalchemy.dialects import mysql

from app.database import Base


def utc6():
    return DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql")


def medium_text():
    return Text().with_variant(mysql.MEDIUMTEXT(), "mysql")


def byte_bounds(column, maximum, name):
    # SQLite length(TEXT) counts codepoints and stops at NUL. Count stored UTF8
    # bytes in both dialects, including NUL and supplementary characters.
    size = func.length(cast(column, LargeBinary))
    return CheckConstraint(and_(size >= 1, size <= maximum), name=name)


class AIOperationsWriteGate(Base):
    __tablename__ = "hoimsystem_ai_operations_write_gate"
    gate_id = Column(Integer, primary_key=True, autoincrement=False)
    revision = Column(Integer, nullable=False)
    __table_args__ = (CheckConstraint("gate_id = 1 AND revision = 1", name="ck_ops_single_gate"),)


class AIOperationsOriginal(Base):
    __tablename__ = "hoimsystem_ai_operations_original"
    original_id = Column(String(36), primary_key=True)
    identity_json = Column(Text, nullable=False)
    content_text = Column(medium_text(), nullable=False)
    content_hash = Column(String(64), nullable=False)
    raw_text_sha256 = Column(String(64), nullable=False)
    raw_bytes_length = Column(Integer, nullable=False)
    codepoint_length = Column(Integer, nullable=False)
    captured_by = Column(Integer, ForeignKey("hoimsystem_users.user_id"), nullable=False)
    captured_at = Column(utc6(), nullable=False)
    creation_event_id = Column(Integer, ForeignKey("hoimsystem_ai_audit_event.event_id"), nullable=False, unique=True)
    status = Column(String(16), nullable=False)
    revision = Column(Integer, nullable=False)
    revoked_by = Column(Integer, ForeignKey("hoimsystem_users.user_id"), nullable=True)
    revoked_at = Column(utc6(), nullable=True)
    revoke_reason = Column(String(1000), nullable=False)
    revocation_event_id = Column(Integer, ForeignKey("hoimsystem_ai_audit_event.event_id"), nullable=True, unique=True)
    __table_args__ = (
        UniqueConstraint("original_id", "content_hash", "captured_by", name="uq_ops_original_identity"),
        CheckConstraint("length(content_hash) = 64 AND length(raw_text_sha256) = 64", name="ck_ops_original_hashes"),
        CheckConstraint("raw_bytes_length >= 1 AND raw_bytes_length <= 4194304 AND codepoint_length >= 1 AND codepoint_length <= 4194304", name="ck_ops_original_sizes"),
        byte_bounds(identity_json, 65535, "ck_ops_original_metadata_bytes"),
        byte_bounds(content_text, 4194304, "ck_ops_original_text_bytes"),
        CheckConstraint(
            "(status = 'active' AND revision = 1 AND revoked_by IS NULL AND revoked_at IS NULL AND revoke_reason = '' AND revocation_event_id IS NULL) OR "
            "(status = 'revoked' AND revision = 2 AND revoked_by IS NOT NULL AND revoked_at IS NOT NULL AND revoke_reason <> '' AND revocation_event_id IS NOT NULL AND revoked_at >= captured_at)",
            name="ck_ops_original_state",
        ),
        CheckConstraint("revocation_event_id IS NULL OR revocation_event_id <> creation_event_id", name="ck_ops_original_receipt_distinct"),
        Index("idx_ops_original_directory", "status", "captured_at", "original_id"),
    )


class AIOperationsRelease(Base):
    __tablename__ = "hoimsystem_ai_operations_release"
    release_id = Column(String(36), primary_key=True)
    original_id = Column(String(36), nullable=False)
    original_content_hash = Column(String(64), nullable=False)
    original_captured_by = Column(Integer, nullable=False)
    draft_json = Column(medium_text(), nullable=False)
    content_hash = Column(String(64), nullable=False)
    created_by = Column(Integer, ForeignKey("hoimsystem_users.user_id"), nullable=False)
    recorded_at = Column(utc6(), nullable=False)
    creation_event_id = Column(Integer, ForeignKey("hoimsystem_ai_audit_event.event_id"), nullable=False, unique=True)
    status = Column(String(16), nullable=False)
    revision = Column(Integer, nullable=False)
    review_decision = Column(String(16), nullable=True)
    privacy_reviewed = Column(Integer, nullable=True)
    faithfulness_reviewed = Column(Integer, nullable=True)
    applicability_reviewed = Column(Integer, nullable=True)
    model_processing_allowed = Column(Integer, nullable=True)
    reviewed_by = Column(Integer, ForeignKey("hoimsystem_users.user_id"), nullable=True)
    reviewed_at = Column(utc6(), nullable=True)
    review_basis = Column(Text, nullable=False)
    review_event_id = Column(Integer, ForeignKey("hoimsystem_ai_audit_event.event_id"), nullable=True, unique=True)
    published_review_json = Column(medium_text(), nullable=True)
    published_review_hash = Column(String(64), nullable=True)
    revoked_by = Column(Integer, ForeignKey("hoimsystem_users.user_id"), nullable=True)
    revoked_at = Column(utc6(), nullable=True)
    revoke_reason = Column(String(1000), nullable=False)
    revocation_event_id = Column(Integer, ForeignKey("hoimsystem_ai_audit_event.event_id"), nullable=True, unique=True)
    __table_args__ = (
        ForeignKeyConstraint(
            ["original_id", "original_content_hash", "original_captured_by"],
            ["hoimsystem_ai_operations_original.original_id", "hoimsystem_ai_operations_original.content_hash", "hoimsystem_ai_operations_original.captured_by"],
            name="fk_ops_release_original",
        ),
        UniqueConstraint("release_id", "content_hash", name="uq_ops_release_content"),
        CheckConstraint("length(content_hash) = 64 AND length(original_content_hash) = 64", name="ck_ops_release_hashes"),
        byte_bounds(draft_json, 8388608, "ck_ops_release_draft_bytes"),
        byte_bounds(published_review_json, 8388608, "ck_ops_release_published_bytes"),
        CheckConstraint(
            "(reviewed_by IS NULL AND reviewed_at IS NULL AND review_decision IS NULL AND review_basis = '' AND review_event_id IS NULL AND "
            "privacy_reviewed IS NULL AND faithfulness_reviewed IS NULL AND applicability_reviewed IS NULL AND model_processing_allowed IS NULL AND published_review_json IS NULL AND published_review_hash IS NULL) OR "
            "(reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL AND reviewed_at >= recorded_at AND review_basis <> '' AND review_event_id IS NOT NULL AND "
            "reviewed_by <> created_by AND reviewed_by <> original_captured_by AND "
            "review_decision IS NOT NULL AND privacy_reviewed IS NOT NULL AND faithfulness_reviewed IS NOT NULL AND applicability_reviewed IS NOT NULL AND model_processing_allowed IS NOT NULL AND "
            "privacy_reviewed IN (0,1) AND faithfulness_reviewed IN (0,1) AND applicability_reviewed IN (0,1) AND model_processing_allowed IN (0,1) AND "
            "((review_decision = 'published' AND privacy_reviewed = 1 AND faithfulness_reviewed = 1 AND applicability_reviewed = 1 AND published_review_json IS NOT NULL AND published_review_hash IS NOT NULL AND length(published_review_hash) = 64) OR "
            "(review_decision = 'rejected' AND (privacy_reviewed = 0 OR faithfulness_reviewed = 0 OR applicability_reviewed = 0) AND published_review_json IS NULL AND published_review_hash IS NULL)))",
            name="ck_ops_release_review",
        ),
        CheckConstraint(
            "(status = 'draft' AND revision = 1 AND reviewed_by IS NULL AND revoked_by IS NULL AND revoked_at IS NULL AND revoke_reason = '' AND revocation_event_id IS NULL) OR "
            "(status IN ('published','rejected') AND status = review_decision AND revision = 2 AND reviewed_by IS NOT NULL AND revoked_by IS NULL AND revoked_at IS NULL AND revoke_reason = '' AND revocation_event_id IS NULL) OR "
            "(status = 'revoked' AND revoked_by IS NOT NULL AND revoked_at IS NOT NULL AND revoke_reason <> '' AND revocation_event_id IS NOT NULL AND revoked_at >= recorded_at AND "
            "((revision = 2 AND reviewed_by IS NULL) OR (revision = 3 AND reviewed_by IS NOT NULL AND revoked_at >= reviewed_at)))",
            name="ck_ops_release_state",
        ),
        CheckConstraint(
            "(review_event_id IS NULL OR review_event_id <> creation_event_id) AND (revocation_event_id IS NULL OR revocation_event_id <> creation_event_id) AND "
            "(review_event_id IS NULL OR revocation_event_id IS NULL OR review_event_id <> revocation_event_id)",
            name="ck_ops_release_receipts_distinct",
        ),
        CheckConstraint(func.length(cast(review_basis, LargeBinary)) <= 16000, name="ck_ops_release_basis_bytes"),
        Index("idx_ops_release_directory", "status", "recorded_at", "release_id"),
        Index("idx_ops_release_original", "original_id", "status"),
    )


class AIOperationsCase(Base):
    __tablename__ = "hoimsystem_ai_operations_case"
    case_id = Column(String(36), primary_key=True)
    requested_by = Column(Integer, ForeignKey("hoimsystem_users.user_id"), nullable=False)
    assembled_at = Column(utc6(), nullable=False)
    member_bindings_json = Column(medium_text(), nullable=False)
    member_bindings_hash = Column(String(64), nullable=False)
    private_json = Column(medium_text(), nullable=False)
    private_hash = Column(String(64), nullable=False)
    public_json = Column(medium_text(), nullable=False)
    public_hash = Column(String(64), nullable=False)
    source_count = Column(Integer, nullable=False)
    creation_event_id = Column(Integer, ForeignKey("hoimsystem_ai_audit_event.event_id"), nullable=False, unique=True)
    status = Column(String(16), nullable=False)
    revision = Column(Integer, nullable=False)
    revoked_by = Column(Integer, ForeignKey("hoimsystem_users.user_id"), nullable=True)
    revoked_at = Column(utc6(), nullable=True)
    revoke_reason = Column(String(1000), nullable=False)
    revocation_event_id = Column(Integer, ForeignKey("hoimsystem_ai_audit_event.event_id"), nullable=True, unique=True)
    __table_args__ = (
        UniqueConstraint("case_id", "private_hash", "public_hash", "requested_by", name="uq_ops_case_binding"),
        CheckConstraint("length(member_bindings_hash) = 64 AND length(private_hash) = 64 AND length(public_hash) = 64 AND source_count >= 1 AND source_count <= 128", name="ck_ops_case_hash_count"),
        byte_bounds(member_bindings_json, 262144, "ck_ops_case_members_bytes"),
        byte_bounds(private_json, 8388608, "ck_ops_case_private_bytes"),
        byte_bounds(public_json, 8388608, "ck_ops_case_public_bytes"),
        CheckConstraint(
            "(status = 'active' AND revision = 1 AND revoked_by IS NULL AND revoked_at IS NULL AND revoke_reason = '' AND revocation_event_id IS NULL) OR "
            "(status = 'revoked' AND revision = 2 AND revoked_by IS NOT NULL AND revoked_at IS NOT NULL AND revoke_reason <> '' AND revocation_event_id IS NOT NULL AND revoked_at >= assembled_at)",
            name="ck_ops_case_state",
        ),
        CheckConstraint("revocation_event_id IS NULL OR revocation_event_id <> creation_event_id", name="ck_ops_case_receipts_distinct"),
        Index("idx_ops_case_owner", "requested_by", "status", "assembled_at", "case_id"),
    )


OPERATIONS_SOURCE_MODELS = (AIOperationsWriteGate, AIOperationsOriginal, AIOperationsRelease, AIOperationsCase)
