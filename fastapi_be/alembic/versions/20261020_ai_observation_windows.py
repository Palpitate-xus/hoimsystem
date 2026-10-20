"""Add immutable, UTC admission-bound observation-window snapshots."""

import sqlalchemy as sa
from sqlalchemy.dialects import mysql

from alembic import op

revision = "20261020_ai_observation_windows"
down_revision = "20261020_inpatient_observations"
branch_labels = None
depends_on = None


def upgrade():
    utc6 = sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql")
    op.create_table(
        "hoimsystem_ai_observation_window",
        sa.Column("window_id", sa.String(36), primary_key=True),
        sa.Column("patient_id", sa.Integer(), sa.ForeignKey("hoimsystem_patient.patient_id"), nullable=False),
        sa.Column("admission_id", sa.String(36), sa.ForeignKey("hoimsystem_admission.admission_id"), nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("hoimsystem_users.user_id"), nullable=False),
        sa.Column("created_at", utc6, nullable=False),
        sa.Column("start_at", utc6, nullable=False),
        sa.Column("end_at", utc6, nullable=False),
        sa.Column("as_of", utc6, nullable=False),
        sa.Column("schema_version", sa.String(40), nullable=False),
        sa.Column("snapshot_json", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("revoked_at", utc6),
        sa.Column("revoked_by", sa.Integer(), sa.ForeignKey("hoimsystem_users.user_id")),
        sa.Column("revoke_reason", sa.String(1000), nullable=False),
        sa.CheckConstraint("start_at < end_at AND end_at <= as_of", name="ck_ai_observation_window_time"),
        sa.CheckConstraint(
            "(status = 'active' AND revision = 1 AND revoked_at IS NULL AND revoked_by IS NULL AND revoke_reason = '') OR (status = 'revoked' AND revision = 2 AND revoked_at IS NOT NULL AND revoked_by IS NOT NULL AND revoke_reason <> '')",
            name="ck_ai_observation_window_governance",
        ),
    )
    op.create_index("idx_ai_observation_window_scope", "hoimsystem_ai_observation_window", ["patient_id", "admission_id", "status"])
    op.create_index("idx_ai_observation_window_created", "hoimsystem_ai_observation_window", ["created_by", "created_at"])


def downgrade():
    op.drop_table("hoimsystem_ai_observation_window")
