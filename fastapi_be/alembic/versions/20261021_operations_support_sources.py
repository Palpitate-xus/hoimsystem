"""Reviewed operational originals and finite snapshots; four additive tables."""

from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, ForeignKeyConstraint, Integer, LargeBinary, String, Text, UniqueConstraint, and_, cast, column, func
from sqlalchemy.dialects import mysql

from alembic import op

revision = "20261021_ops_sources"
down_revision = "20261021_native_research_merge"
branch_labels = None
depends_on = None


def utc6():
    return DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql")


def medium_text():
    return Text().with_variant(mysql.MEDIUMTEXT(), "mysql")


def byte_bounds(column, maximum, name):
    # SQLite length(TEXT) counts codepoints and stops at NUL. Count stored UTF8
    # bytes in both dialects, including NUL and supplementary characters.
    size = func.length(cast(column, LargeBinary))
    return CheckConstraint(and_(size >= 1, size <= maximum), name=name)


def upgrade():
    op.create_table(
        "hoimsystem_ai_operations_write_gate",
        Column("gate_id", Integer, primary_key=True, autoincrement=False),
        Column("revision", Integer, nullable=False),
        CheckConstraint("gate_id = 1 AND revision = 1", name="ck_ops_single_gate"),
    )
    op.create_table(
        "hoimsystem_ai_operations_original",
        Column("original_id", String(36), primary_key=True),
        Column("identity_json", Text, nullable=False),
        Column("content_text", medium_text(), nullable=False),
        Column("content_hash", String(64), nullable=False),
        Column("raw_text_sha256", String(64), nullable=False),
        Column("raw_bytes_length", Integer, nullable=False),
        Column("codepoint_length", Integer, nullable=False),
        Column("captured_by", Integer, ForeignKey("hoimsystem_users.user_id"), nullable=False),
        Column("captured_at", utc6(), nullable=False),
        Column("creation_event_id", Integer, ForeignKey("hoimsystem_ai_audit_event.event_id"), nullable=False, unique=True),
        Column("status", String(16), nullable=False),
        Column("revision", Integer, nullable=False),
        Column("revoked_by", Integer, ForeignKey("hoimsystem_users.user_id"), nullable=True),
        Column("revoked_at", utc6(), nullable=True),
        Column("revoke_reason", String(1000), nullable=False),
        Column("revocation_event_id", Integer, ForeignKey("hoimsystem_ai_audit_event.event_id"), nullable=True, unique=True),
        UniqueConstraint("original_id", "content_hash", "captured_by", name="uq_ops_original_identity"),
        CheckConstraint("length(content_hash) = 64 AND length(raw_text_sha256) = 64", name="ck_ops_original_hashes"),
        CheckConstraint("raw_bytes_length >= 1 AND raw_bytes_length <= 4194304 AND codepoint_length >= 1 AND codepoint_length <= 4194304", name="ck_ops_original_sizes"),
        byte_bounds(column("identity_json"), 65535, "ck_ops_original_metadata_bytes"),
        byte_bounds(column("content_text"), 4194304, "ck_ops_original_text_bytes"),
        CheckConstraint(
            "(status = 'active' AND revision = 1 AND revoked_by IS NULL AND revoked_at IS NULL AND revoke_reason = '' AND revocation_event_id IS NULL) OR (status = 'revoked' AND revision = 2 AND revoked_by IS NOT NULL AND revoked_at IS NOT NULL AND revoke_reason <> '' AND revocation_event_id IS NOT NULL AND revoked_at >= captured_at)",
            name="ck_ops_original_state",
        ),
        CheckConstraint("revocation_event_id IS NULL OR revocation_event_id <> creation_event_id", name="ck_ops_original_receipt_distinct"),
    )
    op.create_index("idx_ops_original_directory", "hoimsystem_ai_operations_original", ["status", "captured_at", "original_id"], unique=False)
    op.create_table(
        "hoimsystem_ai_operations_release",
        Column("release_id", String(36), primary_key=True),
        Column("original_id", String(36), nullable=False),
        Column("original_content_hash", String(64), nullable=False),
        Column("original_captured_by", Integer, nullable=False),
        Column("draft_json", medium_text(), nullable=False),
        Column("content_hash", String(64), nullable=False),
        Column("created_by", Integer, ForeignKey("hoimsystem_users.user_id"), nullable=False),
        Column("recorded_at", utc6(), nullable=False),
        Column("creation_event_id", Integer, ForeignKey("hoimsystem_ai_audit_event.event_id"), nullable=False, unique=True),
        Column("status", String(16), nullable=False),
        Column("revision", Integer, nullable=False),
        Column("review_decision", String(16), nullable=True),
        Column("privacy_reviewed", Integer, nullable=True),
        Column("faithfulness_reviewed", Integer, nullable=True),
        Column("applicability_reviewed", Integer, nullable=True),
        Column("model_processing_allowed", Integer, nullable=True),
        Column("reviewed_by", Integer, ForeignKey("hoimsystem_users.user_id"), nullable=True),
        Column("reviewed_at", utc6(), nullable=True),
        Column("review_basis", Text, nullable=False),
        Column("review_event_id", Integer, ForeignKey("hoimsystem_ai_audit_event.event_id"), nullable=True, unique=True),
        Column("published_review_json", medium_text(), nullable=True),
        Column("published_review_hash", String(64), nullable=True),
        Column("revoked_by", Integer, ForeignKey("hoimsystem_users.user_id"), nullable=True),
        Column("revoked_at", utc6(), nullable=True),
        Column("revoke_reason", String(1000), nullable=False),
        Column("revocation_event_id", Integer, ForeignKey("hoimsystem_ai_audit_event.event_id"), nullable=True, unique=True),
        ForeignKeyConstraint(
            ["original_id", "original_content_hash", "original_captured_by"],
            ["hoimsystem_ai_operations_original.original_id", "hoimsystem_ai_operations_original.content_hash", "hoimsystem_ai_operations_original.captured_by"],
            name="fk_ops_release_original",
        ),
        UniqueConstraint("release_id", "content_hash", name="uq_ops_release_content"),
        CheckConstraint("length(content_hash) = 64 AND length(original_content_hash) = 64", name="ck_ops_release_hashes"),
        byte_bounds(column("draft_json"), 8388608, "ck_ops_release_draft_bytes"),
        byte_bounds(column("published_review_json"), 8388608, "ck_ops_release_published_bytes"),
        CheckConstraint(
            "(reviewed_by IS NULL AND reviewed_at IS NULL AND review_decision IS NULL AND review_basis = '' AND review_event_id IS NULL AND privacy_reviewed IS NULL AND faithfulness_reviewed IS NULL AND applicability_reviewed IS NULL AND model_processing_allowed IS NULL AND published_review_json IS NULL AND published_review_hash IS NULL) OR (reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL AND reviewed_at >= recorded_at AND review_basis <> '' AND review_event_id IS NOT NULL AND reviewed_by <> created_by AND reviewed_by <> original_captured_by AND review_decision IS NOT NULL AND privacy_reviewed IS NOT NULL AND faithfulness_reviewed IS NOT NULL AND applicability_reviewed IS NOT NULL AND model_processing_allowed IS NOT NULL AND privacy_reviewed IN (0,1) AND faithfulness_reviewed IN (0,1) AND applicability_reviewed IN (0,1) AND model_processing_allowed IN (0,1) AND ((review_decision = 'published' AND privacy_reviewed = 1 AND faithfulness_reviewed = 1 AND applicability_reviewed = 1 AND published_review_json IS NOT NULL AND published_review_hash IS NOT NULL AND length(published_review_hash) = 64) OR (review_decision = 'rejected' AND (privacy_reviewed = 0 OR faithfulness_reviewed = 0 OR applicability_reviewed = 0) AND published_review_json IS NULL AND published_review_hash IS NULL)))",
            name="ck_ops_release_review",
        ),
        CheckConstraint(
            "(status = 'draft' AND revision = 1 AND reviewed_by IS NULL AND revoked_by IS NULL AND revoked_at IS NULL AND revoke_reason = '' AND revocation_event_id IS NULL) OR (status IN ('published','rejected') AND status = review_decision AND revision = 2 AND reviewed_by IS NOT NULL AND revoked_by IS NULL AND revoked_at IS NULL AND revoke_reason = '' AND revocation_event_id IS NULL) OR (status = 'revoked' AND revoked_by IS NOT NULL AND revoked_at IS NOT NULL AND revoke_reason <> '' AND revocation_event_id IS NOT NULL AND revoked_at >= recorded_at AND ((revision = 2 AND reviewed_by IS NULL) OR (revision = 3 AND reviewed_by IS NOT NULL AND revoked_at >= reviewed_at)))",
            name="ck_ops_release_state",
        ),
        CheckConstraint(
            "(review_event_id IS NULL OR review_event_id <> creation_event_id) AND (revocation_event_id IS NULL OR revocation_event_id <> creation_event_id) AND (review_event_id IS NULL OR revocation_event_id IS NULL OR review_event_id <> revocation_event_id)",
            name="ck_ops_release_receipts_distinct",
        ),
        CheckConstraint(func.length(cast(column("review_basis"), LargeBinary)) <= 16000, name="ck_ops_release_basis_bytes"),
    )
    op.create_index("idx_ops_release_directory", "hoimsystem_ai_operations_release", ["status", "recorded_at", "release_id"], unique=False)
    op.create_index("idx_ops_release_original", "hoimsystem_ai_operations_release", ["original_id", "status"], unique=False)
    op.create_table(
        "hoimsystem_ai_operations_case",
        Column("case_id", String(36), primary_key=True),
        Column("requested_by", Integer, ForeignKey("hoimsystem_users.user_id"), nullable=False),
        Column("assembled_at", utc6(), nullable=False),
        Column("member_bindings_json", medium_text(), nullable=False),
        Column("member_bindings_hash", String(64), nullable=False),
        Column("private_json", medium_text(), nullable=False),
        Column("private_hash", String(64), nullable=False),
        Column("public_json", medium_text(), nullable=False),
        Column("public_hash", String(64), nullable=False),
        Column("source_count", Integer, nullable=False),
        Column("creation_event_id", Integer, ForeignKey("hoimsystem_ai_audit_event.event_id"), nullable=False, unique=True),
        Column("status", String(16), nullable=False),
        Column("revision", Integer, nullable=False),
        Column("revoked_by", Integer, ForeignKey("hoimsystem_users.user_id"), nullable=True),
        Column("revoked_at", utc6(), nullable=True),
        Column("revoke_reason", String(1000), nullable=False),
        Column("revocation_event_id", Integer, ForeignKey("hoimsystem_ai_audit_event.event_id"), nullable=True, unique=True),
        UniqueConstraint("case_id", "private_hash", "public_hash", "requested_by", name="uq_ops_case_binding"),
        CheckConstraint("length(member_bindings_hash) = 64 AND length(private_hash) = 64 AND length(public_hash) = 64 AND source_count >= 1 AND source_count <= 128", name="ck_ops_case_hash_count"),
        byte_bounds(column("member_bindings_json"), 262144, "ck_ops_case_members_bytes"),
        byte_bounds(column("private_json"), 8388608, "ck_ops_case_private_bytes"),
        byte_bounds(column("public_json"), 8388608, "ck_ops_case_public_bytes"),
        CheckConstraint(
            "(status = 'active' AND revision = 1 AND revoked_by IS NULL AND revoked_at IS NULL AND revoke_reason = '' AND revocation_event_id IS NULL) OR (status = 'revoked' AND revision = 2 AND revoked_by IS NOT NULL AND revoked_at IS NOT NULL AND revoke_reason <> '' AND revocation_event_id IS NOT NULL AND revoked_at >= assembled_at)",
            name="ck_ops_case_state",
        ),
        CheckConstraint("revocation_event_id IS NULL OR revocation_event_id <> creation_event_id", name="ck_ops_case_receipts_distinct"),
    )
    op.create_index("idx_ops_case_owner", "hoimsystem_ai_operations_case", ["requested_by", "status", "assembled_at", "case_id"], unique=False)
    op.execute("INSERT INTO hoimsystem_ai_operations_write_gate (gate_id,revision) VALUES (1,1)")


def downgrade():
    op.drop_table("hoimsystem_ai_operations_case")
    op.drop_table("hoimsystem_ai_operations_release")
    op.drop_table("hoimsystem_ai_operations_original")
    op.drop_table("hoimsystem_ai_operations_write_gate")
