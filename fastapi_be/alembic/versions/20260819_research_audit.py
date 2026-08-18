"""research export audit table

Revision ID: 20260819_research_audit
Revises: 20260819_signature_record
Create Date: 2026-08-19
"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260819_research_audit"
down_revision: str | Sequence[str] | None = "20260819_signature_record"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "hoimsystem_research_export_audit",
        sa.Column("audit_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("hoimsystem_users.user_id"), nullable=False),
        sa.Column("table_name", sa.String(50), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("anonymize", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("create_time", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("hoimsystem_research_export_audit")
