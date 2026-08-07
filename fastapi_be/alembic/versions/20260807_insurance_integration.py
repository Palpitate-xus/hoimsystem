"""add external medical insurance settlement tracking"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260807_insurance_integration"
down_revision: str | Sequence[str] | None = "20260807_integration_bridge"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    table_name = "hoimsystem_insurance_settlement"
    inspector = sa.inspect(bind)
    if not inspector.has_table(table_name):
        return
    existing = {column["name"] for column in inspector.get_columns(table_name)}
    fields = (
        ("external_settlement_id", sa.String(length=100), None),
        ("integration_status", sa.String(length=20), sa.text("'local'")),
        ("last_sync_time", sa.DateTime(), None),
    )
    for name, field_type, default in fields:
        if name not in existing:
            kwargs = {"nullable": False} if name == "integration_status" else {"nullable": True}
            if default is not None:
                kwargs["server_default"] = default
            op.add_column(table_name, sa.Column(name, field_type, **kwargs))
    index_name = "idx_insurance_settlement_external_id"
    if index_name not in {index["name"] for index in sa.inspect(bind).get_indexes(table_name)}:
        op.create_index(index_name, table_name, ["external_settlement_id"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    table_name = "hoimsystem_insurance_settlement"
    inspector = sa.inspect(bind)
    if not inspector.has_table(table_name):
        return
    index_name = "idx_insurance_settlement_external_id"
    if index_name in {index["name"] for index in inspector.get_indexes(table_name)}:
        op.drop_index(index_name, table_name=table_name)
    existing = {column["name"] for column in inspector.get_columns(table_name)}
    for name in ("last_sync_time", "integration_status", "external_settlement_id"):
        if name in existing:
            op.drop_column(table_name, name)
