"""add surgery nursing record"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260806_surgery_nursing_record"
down_revision: str | Sequence[str] | None = "20260806_critical_care_record"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    if sa.inspect(bind).has_table("hoimsystem_surgery_nursing_record"):
        return
    op.create_table(
        "hoimsystem_surgery_nursing_record",
        sa.Column("record_id", sa.String(length=36), primary_key=True),
        sa.Column("schedule_id", sa.String(length=36), sa.ForeignKey("hoimsystem_surgery_schedule.schedule_id"), nullable=False),
        sa.Column("patient_id", sa.Integer(), sa.ForeignKey("hoimsystem_patient.patient_id"), nullable=False),
        sa.Column("nurse_id", sa.Integer(), sa.ForeignKey("hoimsystem_users.user_id"), nullable=False),
        sa.Column("phase", sa.Integer(), nullable=False),
        sa.Column("checklist", sa.String(length=1000), nullable=False),
        sa.Column("instrument_count", sa.String(length=300), nullable=True),
        sa.Column("specimen", sa.String(length=500), nullable=True),
        sa.Column("wound_condition", sa.String(length=500), nullable=True),
        sa.Column("note", sa.String(length=1000), nullable=True),
        sa.Column("record_time", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("hoimsystem_surgery_nursing_record"):
        op.drop_table("hoimsystem_surgery_nursing_record")
