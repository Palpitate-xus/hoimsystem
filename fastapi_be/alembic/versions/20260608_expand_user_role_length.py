"""expand user role length

Revision ID: 20260608_user_role
Revises: 1f24ea8140a3
Create Date: 2026-06-08 00:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260608_user_role"
down_revision: str | Sequence[str] | None = "1f24ea8140a3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # SQLite 不支持 ALTER COLUMN TYPE，用 batch 模式（表重建）实现跨方言兼容
    with op.batch_alter_table("hoimsystem_users") as batch:
        batch.alter_column(
            "user_role",
            existing_type=sa.String(length=10),
            type_=sa.String(length=20),
            existing_nullable=True,
        )


def downgrade() -> None:
    with op.batch_alter_table("hoimsystem_users") as batch:
        batch.alter_column(
            "user_role",
            existing_type=sa.String(length=20),
            type_=sa.String(length=10),
            existing_nullable=True,
        )
