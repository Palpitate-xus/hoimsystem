"""Add reviewed rule links and complete finite document comparison scopes."""

import sqlalchemy as sa
from sqlalchemy.dialects import mysql

from alembic import op

revision = "20261021_document_change"
down_revision = "20261021_doc_extraction_runs"
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
        sa.Column("dependency_review", sa.String(20), nullable=False),
        sa.Column("reviewed_by", sa.Integer(), sa.ForeignKey("hoimsystem_users.user_id"), nullable=True),
        sa.Column("reviewed_at", utc6(), nullable=True),
        sa.Column("review_basis_note", sa.Text(), nullable=False),
        sa.Column("revoked_by", sa.Integer(), sa.ForeignKey("hoimsystem_users.user_id"), nullable=True),
        sa.Column("revoked_at", utc6(), nullable=True),
        sa.Column("revoke_reason", sa.String(1000), nullable=False),
        sa.Column("created_audit_event_id", sa.Integer(), sa.ForeignKey("hoimsystem_ai_audit_event.event_id"), nullable=False),
        sa.Column("review_audit_event_id", sa.Integer(), sa.ForeignKey("hoimsystem_ai_audit_event.event_id"), nullable=True),
        sa.Column("revoke_audit_event_id", sa.Integer(), sa.ForeignKey("hoimsystem_ai_audit_event.event_id"), nullable=True),
    ]


def review_constraints(prefix):
    return (
        sa.CheckConstraint(
            "privacy_review IN ('unknown','confirmed','not_confirmed') AND faithfulness_review IN ('unknown','confirmed','not_confirmed') AND dependency_review IN ('unknown','confirmed','not_confirmed') AND ((reviewed_by IS NULL AND reviewed_at IS NULL AND review_basis_note = '' AND privacy_review = 'unknown' AND faithfulness_review = 'unknown' AND dependency_review = 'unknown' AND review_audit_event_id IS NULL) OR (reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL AND review_basis_note <> '' AND privacy_review <> 'unknown' AND faithfulness_review <> 'unknown' AND dependency_review <> 'unknown' AND review_audit_event_id IS NOT NULL))",
            name=f"ck_doc_change_{prefix}_review",
        ),
        sa.CheckConstraint(
            "(status = 'draft' AND revision = 1 AND reviewed_by IS NULL AND revoked_by IS NULL AND revoked_at IS NULL AND revoke_reason = '') OR (status IN ('published','rejected') AND revision = 2 AND reviewed_by IS NOT NULL AND revoked_by IS NULL AND revoked_at IS NULL AND revoke_reason = '') OR (status = 'revoked' AND revoked_by IS NOT NULL AND revoked_at IS NOT NULL AND revoke_reason <> '' AND ((revision = 2 AND reviewed_by IS NULL) OR (revision = 3 AND reviewed_by IS NOT NULL)))",
            name=f"ck_doc_change_{prefix}_states",
        ),
        sa.CheckConstraint(
            "status <> 'published' OR (privacy_review = 'confirmed' AND faithfulness_review = 'confirmed' AND dependency_review = 'confirmed')", name=f"ck_doc_change_{prefix}_published"
        ),
        sa.CheckConstraint("status <> 'rejected' OR privacy_review <> 'confirmed' OR faithfulness_review <> 'confirmed' OR dependency_review <> 'confirmed'", name=f"ck_doc_change_{prefix}_rejected"),
        sa.CheckConstraint(
            "(reviewed_at IS NULL OR reviewed_at >= recorded_at) AND (revoked_at IS NULL OR revoked_at >= recorded_at) AND (reviewed_at IS NULL OR revoked_at IS NULL OR revoked_at >= reviewed_at)",
            name=f"ck_doc_change_{prefix}_clocks",
        ),
        sa.CheckConstraint("(revoked_by IS NULL AND revoke_audit_event_id IS NULL) OR (revoked_by IS NOT NULL AND revoke_audit_event_id IS NOT NULL)", name=f"ck_doc_change_{prefix}_revoke_audit"),
        sa.CheckConstraint(
            "created_audit_event_id > 0 AND (review_audit_event_id IS NULL OR review_audit_event_id > 0) AND (revoke_audit_event_id IS NULL OR revoke_audit_event_id > 0)",
            name=f"ck_doc_change_{prefix}_audit_ids",
        ),
        sa.CheckConstraint("length(review_basis_note) <= 4000 AND length(revoke_reason) <= 1000", name=f"ck_doc_change_{prefix}_notes"),
    )


