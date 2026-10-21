"""Add exact UTF8 originals, reviewed spans and bound knowledge publications."""

import sqlalchemy as sa
from sqlalchemy.dialects import mysql

from alembic import op

revision = "20261021_document_evidence"
down_revision = "20261021_coding_evidence"
branch_labels = None
depends_on = None


def utc6():
    return sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql")


def medium_text():
    return sa.Text().with_variant(mysql.MEDIUMTEXT(), "mysql")


def review_columns():
    return [
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("privacy_review", sa.String(20), nullable=False),
        sa.Column("faithfulness_review", sa.String(20), nullable=False),
        sa.Column("reviewed_by", sa.Integer(), sa.ForeignKey("hoimsystem_users.user_id"), nullable=True),
        sa.Column("reviewed_at", utc6(), nullable=True),
        sa.Column("review_basis_note", sa.Text(), nullable=False),
        sa.Column("revoked_by", sa.Integer(), sa.ForeignKey("hoimsystem_users.user_id"), nullable=True),
        sa.Column("revoked_at", utc6(), nullable=True),
        sa.Column("revoke_reason", sa.String(1000), nullable=False),
    ]


def review_constraints(prefix, approved):
    return [
        sa.CheckConstraint(
            "privacy_review IN ('unknown','confirmed','not_confirmed') AND faithfulness_review IN ('unknown','confirmed','not_confirmed') AND "
            "((reviewed_by IS NULL AND reviewed_at IS NULL AND review_basis_note = '' AND privacy_review = 'unknown' AND faithfulness_review = 'unknown') OR "
            "(reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL AND review_basis_note <> '' AND privacy_review <> 'unknown' AND faithfulness_review <> 'unknown'))",
            name=f"ck_doc_{prefix}_review_signature",
        ),
        sa.CheckConstraint(
            f"(status = 'draft' AND revision = 1 AND reviewed_by IS NULL AND revoked_by IS NULL AND revoked_at IS NULL AND revoke_reason = '') OR "
            f"(status IN ('{approved}','rejected') AND revision = 2 AND reviewed_by IS NOT NULL AND revoked_by IS NULL AND revoked_at IS NULL AND revoke_reason = '') OR "
            "(status = 'revoked' AND revoked_by IS NOT NULL AND revoked_at IS NOT NULL AND revoke_reason <> '' AND ((revision = 2 AND reviewed_by IS NULL) OR (revision = 3 AND reviewed_by IS NOT NULL)))",
            name=f"ck_doc_{prefix}_governance",
        ),
        sa.CheckConstraint(f"status <> '{approved}' OR (privacy_review = 'confirmed' AND faithfulness_review = 'confirmed')", name=f"ck_doc_{prefix}_approved_reviews"),
        sa.CheckConstraint("status <> 'rejected' OR privacy_review <> 'confirmed' OR faithfulness_review <> 'confirmed'", name=f"ck_doc_{prefix}_rejected_review"),
        sa.CheckConstraint(
            "(reviewed_at IS NULL OR reviewed_at >= recorded_at) AND (revoked_at IS NULL OR revoked_at >= recorded_at) AND (reviewed_at IS NULL OR revoked_at IS NULL OR revoked_at >= reviewed_at)",
            name=f"ck_doc_{prefix}_clocks",
        ),
        sa.CheckConstraint("length(review_basis_note) <= 4000 AND length(revoke_reason) <= 4000", name=f"ck_doc_{prefix}_basis_bytes"),
    ]


