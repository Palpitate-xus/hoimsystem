"""Add fixed risk-rule profiles and explicit NEWS2 assessment sources; no legacy rewrite."""

import sqlalchemy as sa
from sqlalchemy.dialects import mysql

from alembic import op

revision = "20261020_ai_news2_sources"
down_revision = "20261020_inpatient_laboratory"
branch_labels = None
depends_on = None


def upgrade():
    utc6 = sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql")
    medium = sa.Text().with_variant(mysql.MEDIUMTEXT(), "mysql")
    op.create_table(
        "hoimsystem_ai_risk_rule_profile",
        sa.Column("rule_profile_id", sa.String(36), primary_key=True),
        sa.Column("schema_version", sa.String(40), nullable=False),
        sa.Column("rule_id", sa.String(80), nullable=False),
        sa.Column("recipe_digest", sa.String(64), nullable=False),
        sa.Column("policy_digest", sa.String(64), nullable=False),
        sa.Column("identity_hash", sa.String(64), nullable=False),
        sa.Column("published_key", sa.String(64)),
        sa.Column("payload_json", medium, nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("hoimsystem_users.user_id"), nullable=False),
        sa.Column("created_at", utc6, nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("published_at", utc6),
        sa.Column("published_by", sa.Integer(), sa.ForeignKey("hoimsystem_users.user_id")),
        sa.Column("review_note", sa.String(2000), nullable=False),
        sa.Column("review_evidence_reference", sa.String(2000), nullable=False),
        sa.Column("implementation_terms_confirmed", sa.Integer(), nullable=False),
        sa.Column("revoked_at", utc6),
        sa.Column("revoked_by", sa.Integer(), sa.ForeignKey("hoimsystem_users.user_id")),
        sa.Column("revoke_reason", sa.String(1000), nullable=False),
        sa.UniqueConstraint("published_key", name="uq_ai_risk_rule_published"),
        sa.CheckConstraint("(published_at IS NULL AND implementation_terms_confirmed = 0) OR (published_at IS NOT NULL AND implementation_terms_confirmed = 1)", name="ck_ai_risk_rule_terms"),
        sa.CheckConstraint(
            "(status = 'draft' AND revision = 1 AND published_key IS NULL AND published_at IS NULL AND published_by IS NULL AND review_note = '' AND review_evidence_reference = '' AND revoked_at IS NULL AND revoked_by IS NULL AND revoke_reason = '') OR "
            "(status = 'published' AND revision = 2 AND published_key = identity_hash AND published_key IS NOT NULL AND published_at IS NOT NULL AND published_by IS NOT NULL AND review_note <> '' AND review_evidence_reference <> '' AND revoked_at IS NULL AND revoked_by IS NULL AND revoke_reason = '') OR "
            "(status = 'revoked' AND published_key IS NULL AND revoked_at IS NOT NULL AND revoked_by IS NOT NULL AND revoke_reason <> '' AND ((revision = 2 AND published_at IS NULL AND published_by IS NULL AND review_note = '' AND review_evidence_reference = '') OR (revision = 3 AND published_at IS NOT NULL AND published_by IS NOT NULL AND review_note <> '' AND review_evidence_reference <> '')))",
            name="ck_ai_risk_rule_governance",
        ),
    )
    op.create_index("idx_ai_risk_rule_status", "hoimsystem_ai_risk_rule_profile", ["rule_id", "status"])
    op.create_table(
        "hoimsystem_ai_news2_assessment",
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
        sa.Column("observed_at", utc6, nullable=False),
        sa.Column("created_at", utc6, nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("hoimsystem_users.user_id"), nullable=False),
        sa.Column("schema_version", sa.String(40), nullable=False),
        sa.Column("snapshot_json", medium, nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("revoked_at", utc6),
        sa.Column("revoked_by", sa.Integer(), sa.ForeignKey("hoimsystem_users.user_id")),
        sa.Column("revoke_reason", sa.String(1000), nullable=False),
        sa.CheckConstraint("observed_at <= created_at", name="ck_ai_news2_assessment_time"),
        sa.CheckConstraint(
            "(status = 'active' AND revision = 1 AND revoked_at IS NULL AND revoked_by IS NULL AND revoke_reason = '') OR (status = 'revoked' AND revision = 2 AND revoked_at IS NOT NULL AND revoked_by IS NOT NULL AND revoke_reason <> '')",
            name="ck_ai_news2_assessment_governance",
        ),
    )
    op.create_index("idx_ai_news2_assessment_scope", "hoimsystem_ai_news2_assessment", ["patient_id", "admission_id", "created_at"])
    op.create_index("idx_ai_news2_assessment_window", "hoimsystem_ai_news2_assessment", ["window_id", "point_id"])


def downgrade():
    op.drop_table("hoimsystem_ai_news2_assessment")
    op.drop_table("hoimsystem_ai_risk_rule_profile")
