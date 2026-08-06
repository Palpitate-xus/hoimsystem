"""add controlled drug dual check ledger"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260806_special_drug"
down_revision: str | Sequence[str] | None = "20260806_dispense_verification"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    if sa.inspect(bind).has_table("hoimsystem_special_drug_register"):
        return
    op.create_table(
        "hoimsystem_special_drug_register",
        sa.Column("register_id", sa.String(length=36), primary_key=True),
        sa.Column("pharmaceutical_id", sa.Integer(), sa.ForeignKey("hoimsystem_pharmaceutical.pharmaceutical_id"), nullable=False),
        sa.Column("patient_id", sa.Integer(), sa.ForeignKey("hoimsystem_patient.patient_id"), nullable=True),
        sa.Column("action", sa.String(length=10), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(length=200), nullable=False),
        sa.Column("status", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("applicant_id", sa.Integer(), sa.ForeignKey("hoimsystem_users.user_id"), nullable=False),
        sa.Column("checker_id", sa.Integer(), sa.ForeignKey("hoimsystem_users.user_id"), nullable=True),
        sa.Column("create_time", sa.DateTime(), nullable=False),
        sa.Column("check_time", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("hoimsystem_special_drug_register"):
        op.drop_table("hoimsystem_special_drug_register")
