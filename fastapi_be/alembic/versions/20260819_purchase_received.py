"""purchase item received quantity

Revision ID: 20260819_purchase_received
Revises: 20260818_merge_user_role_fork
Create Date: 2026-08-19
"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260819_purchase_received"
down_revision: str | Sequence[str] | None = "20260818_merge_user_role_fork"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("hoimsystem_purchase_order_item") as batch:
        batch.add_column(sa.Column("received_quantity", sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("hoimsystem_purchase_order_item") as batch:
        batch.drop_column("received_quantity")
