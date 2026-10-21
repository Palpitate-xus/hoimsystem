"""Join independent governed document and charge additive migrations.

Revision ID: 20261021_charge_doc_merge
Revises: 20261021_doc_extraction_runs, 20261021_charge_runs
"""

revision = "20261021_charge_doc_merge"
down_revision = ("20261021_doc_extraction_runs", "20261021_charge_runs")
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
