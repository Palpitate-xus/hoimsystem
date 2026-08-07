"""add daily outpatient registration counter"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260808_registration_counter"
down_revision: str | Sequence[str] | None = "20260807_navigation_graph"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    if not sa.inspect(bind).has_table("hoimsystem_registration_counter"):
        op.create_table(
            "hoimsystem_registration_counter",
            sa.Column("counter_date", sa.Date(), primary_key=True),
            sa.Column("next_number", sa.Integer(), nullable=False, server_default="1"),
        )
    inspector = sa.inspect(bind)
    if inspector.has_table("hoimsystem_registration") and "idx_registration_time_number" not in {index["name"] for index in inspector.get_indexes("hoimsystem_registration")}:
        op.create_index("idx_registration_time_number", "hoimsystem_registration", ["time", "registration_id"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("hoimsystem_registration") and "idx_registration_time_number" in {index["name"] for index in inspector.get_indexes("hoimsystem_registration")}:
        op.drop_index("idx_registration_time_number", table_name="hoimsystem_registration")
    if inspector.has_table("hoimsystem_registration_counter"):
        op.drop_table("hoimsystem_registration_counter")
