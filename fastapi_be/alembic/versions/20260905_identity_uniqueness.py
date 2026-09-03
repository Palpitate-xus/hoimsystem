"""enforce unique login names and patient identities

Revision ID: 20260905_identity_uniqueness
Revises: 20260904_query_indexes
Create Date: 2026-09-03
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260905_identity_uniqueness"
down_revision: str | Sequence[str] | None = "20260904_query_indexes"
branch_labels = None
depends_on = None

UNIQUE_IDENTITIES = (
    ("hoimsystem_users", "username", "idx_users_username", "uq_users_username"),
    ("hoimsystem_patient", "identity", "idx_patient_identity", "uq_patient_identity"),
)


def _assert_no_duplicates(table_name: str, column_name: str) -> None:
    bind = op.get_bind()
    duplicates = bind.execute(
        sa.text(
            f'SELECT "{column_name}", COUNT(*) AS duplicate_count '
            f'FROM "{table_name}" WHERE "{column_name}" IS NOT NULL '
            f'GROUP BY "{column_name}" HAVING COUNT(*) > 1 LIMIT 10'
        )
    ).fetchall()
    if duplicates:
        values = ", ".join(repr(row[0]) for row in duplicates)
        raise RuntimeError(
            f"Cannot enforce {table_name}.{column_name} uniqueness; "
            f"resolve duplicate values first: {values}"
        )


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    for table_name, column_name, old_index, unique_index in UNIQUE_IDENTITIES:
        if not inspector.has_table(table_name):
            continue
        _assert_no_duplicates(table_name, column_name)
        indexes = {item["name"]: item for item in inspector.get_indexes(table_name)}
        if old_index in indexes:
            op.drop_index(old_index, table_name=table_name)
        if unique_index not in indexes:
            op.create_index(unique_index, table_name, [column_name], unique=True)
        inspector = sa.inspect(op.get_bind())


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    for table_name, column_name, old_index, unique_index in reversed(UNIQUE_IDENTITIES):
        if not inspector.has_table(table_name):
            continue
        indexes = {item["name"]: item for item in inspector.get_indexes(table_name)}
        if unique_index in indexes:
            op.drop_index(unique_index, table_name=table_name)
        if old_index not in indexes:
            op.create_index(old_index, table_name, [column_name], unique=False)
        inspector = sa.inspect(op.get_bind())
