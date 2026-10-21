"""Add one inventory write serialization row; never changes business stock."""

import sqlalchemy as sa

from alembic import op

revision = "20261021_inventory_gate"
down_revision = "20261020_supply_series"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "hoimsystem_ai_inventory_write_gate",
        sa.Column("gate_id", sa.Integer(), primary_key=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.CheckConstraint("gate_id = 1 AND revision > 0", name="ck_inventory_gate_singleton"),
    )
    op.execute(sa.text("INSERT INTO hoimsystem_ai_inventory_write_gate (gate_id,revision) VALUES (1,1)"))


def downgrade():
    op.drop_table("hoimsystem_ai_inventory_write_gate")
