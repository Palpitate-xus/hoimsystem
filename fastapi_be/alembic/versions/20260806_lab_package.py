"""add laboratory packages"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260806_lab_package"
down_revision: str | Sequence[str] | None = "20260806_medical_record_home_quality"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    if sa.inspect(bind).has_table("hoimsystem_lab_package"):
        return
    op.create_table("hoimsystem_lab_package", sa.Column("package_id", sa.Integer(), primary_key=True, autoincrement=True), sa.Column("code", sa.String(length=30), nullable=False, unique=True), sa.Column("name", sa.String(length=100), nullable=False), sa.Column("category", sa.String(length=50), nullable=True), sa.Column("items", sa.String(length=1000), nullable=False, server_default=""), sa.Column("price", sa.Float(), nullable=False, server_default="0"), sa.Column("status", sa.Integer(), nullable=False, server_default="1"), sa.Column("create_time", sa.DateTime(), nullable=False), sa.Column("update_time", sa.DateTime(), nullable=False))


def downgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("hoimsystem_lab_package"):
        op.drop_table("hoimsystem_lab_package")
