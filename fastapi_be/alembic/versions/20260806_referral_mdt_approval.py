"""add audit fields for referral and MDT approvals"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260806_referral_mdt_approval"
down_revision: str | Sequence[str] | None = "20260806_monitor_response_time"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _add_columns(table: str) -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns(table)}
    with op.batch_alter_table(table) as batch:
        if "applicant_id" not in columns:
            batch.add_column(sa.Column("applicant_id", sa.Integer(), nullable=True))
            batch.create_foreign_key(f"fk_{table}_applicant_user", "hoimsystem_users", ["applicant_id"], ["user_id"])
        if "reviewer_id" not in columns:
            batch.add_column(sa.Column("reviewer_id", sa.Integer(), nullable=True))
            batch.create_foreign_key(f"fk_{table}_reviewer_user", "hoimsystem_users", ["reviewer_id"], ["user_id"])
        if "review_time" not in columns:
            batch.add_column(sa.Column("review_time", sa.DateTime(), nullable=True))
        if "review_note" not in columns:
            batch.add_column(sa.Column("review_note", sa.String(length=200), nullable=True))


def upgrade() -> None:
    _add_columns("hoimsystem_referral")
    _add_columns("hoimsystem_mdt_case")


def downgrade() -> None:
    for table in ("hoimsystem_mdt_case", "hoimsystem_referral"):
        with op.batch_alter_table(table) as batch:
            for name in ("review_note", "review_time", "reviewer_id", "applicant_id"):
                batch.drop_column(name)
