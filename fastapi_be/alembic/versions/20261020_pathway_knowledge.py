"""Bind reviewed knowledge snapshots to the exact clinical pathway source version."""

import sqlalchemy as sa

from alembic import op

revision = "20261020_pathway_knowledge"
down_revision = "20261020_adr_resolution"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("hoimsystem_ai_knowledge_document", sa.Column("source_kind", sa.String(40), nullable=True))
    op.add_column("hoimsystem_ai_knowledge_document", sa.Column("source_reference_id", sa.Integer(), nullable=True))
    op.add_column("hoimsystem_ai_knowledge_document", sa.Column("source_snapshot_hash", sa.String(64), nullable=True))
    op.create_index("idx_ai_knowledge_source", "hoimsystem_ai_knowledge_document", ["source_kind", "source_reference_id"])


def downgrade():
    op.drop_index("idx_ai_knowledge_source", table_name="hoimsystem_ai_knowledge_document")
    with op.batch_alter_table("hoimsystem_ai_knowledge_document") as batch:
        for name in ("source_snapshot_hash", "source_reference_id", "source_kind"):
            batch.drop_column(name)
