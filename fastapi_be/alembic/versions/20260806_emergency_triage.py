"""add emergency triage"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260806_emergency_triage"
down_revision: str | Sequence[str] | None = "20260806_schedule_change"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    if sa.inspect(bind).has_table("hoimsystem_emergency_triage"):
        return
    op.create_table(
        "hoimsystem_emergency_triage",
        sa.Column("triage_id", sa.String(length=36), primary_key=True),
        sa.Column("patient_id", sa.Integer(), sa.ForeignKey("hoimsystem_patient.patient_id"), nullable=False),
        sa.Column("triage_level", sa.Integer(), nullable=False),
        sa.Column("chief_complaint", sa.String(length=500), nullable=False),
        sa.Column("vital_signs", sa.String(length=500), nullable=True),
        sa.Column("green_channel", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("nurse_id", sa.Integer(), sa.ForeignKey("hoimsystem_users.user_id"), nullable=False),
        sa.Column("create_time", sa.DateTime(), nullable=False),
        sa.Column("update_time", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("hoimsystem_emergency_triage"):
        op.drop_table("hoimsystem_emergency_triage")
