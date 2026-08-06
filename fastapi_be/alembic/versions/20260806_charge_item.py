"""add charge item catalog"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260806_charge_item"
down_revision: str | Sequence[str] | None = "20260806_special_drug"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    if sa.inspect(bind).has_table("hoimsystem_charge_item"):
        return
    op.create_table(
        "hoimsystem_charge_item",
        sa.Column("item_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("code", sa.String(length=30), nullable=False, unique=True),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("category", sa.String(length=30), nullable=False),
        sa.Column("price", sa.Float(), nullable=False),
        sa.Column("status", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("note", sa.String(length=200), nullable=True),
        sa.Column("creator_id", sa.Integer(), sa.ForeignKey("hoimsystem_users.user_id"), nullable=False),
        sa.Column("create_time", sa.DateTime(), nullable=False),
        sa.Column("update_time", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("hoimsystem_charge_item"):
        op.drop_table("hoimsystem_charge_item")
