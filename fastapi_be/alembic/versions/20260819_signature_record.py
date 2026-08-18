"""digital signature records

Revision ID: 20260819_signature_record
Revises: 20260819_lab_auditor
Create Date: 2026-08-19
"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260819_signature_record"
down_revision: str | Sequence[str] | None = "20260819_lab_auditor"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "hoimsystem_digital_signature_record",
        sa.Column("signature_id", sa.String(36), primary_key=True),
        sa.Column("signer_id", sa.Integer(), sa.ForeignKey("hoimsystem_users.user_id"), nullable=False),
        sa.Column("doc_type", sa.String(30), nullable=False, server_default="generic"),
        sa.Column("reference_id", sa.String(60), nullable=True),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("sign_hash", sa.String(64), nullable=False),
        sa.Column("sign_time", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("hoimsystem_digital_signature_record")
