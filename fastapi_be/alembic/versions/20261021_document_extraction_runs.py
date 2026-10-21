"""Add immutable original-bound extraction task anchors without changing Run."""

import sqlalchemy as sa
from sqlalchemy.dialects import mysql

from alembic import op

# Alembic's existing version_num is VARCHAR(32); the descriptive filename need
# not be the revision identifier.
revision = "20261021_doc_extraction_runs"
down_revision = "20261021_document_evidence"
branch_labels = None
depends_on = None

HASH_FIELDS = (
    "original_content_hash",
    "original_governance_hash",
    "source_digest",
    "prompt_hash",
    "context_digest",
    "input_hash",
    "evidence_hash",
    "metadata_hash",
)


def hash_constraint(field):
    remainder = field
    for character in "0123456789abcdef":
        remainder = f"replace({remainder}, '{character}', '')"
    return sa.CheckConstraint(f"length({field}) = 64 AND length({remainder}) = 0", name=f"ck_doc_extract_{field}")


def upgrade():
    op.create_table(
        "hoimsystem_ai_document_extraction_run_anchor",
        sa.Column("run_id", sa.String(36), sa.ForeignKey("hoimsystem_ai_run.run_id"), primary_key=True),
        sa.Column("original_id", sa.String(36), sa.ForeignKey("hoimsystem_ai_document_original.original_id"), nullable=False),
        sa.Column("requested_by", sa.Integer(), sa.ForeignKey("hoimsystem_users.user_id"), nullable=False),
        sa.Column("schema_version", sa.String(48), nullable=False),
        sa.Column("recorded_at", sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=False),
        *(sa.Column(field, sa.String(64), nullable=False) for field in HASH_FIELDS),
        sa.CheckConstraint("schema_version = 'document_extraction_run_anchor_v1'", name="ck_doc_extract_schema"),
        sa.CheckConstraint("requested_by > 0", name="ck_doc_extract_actor"),
        *(hash_constraint(field) for field in HASH_FIELDS),
    )
    op.create_index("idx_doc_extract_original", "hoimsystem_ai_document_extraction_run_anchor", ["original_id", "recorded_at"])


def downgrade():
    op.drop_table("hoimsystem_ai_document_extraction_run_anchor")
