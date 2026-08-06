"""add response time to operation logs"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260806_monitor_response_time"
down_revision: str | Sequence[str] | None = "20260806_window_appointment"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("hoimsystem_operation_log")}
    if "response_time_ms" not in columns:
        op.add_column("hoimsystem_operation_log", sa.Column("response_time_ms", sa.Float(), nullable=True))


def downgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("hoimsystem_operation_log")}
    if "response_time_ms" in columns:
        op.drop_column("hoimsystem_operation_log", "response_time_ms")
