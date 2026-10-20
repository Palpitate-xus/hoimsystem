"""Add explicit execution start and worker ownership to durable AI tasks."""

import sqlalchemy as sa

from alembic import op

revision = "20261020_ai_task_leases"
down_revision = "20261020_ai_platform"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Enable stale-worker detection without silently retrying model calls."""
    op.add_column("hoimsystem_ai_run", sa.Column("start_time", sa.DateTime(), nullable=True))
    op.add_column("hoimsystem_ai_run", sa.Column("lease_token", sa.String(36), nullable=True))


def downgrade() -> None:
    """Remove only the task lease extension."""
    with op.batch_alter_table("hoimsystem_ai_run") as batch:
        batch.drop_column("lease_token")
        batch.drop_column("start_time")
