"""Add original physical bed observations without changing live ward tables."""

import sqlalchemy as sa
from sqlalchemy.dialects import mysql

from alembic import op

revision = "20261020_bed_sources"
down_revision = "20261020_roster_plans"
branch_labels = None
depends_on = None


def upgrade():
    clock = sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql")
    original = sa.Text().with_variant(mysql.MEDIUMTEXT(), "mysql")
    op.create_table(
        "hoimsystem_ai_bed_source",
        sa.Column("source_record_id", sa.String(36), primary_key=True),
        sa.Column("source_kind", sa.String(32), nullable=False),
        sa.Column("department_id", sa.Integer(), sa.ForeignKey("hoimsystem_department.department_id"), nullable=False),
        sa.Column("ward_id", sa.Integer(), sa.ForeignKey("hoimsystem_ward.ward_id"), nullable=False),
        sa.Column("schema_version", sa.String(40), nullable=False),
        sa.Column("payload_json", original, nullable=False),
        sa.Column("parent_binding_json", original, nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("recorded_at", clock, nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("hoimsystem_users.user_id"), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("reviewed_by", sa.Integer(), sa.ForeignKey("hoimsystem_users.user_id"), nullable=True),
        sa.Column("reviewed_at", clock, nullable=True),
        sa.Column("review_basis_note", sa.Text(), nullable=False),
        sa.Column("revoked_by", sa.Integer(), sa.ForeignKey("hoimsystem_users.user_id"), nullable=True),
        sa.Column("revoked_at", clock, nullable=True),
        sa.Column("revoke_reason", sa.String(1000), nullable=False),
        sa.CheckConstraint("source_kind IN ('census','flow_day','capacity_interval')", name="ck_ai_bed_source_kind"),
        sa.CheckConstraint(
            "(status = 'draft' AND revision = 1 AND reviewed_at IS NULL AND reviewed_by IS NULL AND review_basis_note = '' "
            "AND revoked_at IS NULL AND revoked_by IS NULL AND revoke_reason = '') OR "
            "(status IN ('published','rejected') AND revision = 2 AND reviewed_at IS NOT NULL AND reviewed_by IS NOT NULL AND review_basis_note <> '' "
            "AND revoked_at IS NULL AND revoked_by IS NULL AND revoke_reason = '') OR "
            "(status = 'revoked' AND revoked_at IS NOT NULL AND revoked_by IS NOT NULL AND revoke_reason <> '' AND "
            "((revision = 2 AND reviewed_at IS NULL AND reviewed_by IS NULL AND review_basis_note = '') OR "
            "(revision = 3 AND reviewed_at IS NOT NULL AND reviewed_by IS NOT NULL AND review_basis_note <> '')))",
            name="ck_ai_bed_source_governance",
        ),
        sa.CheckConstraint(
            "(reviewed_at IS NULL OR reviewed_at >= recorded_at) AND (revoked_at IS NULL OR revoked_at >= recorded_at) AND (reviewed_at IS NULL OR revoked_at IS NULL OR revoked_at >= reviewed_at)",
            name="ck_ai_bed_source_clocks",
        ),
        sa.CheckConstraint(
            "length(payload_json) > 0 AND length(payload_json) <= 262144 AND length(parent_binding_json) > 0 AND length(parent_binding_json) <= 32768 AND length(review_basis_note) <= 4000",
            name="ck_ai_bed_source_bounds",
        ),
    )
    op.create_index("idx_ai_bed_source_scope", "hoimsystem_ai_bed_source", ["department_id", "ward_id", "source_kind", "recorded_at"])
    op.create_index("idx_ai_bed_source_ward_status", "hoimsystem_ai_bed_source", ["ward_id", "source_kind", "status"])


def downgrade():
    op.drop_table("hoimsystem_ai_bed_source")
