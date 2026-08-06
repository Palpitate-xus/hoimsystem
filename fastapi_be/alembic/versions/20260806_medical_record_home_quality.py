"""add medical record home quality"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260806_medical_record_home_quality"
down_revision: str | Sequence[str] | None = "20260806_icd10"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    if sa.inspect(bind).has_table("hoimsystem_medical_record_home_quality"):
        return
    op.create_table("hoimsystem_medical_record_home_quality", sa.Column("quality_id", sa.String(length=36), primary_key=True), sa.Column("home_id", sa.String(length=36), sa.ForeignKey("hoimsystem_medical_record_home.home_id"), nullable=False), sa.Column("check_item", sa.String(length=100), nullable=False), sa.Column("check_result", sa.Integer(), nullable=False, server_default="0"), sa.Column("issue", sa.String(length=500), nullable=True), sa.Column("score", sa.Integer(), nullable=False, server_default="100"), sa.Column("checker_id", sa.Integer(), sa.ForeignKey("hoimsystem_users.user_id"), nullable=False), sa.Column("check_time", sa.DateTime(), nullable=False))


def downgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("hoimsystem_medical_record_home_quality"):
        op.drop_table("hoimsystem_medical_record_home_quality")
