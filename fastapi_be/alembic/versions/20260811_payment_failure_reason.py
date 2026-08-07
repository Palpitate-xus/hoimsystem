"""add payment provider failure reason"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260811_payment_failure_reason"
down_revision: str | Sequence[str] | None = "20260810_payment_integration"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("hoimsystem_payment"):
        return
    columns = {column["name"] for column in inspector.get_columns("hoimsystem_payment")}
    if "failure_reason" not in columns:
        with op.batch_alter_table("hoimsystem_payment") as batch_op:
            batch_op.add_column(sa.Column("failure_reason", sa.String(200), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("hoimsystem_payment"):
        return
    columns = {column["name"] for column in inspector.get_columns("hoimsystem_payment")}
    if "failure_reason" in columns:
        with op.batch_alter_table("hoimsystem_payment") as batch_op:
            batch_op.drop_column("failure_reason")
