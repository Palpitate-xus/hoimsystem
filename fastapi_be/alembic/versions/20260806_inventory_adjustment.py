"""add pharmacy inventory adjustment workflow"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260806_inventory_adjustment"
down_revision: str | Sequence[str] | None = "20260806_prescription_template"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    table_name = "hoimsystem_inventory_adjustment"
    if inspector.has_table(table_name):
        return
    op.create_table(
        table_name,
        sa.Column("adjustment_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("pharmaceutical_id", sa.Integer(), sa.ForeignKey("hoimsystem_pharmaceutical.pharmaceutical_id"), nullable=False),
        sa.Column("adjustment_type", sa.String(length=10), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(length=200), nullable=False),
        sa.Column("status", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("applicant_id", sa.Integer(), sa.ForeignKey("hoimsystem_users.user_id"), nullable=False),
        sa.Column("approver_id", sa.Integer(), sa.ForeignKey("hoimsystem_users.user_id"), nullable=True),
        sa.Column("create_time", sa.DateTime(), nullable=False),
        sa.Column("approve_time", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_inventory_adjustment_status", table_name, ["status"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("hoimsystem_inventory_adjustment"):
        op.drop_index("ix_inventory_adjustment_status", table_name="hoimsystem_inventory_adjustment")
        op.drop_table("hoimsystem_inventory_adjustment")
