"""add skin test workflow"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260806_skin_test"
down_revision: str | Sequence[str] | None = "20260806_injection"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    if sa.inspect(bind).has_table("hoimsystem_skin_test_order"):
        return
    op.create_table(
        "hoimsystem_skin_test_order",
        sa.Column("skin_test_id", sa.String(length=36), primary_key=True),
        sa.Column("patient_id", sa.Integer(), sa.ForeignKey("hoimsystem_patient.patient_id"), nullable=False),
        sa.Column("doctor_id", sa.Integer(), sa.ForeignKey("hoimsystem_doctor.doctor_id"), nullable=False),
        sa.Column("nurse_id", sa.Integer(), sa.ForeignKey("hoimsystem_users.user_id"), nullable=True),
        sa.Column("pharmaceutical_id", sa.Integer(), sa.ForeignKey("hoimsystem_pharmaceutical.pharmaceutical_id"), nullable=False),
        sa.Column("dose", sa.String(length=50), nullable=False),
        sa.Column("site", sa.String(length=30), nullable=False),
        sa.Column("observe_minutes", sa.Integer(), nullable=False),
        sa.Column("status", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("result_note", sa.String(length=200), nullable=True),
        sa.Column("create_time", sa.DateTime(), nullable=False),
        sa.Column("administer_time", sa.DateTime(), nullable=True),
        sa.Column("observe_time", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("hoimsystem_skin_test_order"):
        op.drop_table("hoimsystem_skin_test_order")
