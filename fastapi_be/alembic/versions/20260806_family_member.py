"""add patient family member links"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260806_family_member"
down_revision: str | Sequence[str] | None = "20260806_prepaid_ledger"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    table_name = "hoimsystem_family_member"
    if inspector.has_table(table_name):
        return
    op.create_table(
        table_name,
        sa.Column("family_member_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("owner_patient_id", sa.Integer(), sa.ForeignKey("hoimsystem_patient.patient_id"), nullable=False),
        sa.Column("member_patient_id", sa.Integer(), sa.ForeignKey("hoimsystem_patient.patient_id"), nullable=False),
        sa.Column("relation", sa.String(length=20), nullable=False),
        sa.Column("create_time", sa.DateTime(), nullable=False),
        sa.Column("update_time", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_family_member_owner", table_name, ["owner_patient_id"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("hoimsystem_family_member"):
        op.drop_index("ix_family_member_owner", table_name="hoimsystem_family_member")
        op.drop_table("hoimsystem_family_member")
