"""add structured clinical context to prescription review

Revision ID: 20260908_clinical_decision_support
Revises: 20260907_emar_barcode
Create Date: 2026-09-03
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260908_clinical_decision_support"
down_revision: str | Sequence[str] | None = "20260907_emar_barcode"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "hoimsystem_patient_clinical_profile",
        sa.Column("patient_id", sa.Integer(), sa.ForeignKey("hoimsystem_patient.patient_id"), primary_key=True),
        sa.Column("pregnant", sa.Integer()),
        sa.Column("egfr", sa.Numeric(8, 2)),
        sa.Column("hepatic_impairment", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("diagnoses_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("labs_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("updated_by", sa.Integer(), sa.ForeignKey("hoimsystem_users.user_id"), nullable=False),
        sa.Column("update_time", sa.DateTime(), nullable=False),
    )
    with op.batch_alter_table("hoimsystem_rx_review_rule") as batch:
        batch.add_column(sa.Column("condition_json", sa.Text()))
        batch.add_column(sa.Column("source", sa.String(100)))
        batch.add_column(sa.Column("version", sa.String(30)))
        batch.add_column(sa.Column("effective_from", sa.Date()))
        batch.add_column(sa.Column("effective_to", sa.Date()))
        batch.add_column(sa.Column("update_time", sa.DateTime()))
        batch.add_column(sa.Column("updated_by", sa.Integer(), sa.ForeignKey("hoimsystem_users.user_id")))


def downgrade() -> None:
    with op.batch_alter_table("hoimsystem_rx_review_rule") as batch:
        batch.drop_column("updated_by")
        batch.drop_column("update_time")
        batch.drop_column("effective_to")
        batch.drop_column("effective_from")
        batch.drop_column("version")
        batch.drop_column("source")
        batch.drop_column("condition_json")
    op.drop_table("hoimsystem_patient_clinical_profile")