def upgrade():
    op.create_table(
        "hoimsystem_ai_document_rule_link",
        sa.Column("link_id", sa.String(36), primary_key=True),
        sa.Column("original_id", sa.String(36), nullable=False),
        sa.Column("original_content_hash", sa.String(64), nullable=False),
        sa.Column("original_governance_hash", sa.String(64), nullable=False),
        sa.Column("target_kind", sa.String(32), nullable=False),
        sa.Column("risk_rule_profile_id", sa.String(36), nullable=True),
        sa.Column("clinical_pathway_id", sa.Integer(), nullable=True),
        sa.Column("target_snapshot_hash", sa.String(64), nullable=False),
        sa.Column("span_start", sa.Integer(), nullable=False),
        sa.Column("span_end", sa.Integer(), nullable=False),
        sa.Column("link_json", medium_text(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("hoimsystem_users.user_id"), nullable=False),
        sa.Column("recorded_at", utc6(), nullable=False),
        *review_columns(),
        *review_constraints("link"),
        sa.ForeignKeyConstraint(
            ["original_id", "original_content_hash"], ["hoimsystem_ai_document_original.original_id", "hoimsystem_ai_document_original.content_hash"], name="fk_doc_change_link_original"
        ),
        sa.UniqueConstraint("link_id", "content_hash", name="uq_doc_change_link_hash"),
        sa.CheckConstraint(
            "(target_kind = 'risk_rule_profile' AND risk_rule_profile_id IS NOT NULL AND clinical_pathway_id IS NULL) OR (target_kind = 'clinical_pathway' AND risk_rule_profile_id IS NULL AND clinical_pathway_id IS NOT NULL AND clinical_pathway_id > 0)",
            name="ck_doc_change_link_target",
        ),
        sa.CheckConstraint("span_start >= 0 AND span_end > span_start AND span_end <= 4194304", name="ck_doc_change_link_span"),
        sa.CheckConstraint("length(link_json) > 0 AND length(link_json) <= 1048576", name="ck_doc_change_link_bytes"),
    )
    op.create_index("idx_doc_change_link_original", "hoimsystem_ai_document_rule_link", ["original_id", "link_id"])
    op.create_index("idx_doc_change_link_target", "hoimsystem_ai_document_rule_link", ["target_kind", "risk_rule_profile_id", "clinical_pathway_id"])
    op.create_table(
        "hoimsystem_ai_document_change_scope",
        sa.Column("scope_id", sa.String(36), primary_key=True),
        sa.Column("baseline_original_id", sa.String(36), nullable=False),
        sa.Column("baseline_original_content_hash", sa.String(64), nullable=False),
        sa.Column("baseline_original_governance_hash", sa.String(64), nullable=False),
        sa.Column("candidate_original_id", sa.String(36), nullable=False),
        sa.Column("candidate_original_content_hash", sa.String(64), nullable=False),
        sa.Column("candidate_original_governance_hash", sa.String(64), nullable=False),
        sa.Column("inventory_hash", sa.String(64), nullable=False),
        sa.Column("member_count", sa.Integer(), nullable=False),
        sa.Column("scope_json", medium_text(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("hoimsystem_users.user_id"), nullable=False),
        sa.Column("recorded_at", utc6(), nullable=False),
        *review_columns(),
        *review_constraints("scope"),
        sa.ForeignKeyConstraint(
            ["baseline_original_id", "baseline_original_content_hash"],
            ["hoimsystem_ai_document_original.original_id", "hoimsystem_ai_document_original.content_hash"],
            name="fk_doc_change_scope_baseline",
        ),
        sa.ForeignKeyConstraint(
            ["candidate_original_id", "candidate_original_content_hash"],
            ["hoimsystem_ai_document_original.original_id", "hoimsystem_ai_document_original.content_hash"],
            name="fk_doc_change_scope_candidate",
        ),
        sa.CheckConstraint("baseline_original_id <> candidate_original_id", name="ck_doc_change_scope_two_sources"),
        sa.CheckConstraint("member_count >= 2 AND member_count <= 8192", name="ck_doc_change_scope_members"),
        sa.CheckConstraint("length(scope_json) > 0 AND length(scope_json) <= 8388608", name="ck_doc_change_scope_bytes"),
    )
    op.create_index("idx_doc_change_scope_originals", "hoimsystem_ai_document_change_scope", ["baseline_original_id", "candidate_original_id", "recorded_at"])


def downgrade():
    op.drop_table("hoimsystem_ai_document_change_scope")
    op.drop_table("hoimsystem_ai_document_rule_link")
