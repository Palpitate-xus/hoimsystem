"""Add typed lab observations without interpreting or rewriting historical report text."""

import sqlalchemy as sa

from alembic import op

revision = "20261020_lab_observations"
down_revision = "20261020_rx_instructions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Preserve source coding, methods, units, sample time and report review linkage."""
    op.create_table(
        "hoimsystem_lab_observation",
        sa.Column("observation_id", sa.String(36), primary_key=True),
        sa.Column("lab_result_id", sa.String(36), sa.ForeignKey("hoimsystem_lab_result.lab_result_id"), nullable=False),
        sa.Column("code", sa.String(80), nullable=False),
        sa.Column("code_system", sa.String(80), nullable=False),
        sa.Column("display", sa.String(120), nullable=False),
        sa.Column("value_num", sa.Numeric(24, 8).with_variant(sa.String(32), "sqlite"), nullable=True),
        sa.Column("value_text", sa.String(500), nullable=True),
        sa.Column("unit", sa.String(40), nullable=True),
        sa.Column("reference_low", sa.Numeric(24, 8).with_variant(sa.String(32), "sqlite"), nullable=True),
        sa.Column("reference_high", sa.Numeric(24, 8).with_variant(sa.String(32), "sqlite"), nullable=True),
        sa.Column("reference_text", sa.String(200), nullable=True),
        sa.Column("collected_at", sa.DateTime(), nullable=False),
        sa.Column("method", sa.String(100), nullable=False),
        sa.Column("specimen_type", sa.String(80), nullable=False),
        sa.Column("flag", sa.String(16), nullable=False),
        sa.UniqueConstraint("lab_result_id", "code_system", "code", "collected_at", "method", name="uq_lab_observation_source"),
        sa.CheckConstraint("(value_num IS NULL AND value_text IS NOT NULL) OR (value_num IS NOT NULL AND value_text IS NULL)", name="ck_lab_observation_value"),
        sa.CheckConstraint("value_num IS NULL OR (unit IS NOT NULL AND unit <> '')", name="ck_lab_observation_numeric_unit"),
    )
    op.create_index("ix_hoimsystem_lab_observation_lab_result_id", "hoimsystem_lab_observation", ["lab_result_id"])
    op.create_index("idx_lab_observation_code_time", "hoimsystem_lab_observation", ["code_system", "code", "collected_at"])


def downgrade() -> None:
    """Remove the extension without modifying original laboratory reports."""
    op.drop_table("hoimsystem_lab_observation")
