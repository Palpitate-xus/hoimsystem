"""Add immutable, explicitly reviewed laboratory project mappings."""

import sqlalchemy as sa
from sqlalchemy.dialects import mysql

from alembic import op

revision = "20261020_ai_lab_mappings"
down_revision = "20261020_ai_observation_windows"
branch_labels = None
depends_on = None


def upgrade():
    utc6 = sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql")
    op.create_table(
        "hoimsystem_ai_lab_mapping",
        sa.Column("mapping_id", sa.String(36), primary_key=True),
        sa.Column("schema_version", sa.String(40), nullable=False),
        sa.Column("source_namespace", sa.String(120), nullable=False),
        sa.Column("code_system", sa.String(80), nullable=False),
        sa.Column("code", sa.String(80), nullable=False),
        sa.Column("unit", sa.String(40)),
        sa.Column("method", sa.String(100), nullable=False),
        sa.Column("specimen_type", sa.String(80), nullable=False),
        sa.Column("value_kind", sa.String(24), nullable=False),
        sa.Column("analyte_key", sa.String(64), nullable=False),
        sa.Column("identity_hash", sa.String(64), nullable=False),
        sa.Column("published_key", sa.String(64)),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("hoimsystem_users.user_id"), nullable=False),
        sa.Column("created_at", utc6, nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("published_by", sa.Integer(), sa.ForeignKey("hoimsystem_users.user_id")),
        sa.Column("published_at", utc6),
        sa.Column("review_note", sa.String(2000), nullable=False),
        sa.Column("revoked_by", sa.Integer(), sa.ForeignKey("hoimsystem_users.user_id")),
        sa.Column("revoked_at", utc6),
        sa.Column("revoke_reason", sa.String(1000), nullable=False),
        sa.UniqueConstraint("published_key", name="uq_ai_lab_mapping_published"),
        sa.CheckConstraint("value_kind IN ('numeric', 'qualitative')", name="ck_ai_lab_mapping_value_kind"),
        sa.CheckConstraint("value_kind <> 'numeric' OR (unit IS NOT NULL AND unit <> '')", name="ck_ai_lab_mapping_numeric_unit"),
        sa.CheckConstraint(
            "(status = 'draft' AND revision = 1 AND published_at IS NULL AND published_by IS NULL AND published_key IS NULL AND review_note = '' AND revoked_at IS NULL AND revoked_by IS NULL AND revoke_reason = '') OR "
            "(status = 'published' AND revision = 2 AND published_at IS NOT NULL AND published_by IS NOT NULL AND published_key IS NOT NULL AND published_key = identity_hash AND review_note <> '' AND revoked_at IS NULL AND revoked_by IS NULL AND revoke_reason = '') OR "
            "(status = 'revoked' AND published_key IS NULL AND revoked_at IS NOT NULL AND revoked_by IS NOT NULL AND revoke_reason <> '' AND "
            "((revision = 2 AND published_at IS NULL AND published_by IS NULL AND review_note = '') OR (revision = 3 AND published_at IS NOT NULL AND published_by IS NOT NULL AND review_note <> '')))",
            name="ck_ai_lab_mapping_governance",
        ),
    )
    op.create_index("idx_ai_lab_mapping_identity", "hoimsystem_ai_lab_mapping", ["identity_hash", "status"])
    op.create_index("idx_ai_lab_mapping_created", "hoimsystem_ai_lab_mapping", ["created_at", "mapping_id"])


def downgrade():
    op.drop_table("hoimsystem_ai_lab_mapping")
