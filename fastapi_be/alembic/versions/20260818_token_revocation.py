"""add token invalidation and login lockout persistence

- users.token_invalid_before: tokens issued before this time are rejected,
  enabling logout / password-change revocation without a server-side session table
- login_lockouts: persistent failed-login counters shared across gunicorn workers
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260818_token_revocation"
down_revision: str | Sequence[str] | None = "20260817_inpatient_charge_audit"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if inspector.has_table("hoimsystem_users"):
        columns = {column["name"] for column in inspector.get_columns("hoimsystem_users")}
        with op.batch_alter_table("hoimsystem_users") as batch_op:
            if "token_invalid_before" not in columns:
                batch_op.add_column(sa.Column("token_invalid_before", sa.DateTime(), nullable=True))

    if not inspector.has_table("hoimsystem_login_lockouts"):
        op.create_table(
            "hoimsystem_login_lockouts",
            sa.Column("lock_key", sa.String(120), primary_key=True),
            sa.Column("fail_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("locked_until", sa.DateTime(), nullable=True),
            sa.Column("update_time", sa.DateTime(), nullable=False),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if inspector.has_table("hoimsystem_login_lockouts"):
        op.drop_table("hoimsystem_login_lockouts")

    if inspector.has_table("hoimsystem_users"):
        columns = {column["name"] for column in inspector.get_columns("hoimsystem_users")}
        with op.batch_alter_table("hoimsystem_users") as batch_op:
            if "token_invalid_before" in columns:
                batch_op.drop_column("token_invalid_before")
