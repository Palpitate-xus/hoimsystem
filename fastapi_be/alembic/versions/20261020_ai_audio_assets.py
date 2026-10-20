"""Private patient-bound audio metadata; original bytes live outside report uploads."""

import sqlalchemy as sa

from alembic import op

revision = "20261020_ai_audio_assets"
down_revision = "20261020_pathway_revision"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "hoimsystem_ai_audio_asset",
        sa.Column("asset_id", sa.String(36), primary_key=True),
        sa.Column("patient_id", sa.Integer(), sa.ForeignKey("hoimsystem_patient.patient_id"), nullable=False),
        sa.Column("encounter_ref", sa.String(64)),
        sa.Column("media_type", sa.String(80), nullable=False),
        sa.Column("extension", sa.String(12), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("sample_rate", sa.Integer(), nullable=False),
        sa.Column("channels", sa.Integer(), nullable=False),
        sa.Column("codec", sa.String(80), nullable=False),
        sa.Column("recorded_at", sa.DateTime()),
        sa.Column("authorization_note", sa.String(1000), nullable=False),
        sa.Column("authorized_at", sa.DateTime(), nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("hoimsystem_users.user_id"), nullable=False),
        sa.Column("create_time", sa.DateTime(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("withdrawn_by", sa.Integer(), sa.ForeignKey("hoimsystem_users.user_id")),
        sa.Column("withdrawn_at", sa.DateTime()),
        sa.Column("withdrawal_note", sa.String(1000), nullable=False),
        sa.Column("purged_by", sa.Integer(), sa.ForeignKey("hoimsystem_users.user_id")),
        sa.Column("purged_at", sa.DateTime()),
    )
    op.create_index("idx_ai_audio_patient_owner", "hoimsystem_ai_audio_asset", ["patient_id", "created_by", "create_time"])
    op.create_index("idx_ai_audio_status", "hoimsystem_ai_audio_asset", ["status"])


def downgrade():
    op.drop_table("hoimsystem_ai_audio_asset")
