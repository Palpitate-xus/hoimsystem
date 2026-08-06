"""add personal prescription templates"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260806_prescription_template"
down_revision: str | Sequence[str] | None = "20260806_family_member"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    table_name = "hoimsystem_prescription_template"
    if inspector.has_table(table_name):
        return
    op.create_table(
        table_name,
        sa.Column("template_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("doctor_id", sa.Integer(), sa.ForeignKey("hoimsystem_doctor.doctor_id"), nullable=False),
        sa.Column("name", sa.String(length=50), nullable=False),
        sa.Column("items", sa.Text(), nullable=False),
        sa.Column("create_time", sa.DateTime(), nullable=False),
        sa.Column("update_time", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_prescription_template_doctor", table_name, ["doctor_id"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("hoimsystem_prescription_template"):
        op.drop_index("ix_prescription_template_doctor", table_name="hoimsystem_prescription_template")
        op.drop_table("hoimsystem_prescription_template")
