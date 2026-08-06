"""add antibiotic escalation approvals"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260806_antibiotic_approval"
down_revision: str | Sequence[str] | None = "20260806_imaging"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if not sa.inspect(op.get_bind()).has_table("hoimsystem_antibiotic_approval"):
        op.create_table(
            "hoimsystem_antibiotic_approval",
            sa.Column("approval_id", sa.String(36), primary_key=True),
            sa.Column("pharmaceutical_id", sa.Integer(), sa.ForeignKey("hoimsystem_pharmaceutical.pharmaceutical_id"), nullable=False),
            sa.Column("patient_id", sa.Integer(), sa.ForeignKey("hoimsystem_patient.patient_id")),
            sa.Column("prescription_id", sa.String(36), sa.ForeignKey("hoimsystem_prescription.prescription_id")),
            sa.Column("applicant_id", sa.Integer(), sa.ForeignKey("hoimsystem_users.user_id"), nullable=False),
            sa.Column("reason", sa.String(300), nullable=False),
            sa.Column("status", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("reviewer_id", sa.Integer(), sa.ForeignKey("hoimsystem_users.user_id")),
            sa.Column("review_note", sa.String(300)),
            sa.Column("create_time", sa.DateTime(), nullable=False),
            sa.Column("review_time", sa.DateTime()),
        )


def downgrade() -> None:
    op.drop_table("hoimsystem_antibiotic_approval")
