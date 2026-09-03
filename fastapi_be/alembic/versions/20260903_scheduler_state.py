"""persist scheduler state

Revision ID: 20260903_scheduler_state
Revises: 20260823_home_icd
Create Date: 2026-09-03
"""

import sqlalchemy as sa

from alembic import op

revision: str = "20260903_scheduler_state"
down_revision: str | None = "20260823_home_icd"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "hoimsystem_scheduler_job_state",
        sa.Column("job_name", sa.String(64), primary_key=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="idle"),
        sa.Column("owner", sa.String(128)),
        sa.Column("last_started_at", sa.DateTime()),
        sa.Column("last_finished_at", sa.DateTime()),
        sa.Column("last_result_json", sa.Text()),
        sa.Column("last_error", sa.String(1000)),
    )


def downgrade() -> None:
    op.drop_table("hoimsystem_scheduler_job_state")
