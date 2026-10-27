"""Retain unknown generic text usage without manufacturing zero counters."""

import sqlalchemy as sa

from alembic import op

revision = "20261027_text_retry_usage"
down_revision = "20261027_ai_provider_retry"
branch_labels = None
depends_on = None

TABLE = "hoimsystem_ai_run"
FIELDS = ("input_tokens", "output_tokens")


def upgrade():
    with op.batch_alter_table(TABLE) as batch:
        for name in FIELDS:
            batch.alter_column(name, existing_type=sa.Integer(), existing_nullable=False, nullable=True)


def downgrade():
    table = sa.table(TABLE, *(sa.column(name, sa.Integer()) for name in FIELDS))
    if op.get_bind().scalar(sa.select(sa.literal(1)).select_from(table).where(sa.or_(*(table.c[name].is_(None) for name in FIELDS))).limit(1)):
        raise RuntimeError("Cannot downgrade text usage while actual token counters are unknown; unknown must not become zero")
    with op.batch_alter_table(TABLE) as batch:
        for name in FIELDS:
            batch.alter_column(name, existing_type=sa.Integer(), existing_nullable=True, nullable=False)
