"""Add complete bounded SOFA originals and lease-bound results without altering old tables."""

import sqlalchemy as sa
from sqlalchemy.dialects import mysql

from alembic import op

revision = "20261020_sofa_assessments"
down_revision = "20261020_organ_support_sources"
branch_labels = None
depends_on = None


def upgrade():
    clock = sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql")
    complete_json = sa.Text().with_variant(mysql.MEDIUMTEXT(), "mysql")
    op.create_table(
        "hoimsystem_ai_sofa_assessment",
        sa.Column("assessment_id", sa.String(36), primary_key=True),
        sa.Column("patient_id", sa.Integer(), sa.ForeignKey("hoimsystem_patient.patient_id"), nullable=False),
        sa.Column("admission_id", sa.String(36), sa.ForeignKey("hoimsystem_admission.admission_id"), nullable=False),
        sa.Column("rule_profile_id", sa.String(36), sa.ForeignKey("hoimsystem_ai_risk_rule_profile.rule_profile_id"), nullable=False),
        sa.Column("rule_profile_content_hash", sa.String(64), nullable=False),
        sa.Column("recipe_digest", sa.String(64), nullable=False),
        sa.Column("policy_digest", sa.String(64), nullable=False),
        sa.Column("manifest_digest", sa.String(64), nullable=False),
        sa.Column("period_start", clock, nullable=False),
        sa.Column("period_end", clock, nullable=False),
        sa.Column("as_of", clock, nullable=False),
        sa.Column("evaluation_at", clock, nullable=False),
        sa.Column("created_at", clock, nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("hoimsystem_users.user_id"), nullable=False),
        sa.Column("schema_version", sa.String(48), nullable=False),
        sa.Column("snapshot_json", complete_json, nullable=False),
        sa.Column("projection_json", complete_json, nullable=False),
        sa.Column("projection_hash", sa.String(64), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("revoked_at", clock, nullable=True),
        sa.Column("revoked_by", sa.Integer(), sa.ForeignKey("hoimsystem_users.user_id"), nullable=True),
        sa.Column("revoke_reason", sa.String(1000), nullable=False),
        sa.CheckConstraint(
            "(status = 'active' AND revision = 1 AND revoked_at IS NULL AND revoked_by IS NULL AND revoke_reason = '') OR (status = 'revoked' AND revision = 2 AND revoked_at IS NOT NULL AND revoked_by IS NOT NULL AND revoke_reason <> '')",
            name="ck_ai_sofa_assessment_governance",
        ),
        sa.CheckConstraint("period_start < period_end AND period_end <= as_of AND as_of <= evaluation_at AND evaluation_at <= created_at", name="ck_ai_sofa_assessment_clocks"),
        sa.CheckConstraint("revoked_at IS NULL OR revoked_at >= created_at", name="ck_ai_sofa_assessment_revocation_clock"),
        sa.CheckConstraint("length(snapshot_json) <= 8388608 AND length(projection_json) <= 2097152", name="ck_ai_sofa_assessment_json_bounds"),
    )
    op.create_index("idx_ai_sofa_assessment_scope", "hoimsystem_ai_sofa_assessment", ["patient_id", "admission_id", "created_at"])
    op.create_index("idx_ai_sofa_assessment_profile", "hoimsystem_ai_sofa_assessment", ["rule_profile_id", "status"])
    op.create_table(
        "hoimsystem_ai_sofa_change_assessment",
        sa.Column("change_assessment_id", sa.String(36), primary_key=True),
        sa.Column("patient_id", sa.Integer(), sa.ForeignKey("hoimsystem_patient.patient_id"), nullable=False),
        sa.Column("admission_id", sa.String(36), sa.ForeignKey("hoimsystem_admission.admission_id"), nullable=False),
        sa.Column("current_assessment_id", sa.String(36), sa.ForeignKey("hoimsystem_ai_sofa_assessment.assessment_id"), nullable=False),
        sa.Column("baseline_assessment_id", sa.String(36), sa.ForeignKey("hoimsystem_ai_sofa_assessment.assessment_id"), nullable=True),
        sa.Column("infection_source_id", sa.String(36), sa.ForeignKey("hoimsystem_inpatient_infection_episode_source.support_source_id"), nullable=False),
        sa.Column("evaluation_at", clock, nullable=False),
        sa.Column("created_at", clock, nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("hoimsystem_users.user_id"), nullable=False),
        sa.Column("schema_version", sa.String(48), nullable=False),
        sa.Column("snapshot_json", complete_json, nullable=False),
        sa.Column("projection_json", complete_json, nullable=False),
        sa.Column("projection_hash", sa.String(64), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("revoked_at", clock, nullable=True),
        sa.Column("revoked_by", sa.Integer(), sa.ForeignKey("hoimsystem_users.user_id"), nullable=True),
        sa.Column("revoke_reason", sa.String(1000), nullable=False),
        sa.CheckConstraint(
            "(status = 'active' AND revision = 1 AND revoked_at IS NULL AND revoked_by IS NULL AND revoke_reason = '') OR (status = 'revoked' AND revision = 2 AND revoked_at IS NOT NULL AND revoked_by IS NOT NULL AND revoke_reason <> '')",
            name="ck_ai_sofa_change_governance",
        ),
        sa.CheckConstraint("evaluation_at <= created_at AND (revoked_at IS NULL OR revoked_at >= created_at)", name="ck_ai_sofa_change_clocks"),
        sa.CheckConstraint("length(snapshot_json) <= 8388608 AND length(projection_json) <= 6291456", name="ck_ai_sofa_change_json_bounds"),
    )
    op.create_index("idx_ai_sofa_change_scope", "hoimsystem_ai_sofa_change_assessment", ["patient_id", "admission_id", "created_at"])
    op.create_index("idx_ai_sofa_change_current", "hoimsystem_ai_sofa_change_assessment", ["current_assessment_id", "status"])
    op.create_table(
        "hoimsystem_ai_sofa_run_result",
        sa.Column("run_id", sa.String(36), sa.ForeignKey("hoimsystem_ai_run.run_id"), primary_key=True),
        sa.Column("lease_token", sa.String(36), nullable=False),
        sa.Column("schema_version", sa.String(48), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("result_json", complete_json, nullable=False),
        sa.Column("result_bytes", sa.Integer(), nullable=False),
        sa.Column("created_at", clock, nullable=False),
        sa.CheckConstraint("result_bytes > 0 AND result_bytes <= 8388608 AND length(result_json) <= 8388608", name="ck_ai_sofa_result_json_bounds"),
    )
    op.create_index("idx_ai_sofa_result_created", "hoimsystem_ai_sofa_run_result", ["created_at"])


def downgrade():
    op.drop_table("hoimsystem_ai_sofa_run_result")
    op.drop_table("hoimsystem_ai_sofa_change_assessment")
    op.drop_table("hoimsystem_ai_sofa_assessment")
