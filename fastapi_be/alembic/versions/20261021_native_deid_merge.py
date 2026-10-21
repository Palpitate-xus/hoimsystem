"""Join the complete expanded/research and additive75 task histories.

This node changes no table, row or earlier historical migration.
"""

revision = "20261021_native_deid_merge"
down_revision = ("20261021_native_research_merge", "20261021_deid_dispatch")
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
