"""add daily operational analytics summary

Revision ID: 20260910_daily_analytics
Revises: 20260909_automatic_drg
Create Date: 2026-09-03
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260910_daily_analytics"
down_revision: str | Sequence[str] | None = "20260909_automatic_drg"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("hoimsystem_payment", sa.Column("refunded_time", sa.DateTime()))
    op.create_table(
        "hoimsystem_daily_operational_metric",
        sa.Column("metric_date", sa.Date(), primary_key=True),
        sa.Column("outpatient_visits", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("emergency_visits", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("admissions", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("discharges", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("active_inpatients", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("prescriptions", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("lab_orders", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("imaging_orders", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("critical_labs", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("successful_payments", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("revenue", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("refunds", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("average_queue_wait_minutes", sa.Numeric(10, 2)),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("hoimsystem_daily_operational_metric")
    op.drop_column("hoimsystem_payment", "refunded_time")
