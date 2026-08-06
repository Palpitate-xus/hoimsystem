"""add medical record home"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260806_medical_record_home"
down_revision: str | Sequence[str] | None = "20260806_surgery_nursing_record"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    if sa.inspect(bind).has_table("hoimsystem_medical_record_home"):
        return
    op.create_table(
        "hoimsystem_medical_record_home",
        sa.Column("home_id", sa.String(length=36), primary_key=True),
        sa.Column("admission_id", sa.String(length=36), sa.ForeignKey("hoimsystem_admission.admission_id"), nullable=False, unique=True),
        sa.Column("patient_id", sa.Integer(), sa.ForeignKey("hoimsystem_patient.patient_id"), nullable=False),
        sa.Column("doctor_id", sa.Integer(), sa.ForeignKey("hoimsystem_doctor.doctor_id"), nullable=True),
        sa.Column("admission_diagnosis", sa.String(length=500), nullable=False),
        sa.Column("discharge_diagnosis", sa.String(length=500), nullable=True),
        sa.Column("other_diagnosis", sa.String(length=1000), nullable=True),
        sa.Column("operation_summary", sa.String(length=1000), nullable=True),
        sa.Column("complication", sa.String(length=1000), nullable=True),
        sa.Column("discharge_status", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_fee", sa.Float(), nullable=False, server_default="0"),
        sa.Column("status", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("creator_id", sa.Integer(), sa.ForeignKey("hoimsystem_users.user_id"), nullable=False),
        sa.Column("create_time", sa.DateTime(), nullable=False),
        sa.Column("update_time", sa.DateTime(), nullable=False),
        sa.Column("submit_time", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("hoimsystem_medical_record_home"):
        op.drop_table("hoimsystem_medical_record_home")
