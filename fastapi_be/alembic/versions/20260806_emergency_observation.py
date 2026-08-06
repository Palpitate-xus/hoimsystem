"""add emergency observation management"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260806_emergency_observation"
down_revision: str | Sequence[str] | None = "20260806_emergency_rescue"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    if sa.inspect(bind).has_table("hoimsystem_emergency_observation"):
        return
    op.create_table(
        "hoimsystem_emergency_observation",
        sa.Column("observation_id", sa.String(length=36), primary_key=True),
        sa.Column("triage_id", sa.String(length=36), sa.ForeignKey("hoimsystem_emergency_triage.triage_id"), nullable=False),
        sa.Column("start_time", sa.DateTime(), nullable=False),
        sa.Column("end_time", sa.DateTime(), nullable=True),
        sa.Column("condition", sa.String(length=500), nullable=False),
        sa.Column("medical_advice", sa.String(length=500), nullable=True),
        sa.Column("fee_amount", sa.Float(), nullable=False, server_default="0"),
        sa.Column("fee_status", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("operator_id", sa.Integer(), sa.ForeignKey("hoimsystem_users.user_id"), nullable=False),
        sa.Column("update_time", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("hoimsystem_emergency_observation"):
        op.drop_table("hoimsystem_emergency_observation")
