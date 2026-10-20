"""Add six independent governed original-source tables without altering clinical originals."""

import sqlalchemy as sa
from sqlalchemy.dialects import mysql

from alembic import op

revision = "20261020_organ_support_sources"
down_revision = "20261020_qsofa_sources"
branch_labels = None
depends_on = None

CLINICAL_TABLES = (
    ("hoimsystem_inpatient_map_source", "inpatient_map", True),
    ("hoimsystem_inpatient_respiratory_source", "inpatient_respiratory", True),
    ("hoimsystem_inpatient_arterial_pair_source", "inpatient_arterial_pair", True),
    ("hoimsystem_inpatient_vasoactive_source", "vasoactive_source", False),
    ("hoimsystem_inpatient_infection_episode_source", "inpatient_infection_episode", True),
)
MAPPING_TABLE = "hoimsystem_ai_vasoactive_drug_mapping"


def _clinical_source(table_name, prefix, server_defaults):
    clock = sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql")
    op.create_table(
        table_name,
        sa.Column("support_source_id", sa.String(36), primary_key=True),
        sa.Column("patient_id", sa.Integer(), sa.ForeignKey("hoimsystem_patient.patient_id"), nullable=False),
        sa.Column("admission_id", sa.String(36), sa.ForeignKey("hoimsystem_admission.admission_id"), nullable=False),
        sa.Column("event_at", clock, nullable=True),
        sa.Column("recorded_at", clock, nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("hoimsystem_users.user_id"), nullable=False),
        sa.Column("schema_version", sa.String(48), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("reference_snapshot_json", sa.Text().with_variant(mysql.MEDIUMTEXT(), "mysql"), nullable=False),
        sa.Column("author_qualification_json", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="active" if server_defaults else None),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1" if server_defaults else None),
        sa.Column("revoked_at", clock, nullable=True),
        sa.Column("revoked_by", sa.Integer(), sa.ForeignKey("hoimsystem_users.user_id"), nullable=True),
        sa.Column("revoke_reason", sa.String(1000), nullable=False, server_default="" if server_defaults else None),
        sa.CheckConstraint("event_at IS NULL OR event_at <= recorded_at", name=f"ck_{prefix}_time"),
        sa.CheckConstraint(
            "(status = 'active' AND revision = 1 AND revoked_at IS NULL AND revoked_by IS NULL AND revoke_reason = '') OR "
            "(status = 'revoked' AND revision = 2 AND revoked_at IS NOT NULL AND revoked_by IS NOT NULL AND revoke_reason <> '')",
            name=f"ck_{prefix}_governance",
        ),
    )
    op.create_index(f"idx_{prefix}_scope", table_name, ["patient_id", "admission_id", "event_at"])
    op.create_index(f"idx_{prefix}_recorded", table_name, ["recorded_at"])


def upgrade():
    clock = sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql")
    op.create_table(
        MAPPING_TABLE,
        sa.Column("mapping_id", sa.String(36), primary_key=True),
        sa.Column("schema_version", sa.String(48), nullable=False),
        sa.Column("source_namespace", sa.String(120), nullable=False),
        sa.Column("pharmaceutical_id", sa.Integer(), sa.ForeignKey("hoimsystem_pharmaceutical.pharmaceutical_id"), nullable=False),
        sa.Column("identity_hash", sa.String(64), nullable=False),
        sa.Column("published_key", sa.String(64), nullable=True),
        sa.Column("drug_key", sa.String(32), nullable=False),
        sa.Column("active_moiety_basis", sa.String(16), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("hoimsystem_users.user_id"), nullable=False),
        sa.Column("created_at", clock, nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("published_at", clock, nullable=True),
        sa.Column("published_by", sa.Integer(), sa.ForeignKey("hoimsystem_users.user_id"), nullable=True),
        sa.Column("review_note", sa.String(2000), nullable=False),
        sa.Column("revoked_at", clock, nullable=True),
        sa.Column("revoked_by", sa.Integer(), sa.ForeignKey("hoimsystem_users.user_id"), nullable=True),
        sa.Column("revoke_reason", sa.String(1000), nullable=False),
        sa.CheckConstraint("status IN ('draft','published','revoked')", name="ck_vasoactive_mapping_status"),
    )
    op.create_index("uq_vasoactive_mapping_published", MAPPING_TABLE, ["published_key"], unique=True)
    op.create_index("idx_vasoactive_mapping_identity", MAPPING_TABLE, ["identity_hash", "status"])
    for table_name, prefix, server_defaults in CLINICAL_TABLES:
        _clinical_source(table_name, prefix, server_defaults)


def downgrade():
    for table_name, _, _ in reversed(CLINICAL_TABLES):
        op.drop_table(table_name)
    op.drop_table(MAPPING_TABLE)
