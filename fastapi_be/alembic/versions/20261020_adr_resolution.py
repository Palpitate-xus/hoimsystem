"""Separate recorded ADR handling outcomes without guessing legacy status two."""

import sqlalchemy as sa

from alembic import op

revision = "20261020_adr_resolution"
down_revision = "20261020_ai_review_excerpts"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("hoimsystem_adverse_reaction") as batch:
        batch.add_column(sa.Column("status_resolution", sa.String(24), nullable=True))
        batch.add_column(sa.Column("resolution_note", sa.String(1000), nullable=True))
        batch.add_column(sa.Column("status_reviewed_by", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("status_reviewed_at", sa.DateTime(), nullable=True))
        batch.create_foreign_key("fk_adr_status_reviewer", "hoimsystem_users", ["status_reviewed_by"], ["user_id"])


def downgrade():
    with op.batch_alter_table("hoimsystem_adverse_reaction") as batch:
        batch.drop_constraint("fk_adr_status_reviewer", type_="foreignkey")
        for name in ("status_reviewed_at", "status_reviewed_by", "resolution_note", "status_resolution"):
            batch.drop_column(name)
