"""Add independent immutable inpatient point observations and original urine intervals."""

import sqlalchemy as sa
from sqlalchemy.dialects import mysql

from alembic import op

revision = "20261020_inpatient_observations"
down_revision = "20261020_ai_forecast_series"
branch_labels = None
depends_on = None


def _columns(identifier, version):
    precise = sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql")
    return [
        sa.Column(identifier, sa.String(36), primary_key=True),
        sa.Column("patient_id", sa.Integer(), sa.ForeignKey("hoimsystem_patient.patient_id"), nullable=False),
        sa.Column("admission_id", sa.String(36), sa.ForeignKey("hoimsystem_admission.admission_id"), nullable=False),
        sa.Column("recorded_at", precise, nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("hoimsystem_users.user_id"), nullable=False),
        sa.Column("schema_version", sa.String(40), nullable=False, server_default=version),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("revoked_at", precise, nullable=True),
        sa.Column("revoked_by", sa.Integer(), sa.ForeignKey("hoimsystem_users.user_id"), nullable=True),
        sa.Column("revoke_reason", sa.String(1000), nullable=False, server_default=""),
    ]


def _governance(prefix):
    return [
        sa.CheckConstraint("status IN ('active', 'revoked')", name=f"ck_{prefix}_status"),
        sa.CheckConstraint(
            "(status = 'active' AND revision = 1 AND revoked_at IS NULL AND revoked_by IS NULL AND revoke_reason = '') OR "
            "(status = 'revoked' AND revision = 2 AND revoked_at IS NOT NULL AND revoked_by IS NOT NULL AND revoke_reason <> '')",
            name=f"ck_{prefix}_revocation",
        ),
    ]


def upgrade():
    precise = sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql")
    point = "hoimsystem_inpatient_observation"
    urine = "hoimsystem_inpatient_urine_interval"
    op.create_table(point, *_columns("observation_id", "inpatient_observation_v1"), sa.Column("observed_at", precise, nullable=False), *_governance("inpatient_observation"))
    op.create_index("idx_inpatient_observation_admission_time", point, ["admission_id", "observed_at", "observation_id"])
    op.create_index("idx_inpatient_observation_patient_status", point, ["patient_id", "status"])
    op.create_table(
        urine,
        *_columns("interval_id", "urine_interval_v1"),
        sa.Column("start_at", precise, nullable=False),
        sa.Column("end_at", precise, nullable=False),
        sa.CheckConstraint("start_at < end_at", name="ck_inpatient_urine_interval_time"),
        *_governance("inpatient_urine_interval"),
    )
    op.create_index("idx_inpatient_urine_interval_admission_time", urine, ["admission_id", "start_at", "end_at", "interval_id"])
    op.create_index("idx_inpatient_urine_interval_patient_status", urine, ["patient_id", "status"])


def downgrade():
    # Only independent extension tables are removed. No legacy observation or
    # admission is inferred, rewritten, backfilled or assigned a timezone.
    op.drop_table("hoimsystem_inpatient_urine_interval")
    op.drop_table("hoimsystem_inpatient_observation")
