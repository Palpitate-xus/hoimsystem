"""add structured patient allergy records"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260806_patient_allergy"
down_revision: str | Sequence[str] | None = "20260806_skin_test"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    if sa.inspect(bind).has_table("hoimsystem_patient_allergy"):
        return
    op.create_table(
        "hoimsystem_patient_allergy",
        sa.Column("allergy_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("patient_id", sa.Integer(), sa.ForeignKey("hoimsystem_patient.patient_id"), nullable=False),
        sa.Column("allergen", sa.String(length=100), nullable=False),
        sa.Column("reaction", sa.String(length=200), nullable=False),
        sa.Column("severity", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("note", sa.String(length=200), nullable=True),
        sa.Column("status", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("reporter_id", sa.Integer(), sa.ForeignKey("hoimsystem_users.user_id"), nullable=False),
        sa.Column("create_time", sa.DateTime(), nullable=False),
        sa.Column("update_time", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("hoimsystem_patient_allergy"):
        op.drop_table("hoimsystem_patient_allergy")
