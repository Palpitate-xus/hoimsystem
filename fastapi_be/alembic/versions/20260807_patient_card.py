"""add patient card management"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260807_patient_card"
down_revision: str | Sequence[str] | None = "20260806_perioperative_antibiotic"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if not sa.inspect(op.get_bind()).has_table("hoimsystem_patient_card"):
        op.create_table(
            "hoimsystem_patient_card",
            sa.Column("card_id", sa.String(36), primary_key=True),
            sa.Column("card_no", sa.String(24), nullable=False, unique=True),
            sa.Column("patient_id", sa.Integer(), sa.ForeignKey("hoimsystem_patient.patient_id"), nullable=False),
            sa.Column("status", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("issue_time", sa.DateTime(), nullable=False),
            sa.Column("lost_time", sa.DateTime()),
            sa.Column("cancel_time", sa.DateTime()),
            sa.Column("issuer_id", sa.Integer(), sa.ForeignKey("hoimsystem_users.user_id"), nullable=False),
        )


def downgrade() -> None:
    op.drop_table("hoimsystem_patient_card")
