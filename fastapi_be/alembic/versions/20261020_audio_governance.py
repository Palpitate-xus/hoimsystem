"""Retain the reason for an explicit file purge independently of withdrawal."""

import sqlalchemy as sa

from alembic import op

revision = "20261020_audio_governance"
down_revision = "20261020_ai_audio_assets"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("hoimsystem_ai_audio_asset", sa.Column("purge_note", sa.String(1000), nullable=False, server_default=""))


def downgrade():
    with op.batch_alter_table("hoimsystem_ai_audio_asset") as batch:
        batch.drop_column("purge_note")