def upgrade():
    op.create_table(
        "hoimsystem_ai_document_original",
        sa.Column("original_id", sa.String(36), primary_key=True),
        sa.Column("identity_json", sa.Text(), nullable=False),
        sa.Column("original_text", medium_text(), nullable=False),
        sa.Column("raw_bytes_hash", sa.String(64), nullable=False),
        sa.Column("raw_bytes_length", sa.Integer(), nullable=False),
        sa.Column("codepoint_length", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("hoimsystem_users.user_id"), nullable=False),
        sa.Column("recorded_at", utc6(), nullable=False),
        *review_columns(),
        *review_constraints("original", "published"),
        sa.UniqueConstraint("original_id", "content_hash", name="uq_doc_original_hash"),
        sa.CheckConstraint("raw_bytes_length > 0 AND raw_bytes_length <= 4194304 AND codepoint_length > 0 AND codepoint_length <= 4194304", name="ck_doc_original_raw_bounds"),
        sa.CheckConstraint("length(original_text) > 0 AND length(original_text) <= 4194304 AND length(identity_json) > 0 AND length(identity_json) <= 65535", name="ck_doc_original_storage"),
    )
    op.create_index("idx_doc_original_governance", "hoimsystem_ai_document_original", ["status", "recorded_at", "original_id"])
    op.create_table(
        "hoimsystem_ai_document_span_candidate",
        sa.Column("candidate_id", sa.String(36), primary_key=True),
        sa.Column("original_id", sa.String(36), nullable=False),
        sa.Column("original_content_hash", sa.String(64), nullable=False),
        sa.Column("original_governance_hash", sa.String(64), nullable=False),
        sa.Column("span_start", sa.Integer(), nullable=False),
        sa.Column("span_end", sa.Integer(), nullable=False),
        sa.Column("candidate_json", medium_text(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("hoimsystem_users.user_id"), nullable=False),
        sa.Column("recorded_at", utc6(), nullable=False),
        *review_columns(),
        *review_constraints("candidate", "approved"),
        sa.ForeignKeyConstraint(
            ["original_id", "original_content_hash"], ["hoimsystem_ai_document_original.original_id", "hoimsystem_ai_document_original.content_hash"], name="fk_doc_candidate_original_hash"
        ),
        sa.UniqueConstraint("candidate_id", "original_id", "content_hash", name="uq_doc_candidate_original_hash"),
        sa.CheckConstraint(
            "span_start >= 0 AND span_end > span_start AND span_end <= 4194304 AND length(candidate_json) > 0 AND length(candidate_json) <= 131072", name="ck_doc_candidate_span_storage"
        ),
    )
    op.create_index("idx_doc_candidate_original", "hoimsystem_ai_document_span_candidate", ["original_id", "status", "recorded_at"])
    op.create_table(
        "hoimsystem_ai_document_knowledge_publication",
        sa.Column("publication_id", sa.String(36), primary_key=True),
        sa.Column("original_id", sa.String(36), nullable=False),
        sa.Column("original_content_hash", sa.String(64), nullable=False),
        sa.Column("candidate_id", sa.String(36), nullable=False),
        sa.Column("candidate_content_hash", sa.String(64), nullable=False),
        sa.Column("knowledge_document_id", sa.String(36), sa.ForeignKey("hoimsystem_ai_knowledge_document.document_id"), nullable=False),
        sa.Column("publication_json", medium_text(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("published_by", sa.Integer(), sa.ForeignKey("hoimsystem_users.user_id"), nullable=False),
        sa.Column("published_at", utc6(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("revoked_by", sa.Integer(), sa.ForeignKey("hoimsystem_users.user_id"), nullable=True),
        sa.Column("revoked_at", utc6(), nullable=True),
        sa.Column("revoke_reason", sa.String(1000), nullable=False),
        sa.ForeignKeyConstraint(
            ["original_id", "original_content_hash"], ["hoimsystem_ai_document_original.original_id", "hoimsystem_ai_document_original.content_hash"], name="fk_doc_publication_original_hash"
        ),
        sa.ForeignKeyConstraint(
            ["candidate_id", "original_id", "candidate_content_hash"],
            ["hoimsystem_ai_document_span_candidate.candidate_id", "hoimsystem_ai_document_span_candidate.original_id", "hoimsystem_ai_document_span_candidate.content_hash"],
            name="fk_doc_publication_candidate_hash",
        ),
        sa.UniqueConstraint("candidate_id", name="uq_doc_publication_candidate"),
        sa.UniqueConstraint("knowledge_document_id", name="uq_doc_publication_knowledge"),
        sa.CheckConstraint("length(publication_json) > 0 AND length(publication_json) <= 196608", name="ck_doc_publication_storage"),
        sa.CheckConstraint(
            "(status = 'active' AND revision = 1 AND revoked_by IS NULL AND revoked_at IS NULL AND revoke_reason = '') OR "
            "(status = 'revoked' AND revision = 2 AND revoked_by IS NOT NULL AND revoked_at IS NOT NULL AND revoked_at >= published_at AND revoke_reason <> '')",
            name="ck_doc_publication_governance",
        ),
    )
    op.create_index("idx_doc_publication_original", "hoimsystem_ai_document_knowledge_publication", ["original_id", "status"])


def downgrade():
    op.drop_table("hoimsystem_ai_document_knowledge_publication")
    op.drop_table("hoimsystem_ai_document_span_candidate")
    op.drop_table("hoimsystem_ai_document_original")
