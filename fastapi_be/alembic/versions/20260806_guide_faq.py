"""add guide FAQ"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260806_guide_faq"
down_revision: str | Sequence[str] | None = "20260806_lab_qc"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    if sa.inspect(bind).has_table("hoimsystem_guide_faq"):
        return
    op.create_table("hoimsystem_guide_faq", sa.Column("faq_id", sa.Integer(), primary_key=True, autoincrement=True), sa.Column("question", sa.String(length=200), nullable=False), sa.Column("answer", sa.Text(), nullable=False), sa.Column("category", sa.String(length=50), nullable=True), sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"), sa.Column("status", sa.Integer(), nullable=False, server_default="1"), sa.Column("create_time", sa.DateTime(), nullable=False), sa.Column("update_time", sa.DateTime(), nullable=False))


def downgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("hoimsystem_guide_faq"):
        op.drop_table("hoimsystem_guide_faq")
