"""add outpatient infusion workflow"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260806_infusion"
down_revision: str | Sequence[str] | None = "20260806_diagnosis_template"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("hoimsystem_infusion_order"):
        op.create_table(
            "hoimsystem_infusion_order",
            sa.Column("infusion_id", sa.String(length=36), primary_key=True),
            sa.Column("patient_id", sa.Integer(), sa.ForeignKey("hoimsystem_patient.patient_id"), nullable=False),
            sa.Column("doctor_id", sa.Integer(), sa.ForeignKey("hoimsystem_doctor.doctor_id"), nullable=False),
            sa.Column("nurse_id", sa.Integer(), sa.ForeignKey("hoimsystem_users.user_id"), nullable=True),
            sa.Column("pharmaceutical_id", sa.Integer(), sa.ForeignKey("hoimsystem_pharmaceutical.pharmaceutical_id"), nullable=False),
            sa.Column("dose", sa.String(length=50), nullable=False),
            sa.Column("batch_no", sa.String(length=50), nullable=False),
            sa.Column("drip_rate", sa.Integer(), nullable=True),
            sa.Column("status", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("note", sa.String(length=200), nullable=True),
            sa.Column("create_time", sa.DateTime(), nullable=False),
            sa.Column("start_time", sa.DateTime(), nullable=True),
            sa.Column("end_time", sa.DateTime(), nullable=True),
        )
    if not inspector.has_table("hoimsystem_infusion_observation"):
        op.create_table(
            "hoimsystem_infusion_observation",
            sa.Column("observation_id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("infusion_id", sa.String(length=36), sa.ForeignKey("hoimsystem_infusion_order.infusion_id"), nullable=False),
            sa.Column("nurse_id", sa.Integer(), sa.ForeignKey("hoimsystem_users.user_id"), nullable=False),
            sa.Column("drip_rate", sa.Integer(), nullable=False),
            sa.Column("volume", sa.Integer(), nullable=True),
            sa.Column("condition", sa.String(length=200), nullable=False),
            sa.Column("observe_time", sa.DateTime(), nullable=False),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("hoimsystem_infusion_observation"):
        op.drop_table("hoimsystem_infusion_observation")
    if inspector.has_table("hoimsystem_infusion_order"):
        op.drop_table("hoimsystem_infusion_order")
