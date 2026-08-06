"""add imaging film delivery records"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260806_imaging_film"
down_revision: str | Sequence[str] | None = "20260806_insurance"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if not sa.inspect(op.get_bind()).has_table("hoimsystem_imaging_film"):
        op.create_table(
            "hoimsystem_imaging_film",
            sa.Column("film_id", sa.String(36), primary_key=True),
            sa.Column("imaging_order_id", sa.String(36), sa.ForeignKey("hoimsystem_imaging_order.imaging_order_id"), nullable=False),
            sa.Column("delivery_type", sa.String(10), nullable=False, server_default="print"),
            sa.Column("copies", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("status", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("cloud_url", sa.String(500)),
            sa.Column("requester_id", sa.Integer(), sa.ForeignKey("hoimsystem_users.user_id"), nullable=False),
            sa.Column("create_time", sa.DateTime(), nullable=False),
            sa.Column("complete_time", sa.DateTime()),
        )


def downgrade() -> None:
    op.drop_table("hoimsystem_imaging_film")
