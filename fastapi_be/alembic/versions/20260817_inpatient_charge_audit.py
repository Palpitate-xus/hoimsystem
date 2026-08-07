"""add inpatient charge settlement and refund audit fields"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260817_inpatient_charge_audit"
down_revision: str | Sequence[str] | None = "20260816_pharmaceutical_batches"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("hoimsystem_inpatient_charge"):
        return
    columns = {column["name"] for column in inspector.get_columns("hoimsystem_inpatient_charge")}
    with op.batch_alter_table("hoimsystem_inpatient_charge") as batch_op:
        if "settled_by" not in columns:
            batch_op.add_column(sa.Column("settled_by", sa.Integer(), nullable=True))
        if "settled_time" not in columns:
            batch_op.add_column(sa.Column("settled_time", sa.DateTime(), nullable=True))
        if "refunded_by" not in columns:
            batch_op.add_column(sa.Column("refunded_by", sa.Integer(), nullable=True))
        if "refunded_time" not in columns:
            batch_op.add_column(sa.Column("refunded_time", sa.DateTime(), nullable=True))
        if "refund_reason" not in columns:
            batch_op.add_column(sa.Column("refund_reason", sa.String(length=200), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("hoimsystem_inpatient_charge"):
        return
    columns = {column["name"] for column in inspector.get_columns("hoimsystem_inpatient_charge")}
    with op.batch_alter_table("hoimsystem_inpatient_charge") as batch_op:
        for column in ("refund_reason", "refunded_time", "refunded_by", "settled_time", "settled_by"):
            if column in columns:
                batch_op.drop_column(column)
