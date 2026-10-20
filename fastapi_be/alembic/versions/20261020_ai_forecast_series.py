"""Add immutable, explicitly attested daily registration forecast sources."""

import sqlalchemy as sa
from sqlalchemy.dialects import mysql

from alembic import op

revision = "20261020_ai_forecast_series"
down_revision = "20261020_ai_nursing_sources"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "hoimsystem_ai_forecast_series",
        sa.Column("series_id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("target", sa.String(48), nullable=False),
        sa.Column("scope", sa.String(24), nullable=False),
        sa.Column("department_id", sa.Integer(), sa.ForeignKey("hoimsystem_department.department_id")),
        sa.Column("date_from", sa.Date(), nullable=False),
        sa.Column("date_to", sa.Date(), nullable=False),
        sa.Column("timezone", sa.String(100), nullable=False),
        sa.Column("time_basis", sa.String(40), nullable=False),
        sa.Column("source_json", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("registration_digest", sa.String(64), nullable=False),
        sa.Column("coverage_note", sa.String(2000), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("hoimsystem_users.user_id"), nullable=False),
        sa.Column("create_time", sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=False),
        sa.Column("revoked_by", sa.Integer(), sa.ForeignKey("hoimsystem_users.user_id")),
        sa.Column("revoked_at", sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql")),
        sa.Column("revoke_reason", sa.String(1000), nullable=False),
    )
    op.create_index("idx_ai_forecast_scope_status", "hoimsystem_ai_forecast_series", ["scope", "department_id", "status"])
    op.create_index("idx_ai_forecast_created", "hoimsystem_ai_forecast_series", ["create_time"])


def downgrade():
    op.drop_table("hoimsystem_ai_forecast_series")
