"""add secure payment platform callback fields"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260810_payment_integration"
down_revision: str | Sequence[str] | None = "20260809_money_precision"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("hoimsystem_payment"):
        return
    columns = {column["name"] for column in inspector.get_columns("hoimsystem_payment")}
    with op.batch_alter_table("hoimsystem_payment") as batch_op:
        if "external_payment_id" not in columns:
            batch_op.add_column(sa.Column("external_payment_id", sa.String(100), nullable=True))
        if "integration_status" not in columns:
            batch_op.add_column(sa.Column("integration_status", sa.String(20), nullable=False, server_default="local"))
        if "last_sync_time" not in columns:
            batch_op.add_column(sa.Column("last_sync_time", sa.DateTime(), nullable=True))
    inspector = sa.inspect(bind)
    if "ix_hoimsystem_payment_external_payment_id" in {index["name"] for index in inspector.get_indexes("hoimsystem_payment")}:
        return
    op.create_index("ix_hoimsystem_payment_external_payment_id", "hoimsystem_payment", ["external_payment_id"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("hoimsystem_payment"):
        return
    indexes = {index["name"] for index in inspector.get_indexes("hoimsystem_payment")}
    if "ix_hoimsystem_payment_external_payment_id" in indexes:
        op.drop_index("ix_hoimsystem_payment_external_payment_id", table_name="hoimsystem_payment")
    columns = {column["name"] for column in inspector.get_columns("hoimsystem_payment")}
    with op.batch_alter_table("hoimsystem_payment") as batch_op:
        for column in ("last_sync_time", "integration_status", "external_payment_id"):
            if column in columns:
                batch_op.drop_column(column)
