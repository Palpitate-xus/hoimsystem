"""Preserve unknown units on historical prescription rules rather than infer a dose basis."""

import sqlalchemy as sa

from alembic import op

revision = "20261020_dose_rule_units"
down_revision = "20261020_diagnosis_review"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("hoimsystem_rx_review_rule", sa.Column("dose_unit", sa.String(24), nullable=True))


def downgrade() -> None:
    op.drop_column("hoimsystem_rx_review_rule", "dose_unit")
