"""Register immutable reviewed laboratory originals without rewriting legacy clocks or values."""

import sqlalchemy as sa
from sqlalchemy.dialects import mysql

from alembic import op

revision = "20261020_inpatient_laboratory"
down_revision = "20261020_ai_lab_mappings"
branch_labels = None
depends_on = None


def upgrade():
    precise = sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql")
    table = "hoimsystem_inpatient_lab_source"
    op.create_table(
        table,
        sa.Column("lab_source_id", sa.String(36), primary_key=True),
        sa.Column("patient_id", sa.Integer(), sa.ForeignKey("hoimsystem_patient.patient_id"), nullable=False),
        sa.Column("admission_id", sa.String(36), sa.ForeignKey("hoimsystem_admission.admission_id"), nullable=False),
        sa.Column("observation_id", sa.String(36), sa.ForeignKey("hoimsystem_lab_observation.observation_id"), nullable=False),
        sa.Column("active_observation_id", sa.String(36)),
        sa.Column("mapping_id", sa.String(36), sa.ForeignKey("hoimsystem_ai_lab_mapping.mapping_id"), nullable=False),
        sa.Column("collected_at_utc", precise, nullable=False),
        sa.Column("registered_at", precise, nullable=False),
        sa.Column("available_at", precise, nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("hoimsystem_users.user_id"), nullable=False),
        sa.Column("schema_version", sa.String(40), nullable=False, server_default="inpatient_lab_source_v1"),
        sa.Column("raw_original_hash", sa.String(64), nullable=False),
        sa.Column("mapping_content_hash", sa.String(64), nullable=False),
        sa.Column("snapshot_json", sa.Text().with_variant(mysql.MEDIUMTEXT(), "mysql"), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("revoked_at", precise),
        sa.Column("revoked_by", sa.Integer(), sa.ForeignKey("hoimsystem_users.user_id")),
        sa.Column("revoke_reason", sa.String(1000), nullable=False, server_default=""),
        sa.UniqueConstraint("active_observation_id", name="uq_inpatient_lab_active_observation"),
        sa.CheckConstraint("collected_at_utc <= registered_at AND available_at = registered_at", name="ck_inpatient_lab_time"),
        sa.CheckConstraint(
            "(status = 'active' AND revision = 1 AND active_observation_id = observation_id AND active_observation_id IS NOT NULL AND revoked_at IS NULL AND revoked_by IS NULL AND revoke_reason = '') OR "
            "(status = 'revoked' AND revision = 2 AND active_observation_id IS NULL AND revoked_at IS NOT NULL AND revoked_by IS NOT NULL AND revoke_reason <> '')",
            name="ck_inpatient_lab_governance",
        ),
    )
    op.create_index("idx_inpatient_lab_scope_time", table, ["patient_id", "admission_id", "collected_at_utc", "lab_source_id"])
    op.create_index("idx_inpatient_lab_registered", table, ["registered_at", "available_at"])


def downgrade():
    op.drop_table("hoimsystem_inpatient_lab_source")
