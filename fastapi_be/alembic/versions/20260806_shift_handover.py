"""add nursing shift handover"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260806_shift_handover"
down_revision: str | Sequence[str] | None = "20260806_patient_allergy"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    if sa.inspect(bind).has_table("hoimsystem_shift_handover"):
        return
    op.create_table(
        "hoimsystem_shift_handover",
        sa.Column("handover_id", sa.String(length=36), primary_key=True),
        sa.Column("shift_type", sa.String(length=20), nullable=False),
        sa.Column("content", sa.String(length=2000), nullable=False),
        sa.Column("status", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("handover_user_id", sa.Integer(), sa.ForeignKey("hoimsystem_users.user_id"), nullable=False),
        sa.Column("receiver_user_id", sa.Integer(), sa.ForeignKey("hoimsystem_users.user_id"), nullable=True),
        sa.Column("create_time", sa.DateTime(), nullable=False),
        sa.Column("receive_time", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("hoimsystem_shift_handover"):
        op.drop_table("hoimsystem_shift_handover")
