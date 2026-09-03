"""add eMAR barcode medication safety loop

Revision ID: 20260907_emar_barcode
Revises: 20260906_integration_outbox
Create Date: 2026-09-03
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260907_emar_barcode"
down_revision: str | Sequence[str] | None = "20260906_integration_outbox"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("hoimsystem_pharmaceutical", sa.Column("barcode", sa.String(64)))
    op.create_index("uq_pharmaceutical_barcode", "hoimsystem_pharmaceutical", ["barcode"], unique=True)
    op.create_table(
        "hoimsystem_medication_administration",
        sa.Column("administration_id", sa.String(36), primary_key=True),
        sa.Column("execution_id", sa.Integer(), sa.ForeignKey("hoimsystem_order_execution.execution_id"), nullable=False),
        sa.Column("order_id", sa.String(36), sa.ForeignKey("hoimsystem_inpatient_order.order_id"), nullable=False),
        sa.Column("patient_id", sa.Integer(), sa.ForeignKey("hoimsystem_patient.patient_id"), nullable=False),
        sa.Column("nurse_id", sa.Integer(), sa.ForeignKey("hoimsystem_users.user_id"), nullable=False),
        sa.Column("patient_barcode", sa.String(64), nullable=False),
        sa.Column("medication_barcodes_json", sa.Text(), nullable=False),
        sa.Column("status", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("verified_at", sa.DateTime(), nullable=False),
        sa.Column("administration_time", sa.DateTime()),
        sa.Column("note", sa.String(300)),
        sa.UniqueConstraint("execution_id", name="uq_medication_administration_execution"),
    )
    op.create_index(
        "idx_medication_administration_patient_time",
        "hoimsystem_medication_administration",
        ["patient_id", "administration_time"],
    )


def downgrade() -> None:
    op.drop_index(
        "idx_medication_administration_patient_time",
        table_name="hoimsystem_medication_administration",
    )
    op.drop_table("hoimsystem_medication_administration")
    op.drop_index("uq_pharmaceutical_barcode", table_name="hoimsystem_pharmaceutical")
    op.drop_column("hoimsystem_pharmaceutical", "barcode")
