"""Bounded text retries; existing providers retain their single-attempt policy."""

import sqlalchemy as sa

from alembic import op

revision = "20261027_ai_provider_retry"
down_revision = "20261023_native_variables_merge"
branch_labels = None
depends_on = None

TABLE = "hoimsystem_ai_provider"
CHECK = "ck_ai_provider_max_attempts"


def upgrade():
    # Fill only this newly introduced column. Provider revisions, credentials,
    # queued tasks and original snapshot bytes remain untouched.
    with op.batch_alter_table(TABLE) as batch:
        batch.add_column(sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="1"))
    with op.batch_alter_table(TABLE) as batch:
        batch.alter_column("max_attempts", existing_type=sa.Integer(), existing_nullable=False, server_default="3")
        batch.create_check_constraint(CHECK, "max_attempts BETWEEN 1 AND 3")


def downgrade():
    with op.batch_alter_table(TABLE) as batch:
        batch.drop_constraint(CHECK, type_="check")
        batch.drop_column("max_attempts")
