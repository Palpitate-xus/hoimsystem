"""add medical record archive"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260806_medical_record_archive"
down_revision: str | Sequence[str] | None = "20260806_medical_record_home"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    if sa.inspect(bind).has_table("hoimsystem_medical_record_archive"):
        return
    op.create_table(
        "hoimsystem_medical_record_archive",
        sa.Column("archive_id", sa.String(length=36), primary_key=True),
        sa.Column("home_id", sa.String(length=36), sa.ForeignKey("hoimsystem_medical_record_home.home_id"), nullable=False, unique=True),
        sa.Column("archive_no", sa.String(length=40), nullable=False, unique=True),
        sa.Column("location", sa.String(length=100), nullable=True),
        sa.Column("status", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("borrower_id", sa.Integer(), sa.ForeignKey("hoimsystem_users.user_id"), nullable=True),
        sa.Column("borrow_reason", sa.String(length=300), nullable=True),
        sa.Column("borrow_time", sa.DateTime(), nullable=True),
        sa.Column("return_time", sa.DateTime(), nullable=True),
        sa.Column("archived_by", sa.Integer(), sa.ForeignKey("hoimsystem_users.user_id"), nullable=True),
        sa.Column("archive_time", sa.DateTime(), nullable=True),
        sa.Column("seal_reason", sa.String(length=300), nullable=True),
        sa.Column("create_time", sa.DateTime(), nullable=False),
        sa.Column("update_time", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("hoimsystem_medical_record_archive"):
        op.drop_table("hoimsystem_medical_record_archive")
