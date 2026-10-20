"""Keep source edits distinct even when a pathway is later restored to identical content."""

import sqlalchemy as sa

from alembic import op

revision = "20261020_pathway_revision"
down_revision = "20261020_pathway_knowledge"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("hoimsystem_clinical_pathway", sa.Column("source_revision", sa.Integer(), nullable=False, server_default="1"))


def downgrade():
    with op.batch_alter_table("hoimsystem_clinical_pathway") as batch:
        batch.drop_column("source_revision")
