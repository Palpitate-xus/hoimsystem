"""add persisted sample tracking events"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260807_sample_tracking"
down_revision: str | Sequence[str] | None = "20260807_drug_damage"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if not sa.inspect(op.get_bind()).has_table("hoimsystem_sample_tracking"):
        op.create_table(
            "hoimsystem_sample_tracking",
            sa.Column("tracking_id", sa.String(36), primary_key=True),
            sa.Column("lab_order_id", sa.String(36), sa.ForeignKey("hoimsystem_lab_order.lab_order_id"), nullable=False),
            sa.Column("stage", sa.String(40), nullable=False),
            sa.Column("operator_id", sa.Integer(), sa.ForeignKey("hoimsystem_users.user_id"), nullable=False),
            sa.Column("event_time", sa.DateTime(), nullable=False),
            sa.Column("note", sa.String(300)),
        )


def downgrade() -> None:
    op.drop_table("hoimsystem_sample_tracking")
