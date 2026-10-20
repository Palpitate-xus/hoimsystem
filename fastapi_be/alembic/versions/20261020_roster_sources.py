"""Add reviewed workforce originals without changing live scheduling tables."""

import sqlalchemy as sa
from sqlalchemy.dialects import mysql

from alembic import op

revision = "20261020_roster_sources"
down_revision = "20261020_sofa_assessments"
branch_labels = None
depends_on = None


def upgrade():
    clock = sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql")
    original = sa.Text().with_variant(mysql.MEDIUMTEXT(), "mysql")
    op.create_table(
        "hoimsystem_ai_roster_source",
        sa.Column("source_record_id", sa.String(36), primary_key=True),
        sa.Column("source_kind", sa.String(32), nullable=False),
        sa.Column("department_id", sa.Integer(), sa.ForeignKey("hoimsystem_department.department_id"), nullable=False),
        sa.Column("doctor_id", sa.Integer(), sa.ForeignKey("hoimsystem_doctor.doctor_id"), nullable=True),
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
        sa.CheckConstraint("source_kind IN ('qualification','duty_interval','availability','work_rule_policy')", name="ck_ai_roster_source_kind"),
        sa.CheckConstraint("source_kind = 'work_rule_policy' OR doctor_id IS NOT NULL", name="ck_ai_roster_source_subject"),
        sa.CheckConstraint(
            "(status = 'draft' AND revision = 1 AND reviewed_at IS NULL AND reviewed_by IS NULL AND review_basis_note = '' "
            "AND revoked_at IS NULL AND revoked_by IS NULL AND revoke_reason = '') OR "
            "(status IN ('published','rejected') AND revision = 2 AND reviewed_at IS NOT NULL AND reviewed_by IS NOT NULL AND review_basis_note <> '' "
            "AND revoked_at IS NULL AND revoked_by IS NULL AND revoke_reason = '') OR "
            "(status = 'revoked' AND revoked_at IS NOT NULL AND revoked_by IS NOT NULL AND revoke_reason <> '' AND "
            "((revision = 2 AND reviewed_at IS NULL AND reviewed_by IS NULL AND review_basis_note = '') OR "
            "(revision = 3 AND reviewed_at IS NOT NULL AND reviewed_by IS NOT NULL AND review_basis_note <> '')))",
            name="ck_ai_roster_source_governance",
        ),
        sa.CheckConstraint(
            "(reviewed_at IS NULL OR reviewed_at >= recorded_at) AND (revoked_at IS NULL OR revoked_at >= recorded_at) AND (reviewed_at IS NULL OR revoked_at IS NULL OR revoked_at >= reviewed_at)",
            name="ck_ai_roster_source_clocks",
        ),
        sa.CheckConstraint("length(payload_json) <= 262144 AND length(parent_binding_json) <= 32768 AND length(review_basis_note) <= 4000", name="ck_ai_roster_source_bounds"),
    )
    op.create_index("idx_ai_roster_source_scope", "hoimsystem_ai_roster_source", ["department_id", "source_kind", "recorded_at"])
    op.create_index("idx_ai_roster_source_subject", "hoimsystem_ai_roster_source", ["doctor_id", "source_kind", "status"])


def downgrade():
    op.drop_table("hoimsystem_ai_roster_source")
