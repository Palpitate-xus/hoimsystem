"""add nursing admission assessment"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260806_nursing_assessment"
down_revision: str | Sequence[str] | None = "20260806_emergency_medical_record"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    if sa.inspect(bind).has_table("hoimsystem_nursing_assessment"):
        return
    op.create_table(
        "hoimsystem_nursing_assessment",
        sa.Column("assessment_id", sa.String(length=36), primary_key=True),
        sa.Column("admission_id", sa.String(length=36), sa.ForeignKey("hoimsystem_admission.admission_id"), nullable=False),
        sa.Column("patient_id", sa.Integer(), sa.ForeignKey("hoimsystem_patient.patient_id"), nullable=False),
        sa.Column("nurse_id", sa.Integer(), sa.ForeignKey("hoimsystem_users.user_id"), nullable=False),
        sa.Column("adl_score", sa.Integer(), nullable=False),
        sa.Column("pressure_ulcer_risk", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("fall_risk", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("consciousness", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("nutrition_risk", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("note", sa.String(length=1000), nullable=True),
        sa.Column("status", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("create_time", sa.DateTime(), nullable=False),
        sa.Column("update_time", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("hoimsystem_nursing_assessment"):
        op.drop_table("hoimsystem_nursing_assessment")
