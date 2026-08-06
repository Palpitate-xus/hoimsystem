"""add perioperative antibiotic prophylaxis records"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260806_perioperative_antibiotic"
down_revision: str | Sequence[str] | None = "20260806_imaging_film"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if not sa.inspect(op.get_bind()).has_table("hoimsystem_perioperative_antibiotic"):
        op.create_table(
            "hoimsystem_perioperative_antibiotic",
            sa.Column("perioperative_id", sa.String(36), primary_key=True),
            sa.Column("application_id", sa.String(36), sa.ForeignKey("hoimsystem_surgery_application.application_id"), nullable=False),
            sa.Column("patient_id", sa.Integer(), sa.ForeignKey("hoimsystem_patient.patient_id"), nullable=False),
            sa.Column("pharmaceutical_id", sa.Integer(), sa.ForeignKey("hoimsystem_pharmaceutical.pharmaceutical_id"), nullable=False),
            sa.Column("prescriber_id", sa.Integer(), sa.ForeignKey("hoimsystem_users.user_id"), nullable=False),
            sa.Column("dose", sa.String(100), nullable=False),
            sa.Column("timing_minutes", sa.Integer(), nullable=False, server_default="30"),
            sa.Column("indication", sa.String(300)),
            sa.Column("status", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("administered_time", sa.DateTime()),
            sa.Column("create_time", sa.DateTime(), nullable=False),
        )


def downgrade() -> None:
    op.drop_table("hoimsystem_perioperative_antibiotic")
