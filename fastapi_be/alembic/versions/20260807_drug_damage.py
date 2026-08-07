"""add drug damage records"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260807_drug_damage"
down_revision: str | Sequence[str] | None = "20260807_patient_card"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if not sa.inspect(op.get_bind()).has_table("hoimsystem_drug_damage"):
        op.create_table(
            "hoimsystem_drug_damage",
            sa.Column("damage_id", sa.String(36), primary_key=True),
            sa.Column("pharmaceutical_id", sa.Integer(), sa.ForeignKey("hoimsystem_pharmaceutical.pharmaceutical_id"), nullable=False),
            sa.Column("quantity", sa.Integer(), nullable=False),
            sa.Column("damage_type", sa.String(20), nullable=False),
            sa.Column("batch_no", sa.String(60)),
            sa.Column("reason", sa.String(300), nullable=False),
            sa.Column("status", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("applicant_id", sa.Integer(), sa.ForeignKey("hoimsystem_users.user_id"), nullable=False),
            sa.Column("approver_id", sa.Integer(), sa.ForeignKey("hoimsystem_users.user_id")),
            sa.Column("create_time", sa.DateTime(), nullable=False),
            sa.Column("approve_time", sa.DateTime()),
        )


def downgrade() -> None:
    op.drop_table("hoimsystem_drug_damage")
