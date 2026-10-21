"""First transaction boundary for actual ledger writers and complete capture."""

import sqlalchemy as sa

from alembic import op

revision = "20261021_charge_gate"
down_revision = "20261021_coding_evidence"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "hoimsystem_ai_charge_write_gate",
        sa.Column("gate_id", sa.Integer(), nullable=False, primary_key=True, autoincrement=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.CheckConstraint("gate_id=1 AND revision>0", name="ck_charge_gate_singleton"),
    )
    op.execute(sa.text("INSERT INTO hoimsystem_ai_charge_write_gate(gate_id,revision) VALUES(1,1)"))


def downgrade():
    op.drop_table("hoimsystem_ai_charge_write_gate")
