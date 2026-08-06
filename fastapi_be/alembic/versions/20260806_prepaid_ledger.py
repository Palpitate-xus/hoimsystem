"""add prepaid account transaction ledger"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260806_prepaid_ledger"
down_revision: str | Sequence[str] | None = "20260806_operation_log"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    table_name = "hoimsystem_prepaid_transaction"
    if inspector.has_table(table_name):
        return
    op.create_table(
        table_name,
        sa.Column("transaction_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("patient_id", sa.Integer(), sa.ForeignKey("hoimsystem_patient.patient_id"), nullable=False),
        sa.Column("operator_id", sa.Integer(), sa.ForeignKey("hoimsystem_users.user_id"), nullable=False),
        sa.Column("transaction_type", sa.String(length=20), nullable=False),
        sa.Column("amount", sa.Float(), nullable=False),
        sa.Column("balance_after", sa.Float(), nullable=False),
        sa.Column("note", sa.String(length=200), nullable=True),
        sa.Column("create_time", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "ix_prepaid_transaction_patient_time",
        table_name,
        ["patient_id", "create_time"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("hoimsystem_prepaid_transaction"):
        op.drop_index("ix_prepaid_transaction_patient_time", table_name="hoimsystem_prepaid_transaction")
        op.drop_table("hoimsystem_prepaid_transaction")
