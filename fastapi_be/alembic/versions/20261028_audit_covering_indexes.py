"""Cover audit ranking aggregates without loading complete log rows."""

import sqlalchemy as sa

from alembic import op

revision = "20261028_audit_covering"
down_revision = "20261027_text_retry_usage"
branch_labels = None
depends_on = None

TABLE = "hoimsystem_operation_log"
INDEXES = (("idx_operation_log_username", "username"), ("idx_operation_log_action", "action"))


def upgrade():
    connection = op.get_bind()
    existing = {index["name"] for index in sa.inspect(connection).get_indexes(TABLE)}
    if connection.dialect.name == "postgresql":
        # Concurrent creation lets audit writes continue on an existing large table.
        with op.get_context().autocommit_block():
            for name, column in INDEXES:
                if name not in existing:
                    op.create_index(name, TABLE, [column], postgresql_concurrently=True)
    else:
        for name, column in INDEXES:
            if name not in existing:
                op.create_index(name, TABLE, [column])


def downgrade():
    connection = op.get_bind()
    existing = {index["name"] for index in sa.inspect(connection).get_indexes(TABLE)}
    if connection.dialect.name == "postgresql":
        with op.get_context().autocommit_block():
            for name, _column in reversed(INDEXES):
                if name in existing:
                    op.drop_index(name, TABLE, postgresql_concurrently=True)
    else:
        for name, _column in reversed(INDEXES):
            if name in existing:
                op.drop_index(name, TABLE)
