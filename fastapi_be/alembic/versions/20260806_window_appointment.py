"""add window appointment confirmation fields"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260806_window_appointment"
down_revision: str | Sequence[str] | None = "20260806_guide_faq"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns("hoimsystem_appointment")}
    if "confirmed" not in columns:
        op.add_column("hoimsystem_appointment", sa.Column("confirmed", sa.Integer(), nullable=False, server_default="0"))
    if "confirmed_time" not in columns:
        op.add_column("hoimsystem_appointment", sa.Column("confirmed_time", sa.DateTime(), nullable=True))
    if "confirmed_by" not in columns:
        op.add_column("hoimsystem_appointment", sa.Column("confirmed_by", sa.Integer(), sa.ForeignKey("hoimsystem_users.user_id"), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns("hoimsystem_appointment")}
    for name in ("confirmed_by", "confirmed_time", "confirmed"):
        if name in columns:
            op.drop_column("hoimsystem_appointment", name)
