"""add emergency green channel workflow"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260806_emergency_green_channel"
down_revision: str | Sequence[str] | None = "20260806_emergency_observation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    if sa.inspect(bind).has_table("hoimsystem_emergency_green_channel"):
        return
    op.create_table(
        "hoimsystem_emergency_green_channel",
        sa.Column("channel_id", sa.String(length=36), primary_key=True),
        sa.Column("triage_id", sa.String(length=36), sa.ForeignKey("hoimsystem_emergency_triage.triage_id"), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=False),
        sa.Column("status", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("applicant_id", sa.Integer(), sa.ForeignKey("hoimsystem_users.user_id"), nullable=False),
        sa.Column("approver_id", sa.Integer(), sa.ForeignKey("hoimsystem_users.user_id"), nullable=True),
        sa.Column("create_time", sa.DateTime(), nullable=False),
        sa.Column("action_time", sa.DateTime(), nullable=True),
        sa.Column("note", sa.String(length=500), nullable=True),
    )


def downgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("hoimsystem_emergency_green_channel"):
        op.drop_table("hoimsystem_emergency_green_channel")
