"""Persist outpatient dose, unit, frequency, route and duration without guessing legacy values."""

import sqlalchemy as sa

from alembic import op

revision = "20261020_rx_instructions"
down_revision = "20261020_ai_task_leases"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Keep old prescriptions intact; missing instructions remain NULL."""
    op.add_column("hoimsystem_pre_pha", sa.Column("dosage", sa.Numeric(18, 6), nullable=True))
    op.add_column("hoimsystem_pre_pha", sa.Column("dose_unit", sa.String(24), nullable=True))
    op.add_column("hoimsystem_pre_pha", sa.Column("frequency", sa.String(40), nullable=True))
    op.add_column("hoimsystem_pre_pha", sa.Column("route", sa.String(24), nullable=True))
    op.add_column("hoimsystem_pre_pha", sa.Column("duration_days", sa.Integer(), nullable=True))


def downgrade() -> None:
    """Remove only instruction fields; retain the original prescription quantities."""
    with op.batch_alter_table("hoimsystem_pre_pha") as batch:
        for name in ("duration_days", "route", "frequency", "dose_unit", "dosage"):
            batch.drop_column(name)
