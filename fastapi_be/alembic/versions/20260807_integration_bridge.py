"""add LIS/PACS integration tracking fields"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260807_integration_bridge"
down_revision: str | Sequence[str] | None = "20260807_multi_campus"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_FIELDS = {
    "hoimsystem_lab_order": [
        ("external_order_id", sa.String(length=100), None),
        ("integration_status", sa.String(length=20), "'pending'"),
        ("last_sync_time", sa.DateTime(), None),
    ],
    "hoimsystem_imaging_order": [
        ("external_order_id", sa.String(length=100), None),
        ("integration_status", sa.String(length=20), "'pending'"),
        ("last_sync_time", sa.DateTime(), None),
    ],
}


def upgrade() -> None:
    bind = op.get_bind()
    for table_name, fields in _FIELDS.items():
        inspector = sa.inspect(bind)
        if not inspector.has_table(table_name):
            continue
        existing = {column["name"] for column in inspector.get_columns(table_name)}
        for name, field_type, default in fields:
            if name in existing:
                continue
            kwargs = {"nullable": False} if name == "integration_status" else {"nullable": True}
            if default is not None:
                kwargs["server_default"] = sa.text(default)
            op.add_column(table_name, sa.Column(name, field_type, **kwargs))
        index_name = f"idx_{table_name.removeprefix('hoimsystem_')}_external_order"
        indexes = {index["name"] for index in sa.inspect(bind).get_indexes(table_name)}
        if index_name not in indexes:
            op.create_index(index_name, table_name, ["external_order_id"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    for table_name, fields in _FIELDS.items():
        inspector = sa.inspect(bind)
        if not inspector.has_table(table_name):
            continue
        index_name = f"idx_{table_name.removeprefix('hoimsystem_')}_external_order"
        if index_name in {index["name"] for index in inspector.get_indexes(table_name)}:
            op.drop_index(index_name, table_name=table_name)
        existing = {column["name"] for column in inspector.get_columns(table_name)}
        for name, _, _ in reversed(fields):
            if name in existing:
                op.drop_column(table_name, name)
