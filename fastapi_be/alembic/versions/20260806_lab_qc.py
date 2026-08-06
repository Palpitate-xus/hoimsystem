"""add laboratory quality control records"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260806_lab_qc"
down_revision: str | Sequence[str] | None = "20260806_lab_package"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    if sa.inspect(bind).has_table("hoimsystem_lab_qc_record"):
        return
    op.create_table("hoimsystem_lab_qc_record", sa.Column("qc_id", sa.String(length=36), primary_key=True), sa.Column("qc_name", sa.String(length=100), nullable=False), sa.Column("level", sa.String(length=30), nullable=False), sa.Column("target_value", sa.Float(), nullable=False), sa.Column("measured_value", sa.Float(), nullable=False), sa.Column("unit", sa.String(length=20), nullable=True), sa.Column("pass_flag", sa.Integer(), nullable=False, server_default="1"), sa.Column("remark", sa.String(length=300), nullable=True), sa.Column("operator_id", sa.Integer(), sa.ForeignKey("hoimsystem_users.user_id"), nullable=False), sa.Column("qc_time", sa.DateTime(), nullable=False))


def downgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("hoimsystem_lab_qc_record"):
        op.drop_table("hoimsystem_lab_qc_record")
