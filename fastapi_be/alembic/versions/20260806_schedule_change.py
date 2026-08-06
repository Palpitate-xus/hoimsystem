"""add schedule change approval"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260806_schedule_change"
down_revision: str | Sequence[str] | None = "20260806_charge_item"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    if sa.inspect(bind).has_table("hoimsystem_schedule_change_request"):
        return
    op.create_table(
        "hoimsystem_schedule_change_request",
        sa.Column("request_id", sa.String(length=36), primary_key=True),
        sa.Column("doctor_id", sa.Integer(), sa.ForeignKey("hoimsystem_doctor.doctor_id"), nullable=False),
        sa.Column("schedule_id", sa.Integer(), sa.ForeignKey("hoimsystem_doctor_schedule.schedule_id"), nullable=True),
        sa.Column("request_type", sa.String(length=10), nullable=False),
        sa.Column("target_date", sa.Date(), nullable=False),
        sa.Column("extra_slots", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("reason", sa.String(length=200), nullable=False),
        sa.Column("status", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("applicant_id", sa.Integer(), sa.ForeignKey("hoimsystem_users.user_id"), nullable=False),
        sa.Column("approver_id", sa.Integer(), sa.ForeignKey("hoimsystem_users.user_id"), nullable=True),
        sa.Column("create_time", sa.DateTime(), nullable=False),
        sa.Column("approve_time", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("hoimsystem_schedule_change_request"):
        op.drop_table("hoimsystem_schedule_change_request")
