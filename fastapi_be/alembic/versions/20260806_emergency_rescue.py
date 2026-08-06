"""add emergency rescue timeline"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260806_emergency_rescue"
down_revision: str | Sequence[str] | None = "20260806_emergency_triage"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    if sa.inspect(bind).has_table("hoimsystem_emergency_rescue_event"):
        return
    op.create_table(
        "hoimsystem_emergency_rescue_event",
        sa.Column("event_id", sa.String(length=36), primary_key=True),
        sa.Column("triage_id", sa.String(length=36), sa.ForeignKey("hoimsystem_emergency_triage.triage_id"), nullable=False),
        sa.Column("event_type", sa.String(length=30), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=False),
        sa.Column("medication", sa.String(length=300), nullable=True),
        sa.Column("event_time", sa.DateTime(), nullable=False),
        sa.Column("operator_id", sa.Integer(), sa.ForeignKey("hoimsystem_users.user_id"), nullable=False),
    )


def downgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("hoimsystem_emergency_rescue_event"):
        op.drop_table("hoimsystem_emergency_rescue_event")
