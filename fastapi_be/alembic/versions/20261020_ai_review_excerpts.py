"""Versioned manual redaction and review of patient feedback excerpts."""

import sqlalchemy as sa

from alembic import op

revision = "20261020_ai_review_excerpts"
down_revision = "20261020_dose_rule_units"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "hoimsystem_ai_review_excerpt",
        sa.Column("excerpt_id", sa.String(36), primary_key=True),
        sa.Column("review_id", sa.Integer(), sa.ForeignKey("hoimsystem_review.review_id"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("source_hash", sa.String(64), nullable=False),
        sa.Column("department_id", sa.Integer(), sa.ForeignKey("hoimsystem_department.department_id"), nullable=False),
        sa.Column("redacted_text", sa.Text(), nullable=False),
        sa.Column("text_hash", sa.String(64), nullable=False),
        sa.Column("change_note", sa.String(1000), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("privacy_checked", sa.Integer(), nullable=False),
        sa.Column("faithfulness_checked", sa.Integer(), nullable=False),
        sa.Column("review_note", sa.String(1000), nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("hoimsystem_users.user_id"), nullable=False),
        sa.Column("create_time", sa.DateTime(), nullable=False),
        sa.Column("reviewed_by", sa.Integer(), sa.ForeignKey("hoimsystem_users.user_id")),
        sa.Column("reviewed_at", sa.DateTime()),
        sa.Column("retired_by", sa.Integer(), sa.ForeignKey("hoimsystem_users.user_id")),
        sa.Column("retired_at", sa.DateTime()),
        sa.UniqueConstraint("review_id", "version", name="uq_ai_review_excerpt_version"),
    )
    op.create_index("idx_ai_review_excerpt_status_dept", "hoimsystem_ai_review_excerpt", ["status", "department_id"])


def downgrade() -> None:
    op.drop_index("idx_ai_review_excerpt_status_dept", table_name="hoimsystem_ai_review_excerpt")
    op.drop_table("hoimsystem_ai_review_excerpt")
