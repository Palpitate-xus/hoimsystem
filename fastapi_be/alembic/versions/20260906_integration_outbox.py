"""add durable integration outbox

Revision ID: 20260906_integration_outbox
Revises: 20260905_identity_uniqueness
Create Date: 2026-09-03
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260906_integration_outbox"
down_revision: str | Sequence[str] | None = "20260905_identity_uniqueness"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "hoimsystem_integration_outbox",
        sa.Column("event_id", sa.String(36), primary_key=True),
        sa.Column("destination", sa.String(30), nullable=False),
        sa.Column("event_type", sa.String(80), nullable=False),
        sa.Column("aggregate_type", sa.String(50), nullable=False),
        sa.Column("aggregate_id", sa.String(100), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_attempt_at", sa.DateTime(), nullable=False),
        sa.Column("last_attempt_at", sa.DateTime()),
        sa.Column("delivered_at", sa.DateTime()),
        sa.Column("last_http_status", sa.Integer()),
        sa.Column("last_error", sa.String(1000)),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "idx_integration_outbox_due",
        "hoimsystem_integration_outbox",
        ["status", "next_attempt_at"],
    )
    op.create_index(
        "idx_integration_outbox_aggregate",
        "hoimsystem_integration_outbox",
        ["aggregate_type", "aggregate_id"],
    )


def downgrade() -> None:
    op.drop_index("idx_integration_outbox_aggregate", table_name="hoimsystem_integration_outbox")
    op.drop_index("idx_integration_outbox_due", table_name="hoimsystem_integration_outbox")
    op.drop_table("hoimsystem_integration_outbox")
