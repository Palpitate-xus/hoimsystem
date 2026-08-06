"""add emergency medical record"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260806_emergency_medical_record"
down_revision: str | Sequence[str] | None = "20260806_emergency_green_channel"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    if sa.inspect(bind).has_table("hoimsystem_emergency_medical_record"):
        return
    op.create_table(
        "hoimsystem_emergency_medical_record",
        sa.Column("record_id", sa.String(length=36), primary_key=True),
        sa.Column("triage_id", sa.String(length=36), sa.ForeignKey("hoimsystem_emergency_triage.triage_id"), nullable=False),
        sa.Column("patient_id", sa.Integer(), sa.ForeignKey("hoimsystem_patient.patient_id"), nullable=False),
        sa.Column("doctor_id", sa.Integer(), sa.ForeignKey("hoimsystem_doctor.doctor_id"), nullable=True),
        sa.Column("chief_complaint", sa.String(length=500), nullable=False),
        sa.Column("present_illness", sa.String(length=1000), nullable=True),
        sa.Column("physical_exam", sa.String(length=1000), nullable=True),
        sa.Column("diagnosis", sa.String(length=500), nullable=True),
        sa.Column("treatment_plan", sa.String(length=1000), nullable=True),
        sa.Column("status", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("create_time", sa.DateTime(), nullable=False),
        sa.Column("update_time", sa.DateTime(), nullable=False),
        sa.Column("sign_time", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("hoimsystem_emergency_medical_record"):
        op.drop_table("hoimsystem_emergency_medical_record")
