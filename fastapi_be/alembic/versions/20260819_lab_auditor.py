"""lab result audit trail

Revision ID: 20260819_lab_auditor
Revises: 20260819_purchase_received
Create Date: 2026-08-19
"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260819_lab_auditor"
down_revision: str | Sequence[str] | None = "20260819_purchase_received"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("hoimsystem_lab_result") as batch:
        batch.add_column(sa.Column("auditor_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("audit_time", sa.DateTime(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("hoimsystem_lab_result") as batch:
        batch.drop_column("audit_time")
        batch.drop_column("auditor_id")
