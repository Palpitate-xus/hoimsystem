"""add critical care record"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260806_critical_care_record"
down_revision: str | Sequence[str] | None = "20260806_nursing_plan"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    if sa.inspect(bind).has_table("hoimsystem_critical_care_record"):
        return
    op.create_table(
        "hoimsystem_critical_care_record",
        sa.Column("record_id", sa.String(length=36), primary_key=True),
        sa.Column("admission_id", sa.String(length=36), sa.ForeignKey("hoimsystem_admission.admission_id"), nullable=False),
        sa.Column("patient_id", sa.Integer(), sa.ForeignKey("hoimsystem_patient.patient_id"), nullable=False),
        sa.Column("nurse_id", sa.Integer(), sa.ForeignKey("hoimsystem_users.user_id"), nullable=False),
        sa.Column("record_time", sa.DateTime(), nullable=False),
        sa.Column("consciousness", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("gcs_score", sa.Integer(), nullable=True),
        sa.Column("oxygen_support", sa.String(length=200), nullable=True),
        sa.Column("blood_pressure", sa.String(length=30), nullable=True),
        sa.Column("pulse", sa.Integer(), nullable=True),
        sa.Column("spo2", sa.Float(), nullable=True),
        sa.Column("urine_output", sa.String(length=100), nullable=True),
        sa.Column("note", sa.String(length=1000), nullable=True),
    )


def downgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("hoimsystem_critical_care_record"):
        op.drop_table("hoimsystem_critical_care_record")
