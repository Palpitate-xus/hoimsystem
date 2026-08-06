"""add fields required by the operation log model"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260806_operation_log"
down_revision: str | Sequence[str] | None = "1f24ea8140a3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_COLUMNS = (
    ("username", sa.String(length=50)),
    ("role", sa.String(length=20)),
    ("detail", sa.String(length=500)),
    ("status_code", sa.Integer()),
    ("method", sa.String(length=10)),
    ("path", sa.String(length=200)),
)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    table_name = "hoimsystem_operation_log"

    if not inspector.has_table(table_name):
        op.create_table(
            table_name,
            sa.Column("log_id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("user_id", sa.Integer()),
            *[sa.Column(name, column_type) for name, column_type in _COLUMNS],
            sa.Column("action", sa.String(length=50)),
            sa.Column("target", sa.String(length=100)),
            sa.Column("result", sa.String(length=20)),
            sa.Column("ip", sa.String(length=40)),
            sa.Column("create_time", sa.DateTime()),
        )
        return

    existing = {column["name"] for column in inspector.get_columns(table_name)}
    for name, column_type in _COLUMNS:
        if name not in existing:
            op.add_column(table_name, sa.Column(name, column_type))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("hoimsystem_operation_log"):
        return
    existing = {column["name"] for column in inspector.get_columns("hoimsystem_operation_log")}
    for name, _ in reversed(_COLUMNS):
        if name in existing:
            op.drop_column("hoimsystem_operation_log", name)
