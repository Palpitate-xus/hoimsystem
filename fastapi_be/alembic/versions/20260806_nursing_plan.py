"""add nursing plan"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260806_nursing_plan"
down_revision: str | Sequence[str] | None = "20260806_nursing_assessment"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    if sa.inspect(bind).has_table("hoimsystem_nursing_plan"):
        return
    op.create_table(
        "hoimsystem_nursing_plan",
        sa.Column("plan_id", sa.String(length=36), primary_key=True),
        sa.Column("admission_id", sa.String(length=36), sa.ForeignKey("hoimsystem_admission.admission_id"), nullable=False),
        sa.Column("patient_id", sa.Integer(), sa.ForeignKey("hoimsystem_patient.patient_id"), nullable=False),
        sa.Column("nurse_id", sa.Integer(), sa.ForeignKey("hoimsystem_users.user_id"), nullable=False),
        sa.Column("nursing_diagnosis", sa.String(length=500), nullable=False),
        sa.Column("goal", sa.String(length=500), nullable=False),
        sa.Column("measures", sa.String(length=1000), nullable=False),
        sa.Column("status", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("create_time", sa.DateTime(), nullable=False),
        sa.Column("update_time", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("hoimsystem_nursing_plan"):
        op.drop_table("hoimsystem_nursing_plan")
