"""病案首页 ICD 编码绑定表

Revision ID: 20260823_home_icd
Revises: 20260822_borrow_perf
Create Date: 2026-08-23
"""
import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260823_home_icd"
down_revision: str | None = "20260822_borrow_perf"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "hoimsystem_home_icd_binding",
        sa.Column("binding_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("home_id", sa.String(36), sa.ForeignKey("hoimsystem_medical_record_home.home_id"), nullable=False, index=True),
        sa.Column("kind", sa.String(10), nullable=False),
        sa.Column("icd_code", sa.String(20), nullable=False),
        sa.Column("icd_name", sa.String(200), nullable=False),
        sa.Column("is_primary", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("coder_id", sa.Integer(), sa.ForeignKey("hoimsystem_users.user_id"), nullable=False),
        sa.Column("code_time", sa.DateTime(), nullable=False),
        sa.Column("remark", sa.String(300), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("hoimsystem_home_icd_binding")
