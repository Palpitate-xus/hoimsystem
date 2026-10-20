"""Add original ward GCS and retrospective qSOFA reviews; preserve all legacy clinical facts."""

import sqlalchemy as sa
from sqlalchemy.dialects import mysql

from alembic import op

revision = "20261020_qsofa_sources"
down_revision = "20261020_ai_aki_sources"
branch_labels = None
depends_on = None


def upgrade():
    clock = sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql")
    op.create_table(
        "hoimsystem_inpatient_gcs_observation",
        sa.Column("gcs_observation_id", sa.String(36), primary_key=True),
        sa.Column("patient_id", sa.Integer(), sa.ForeignKey("hoimsystem_patient.patient_id"), nullable=False),
        sa.Column("admission_id", sa.String(36), sa.ForeignKey("hoimsystem_admission.admission_id"), nullable=False),
        sa.Column("observed_at", clock, nullable=False),
        sa.Column("recorded_at", clock, nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("hoimsystem_users.user_id"), nullable=False),
        sa.Column("schema_version", sa.String(40), nullable=False),
        sa.Column("anchor_point_id", sa.String(36), sa.ForeignKey("hoimsystem_inpatient_observation.observation_id")),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("anchor_snapshot_json", sa.Text()),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("revoked_at", clock),
        sa.Column("revoked_by", sa.Integer(), sa.ForeignKey("hoimsystem_users.user_id")),
        sa.Column("revoke_reason", sa.String(1000), nullable=False),
        sa.CheckConstraint("observed_at <= recorded_at", name="ck_inpatient_gcs_time"),
        sa.CheckConstraint(
            "(status = 'active' AND revision = 1 AND revoked_at IS NULL AND revoked_by IS NULL AND revoke_reason = '') OR "
            "(status = 'revoked' AND revision = 2 AND revoked_at IS NOT NULL AND revoked_by IS NOT NULL AND revoke_reason <> '')",
            name="ck_inpatient_gcs_governance",
        ),
    )
    op.create_index("idx_inpatient_gcs_scope", "hoimsystem_inpatient_gcs_observation", ["patient_id", "admission_id", "observed_at"])
    op.create_index("idx_inpatient_gcs_anchor", "hoimsystem_inpatient_gcs_observation", ["anchor_point_id", "recorded_at", "gcs_observation_id"])
    op.create_table(
        "hoimsystem_ai_qsofa_assessment",
        sa.Column("assessment_id", sa.String(36), primary_key=True),
        sa.Column("patient_id", sa.Integer(), sa.ForeignKey("hoimsystem_patient.patient_id"), nullable=False),
        sa.Column("admission_id", sa.String(36), sa.ForeignKey("hoimsystem_admission.admission_id"), nullable=False),
        sa.Column("window_id", sa.String(36), sa.ForeignKey("hoimsystem_ai_observation_window.window_id"), nullable=False),
        sa.Column("window_content_hash", sa.String(64), nullable=False),
        sa.Column("point_id", sa.String(36), sa.ForeignKey("hoimsystem_inpatient_observation.observation_id"), nullable=False),
        sa.Column("point_content_hash", sa.String(64), nullable=False),
        sa.Column("rule_profile_id", sa.String(36), sa.ForeignKey("hoimsystem_ai_risk_rule_profile.rule_profile_id"), nullable=False),
        sa.Column("rule_profile_content_hash", sa.String(64), nullable=False),
        sa.Column("recipe_digest", sa.String(64), nullable=False),
        sa.Column("evaluation_at", clock, nullable=False),
        sa.Column("created_at", clock, nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("hoimsystem_users.user_id"), nullable=False),
        sa.Column("schema_version", sa.String(40), nullable=False),
        sa.Column("snapshot_json", sa.Text().with_variant(mysql.MEDIUMTEXT(), "mysql"), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("revoked_at", clock),
        sa.Column("revoked_by", sa.Integer(), sa.ForeignKey("hoimsystem_users.user_id")),
        sa.Column("revoke_reason", sa.String(1000), nullable=False),
        sa.CheckConstraint("evaluation_at = created_at", name="ck_ai_qsofa_review_time"),
        sa.CheckConstraint(
            "(status = 'active' AND revision = 1 AND revoked_at IS NULL AND revoked_by IS NULL AND revoke_reason = '') OR "
            "(status = 'revoked' AND revision = 2 AND revoked_at IS NOT NULL AND revoked_by IS NOT NULL AND revoke_reason <> '')",
            name="ck_ai_qsofa_governance",
        ),
    )
    op.create_index("idx_ai_qsofa_scope", "hoimsystem_ai_qsofa_assessment", ["patient_id", "admission_id", "created_at"])
    op.create_index("idx_ai_qsofa_window", "hoimsystem_ai_qsofa_assessment", ["window_id", "point_id"])


def downgrade():
    op.drop_table("hoimsystem_ai_qsofa_assessment")
    op.drop_table("hoimsystem_inpatient_gcs_observation")
