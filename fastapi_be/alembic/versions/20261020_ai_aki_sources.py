"""Add immutable, explicit adult AKI assessments without changing legacy clinical tables."""

import sqlalchemy as sa
from sqlalchemy.dialects import mysql

from alembic import op

revision = "20261020_ai_aki_sources"
down_revision = "20261020_ai_news2_sources"
branch_labels = None
depends_on = None


def upgrade():
    clock = sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql")
    body = sa.Text().with_variant(mysql.MEDIUMTEXT(), "mysql")
    op.create_table(
        "hoimsystem_ai_aki_assessment",
        sa.Column("assessment_id", sa.String(36), primary_key=True),
        sa.Column("patient_id", sa.Integer(), sa.ForeignKey("hoimsystem_patient.patient_id"), nullable=False),
        sa.Column("admission_id", sa.String(36), sa.ForeignKey("hoimsystem_admission.admission_id"), nullable=False),
        sa.Column("window_id", sa.String(36), sa.ForeignKey("hoimsystem_ai_observation_window.window_id"), nullable=False),
        sa.Column("window_content_hash", sa.String(64), nullable=False),
        sa.Column("rule_profile_id", sa.String(36), sa.ForeignKey("hoimsystem_ai_risk_rule_profile.rule_profile_id"), nullable=False),
        sa.Column("rule_profile_content_hash", sa.String(64), nullable=False),
        sa.Column("recipe_digest", sa.String(64), nullable=False),
        sa.Column("evaluation_at", clock, nullable=False),
        sa.Column("created_at", clock, nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("hoimsystem_users.user_id"), nullable=False),
        sa.Column("schema_version", sa.String(40), nullable=False),
        sa.Column("snapshot_json", body, nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("revoked_at", clock),
        sa.Column("revoked_by", sa.Integer(), sa.ForeignKey("hoimsystem_users.user_id")),
        sa.Column("revoke_reason", sa.String(1000), nullable=False),
        sa.CheckConstraint("evaluation_at <= created_at", name="ck_ai_aki_assessment_time"),
        sa.CheckConstraint(
            "(status = 'active' AND revision = 1 AND revoked_at IS NULL AND revoked_by IS NULL AND revoke_reason = '') OR "
            "(status = 'revoked' AND revision = 2 AND revoked_at IS NOT NULL AND revoked_by IS NOT NULL AND revoke_reason <> '')",
            name="ck_ai_aki_assessment_governance",
        ),
    )
    op.create_index("idx_ai_aki_assessment_scope", "hoimsystem_ai_aki_assessment", ["patient_id", "admission_id", "created_at"])
    op.create_index("idx_ai_aki_assessment_window", "hoimsystem_ai_aki_assessment", ["window_id", "evaluation_at"])


def downgrade():
    op.drop_index("idx_ai_aki_assessment_window", table_name="hoimsystem_ai_aki_assessment")
    op.drop_index("idx_ai_aki_assessment_scope", table_name="hoimsystem_ai_aki_assessment")
    op.drop_table("hoimsystem_ai_aki_assessment")
