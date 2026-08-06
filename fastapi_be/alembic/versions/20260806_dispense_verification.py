"""add pharmacy dispense verification"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260806_dispense_verification"
down_revision: str | Sequence[str] | None = "20260806_shift_handover"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    if sa.inspect(bind).has_table("hoimsystem_dispense_verification"):
        return
    op.create_table(
        "hoimsystem_dispense_verification",
        sa.Column("verification_id", sa.String(length=36), primary_key=True),
        sa.Column("prescription_id", sa.String(length=36), sa.ForeignKey("hoimsystem_prescription.prescription_id"), nullable=False, unique=True),
        sa.Column("pharmacist_id", sa.Integer(), sa.ForeignKey("hoimsystem_users.user_id"), nullable=False),
        sa.Column("verifier_id", sa.Integer(), sa.ForeignKey("hoimsystem_users.user_id"), nullable=True),
        sa.Column("status", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("note", sa.String(length=200), nullable=True),
        sa.Column("create_time", sa.DateTime(), nullable=False),
        sa.Column("verify_time", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("hoimsystem_dispense_verification"):
        op.drop_table("hoimsystem_dispense_verification")
