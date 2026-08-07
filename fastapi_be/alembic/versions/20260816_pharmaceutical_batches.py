"""add pharmaceutical batch inventory and stock ledger"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260816_pharmaceutical_batches"
down_revision: str | Sequence[str] | None = "20260815_medical_record_signature"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("hoimsystem_pharmaceutical_batch"):
        op.create_table(
            "hoimsystem_pharmaceutical_batch",
            sa.Column("batch_id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("pharmaceutical_id", sa.Integer(), nullable=False),
            sa.Column("batch_no", sa.String(length=60), nullable=False),
            sa.Column("expiry_date", sa.Date(), nullable=True),
            sa.Column("stock", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("location", sa.String(length=100), nullable=False, server_default=""),
            sa.Column("status", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("create_time", sa.DateTime(), nullable=False),
            sa.Column("update_time", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["pharmaceutical_id"], ["hoimsystem_pharmaceutical.pharmaceutical_id"]),
            sa.PrimaryKeyConstraint("batch_id"),
            sa.UniqueConstraint("pharmaceutical_id", "batch_no", name="uq_pharmaceutical_batch_no"),
        )
    if not inspector.has_table("hoimsystem_pharmaceutical_stock_ledger"):
        op.create_table(
            "hoimsystem_pharmaceutical_stock_ledger",
            sa.Column("ledger_id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("batch_id", sa.Integer(), nullable=False),
            sa.Column("pharmaceutical_id", sa.Integer(), nullable=False),
            sa.Column("transaction_type", sa.String(length=20), nullable=False),
            sa.Column("quantity", sa.Integer(), nullable=False),
            sa.Column("before_stock", sa.Integer(), nullable=False),
            sa.Column("after_stock", sa.Integer(), nullable=False),
            sa.Column("reference_type", sa.String(length=30), nullable=True),
            sa.Column("reference_id", sa.String(length=60), nullable=True),
            sa.Column("operator_id", sa.Integer(), nullable=False),
            sa.Column("reason", sa.String(length=200), nullable=False, server_default=""),
            sa.Column("create_time", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["batch_id"], ["hoimsystem_pharmaceutical_batch.batch_id"]),
            sa.ForeignKeyConstraint(["pharmaceutical_id"], ["hoimsystem_pharmaceutical.pharmaceutical_id"]),
            sa.ForeignKeyConstraint(["operator_id"], ["hoimsystem_users.user_id"]),
            sa.PrimaryKeyConstraint("ledger_id"),
        )
    item_columns = {column["name"] for column in inspector.get_columns("hoimsystem_purchase_order_item")}
    with op.batch_alter_table("hoimsystem_purchase_order_item") as batch_op:
        if "batch_no" not in item_columns:
            batch_op.add_column(sa.Column("batch_no", sa.String(length=60), nullable=True))
        if "expiry_date" not in item_columns:
            batch_op.add_column(sa.Column("expiry_date", sa.Date(), nullable=True))
        if "location" not in item_columns:
            batch_op.add_column(sa.Column("location", sa.String(length=100), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("hoimsystem_pharmaceutical_stock_ledger"):
        op.drop_table("hoimsystem_pharmaceutical_stock_ledger")
    if inspector.has_table("hoimsystem_pharmaceutical_batch"):
        op.drop_table("hoimsystem_pharmaceutical_batch")
    if inspector.has_table("hoimsystem_purchase_order_item"):
        columns = {column["name"] for column in inspector.get_columns("hoimsystem_purchase_order_item")}
        with op.batch_alter_table("hoimsystem_purchase_order_item") as batch_op:
            for column in ("location", "expiry_date", "batch_no"):
                if column in columns:
                    batch_op.drop_column(column)
