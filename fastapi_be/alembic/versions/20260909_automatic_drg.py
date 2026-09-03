"""add versioned automatic DRG and DIP grouping

Revision ID: 20260909_automatic_drg
Revises: 20260908_clinical_decision_support
Create Date: 2026-09-03
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260909_automatic_drg"
down_revision: str | Sequence[str] | None = "20260908_clinical_decision_support"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "hoimsystem_drg_rule",
        sa.Column("rule_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("payment_method", sa.String(10), nullable=False, server_default="DRG"),
        sa.Column("group_code", sa.String(30), nullable=False),
        sa.Column("group_name", sa.String(200), nullable=False),
        sa.Column("diagnosis_prefix", sa.String(20), nullable=False),
        sa.Column("procedure_prefix", sa.String(20)),
        sa.Column("expected_amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("version", sa.String(30), nullable=False),
        sa.Column("effective_from", sa.Date()),
        sa.Column("effective_to", sa.Date()),
        sa.Column("status", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("creator_id", sa.Integer(), sa.ForeignKey("hoimsystem_users.user_id"), nullable=False),
        sa.Column("create_time", sa.DateTime(), nullable=False),
        sa.Column("update_time", sa.DateTime(), nullable=False),
        sa.UniqueConstraint(
            "payment_method",
            "group_code",
            "diagnosis_prefix",
            "procedure_prefix",
            "version",
            name="uq_drg_rule_version",
        ),
    )
    op.create_index("idx_drg_rule_match", "hoimsystem_drg_rule", ["status", "diagnosis_prefix", "priority"])
    with op.batch_alter_table("hoimsystem_drg_grouping") as batch:
        batch.add_column(sa.Column("home_id", sa.String(36), sa.ForeignKey("hoimsystem_medical_record_home.home_id")))
        batch.add_column(sa.Column("rule_id", sa.Integer(), sa.ForeignKey("hoimsystem_drg_rule.rule_id")))
        batch.add_column(sa.Column("payment_method", sa.String(10), nullable=False, server_default="DRG"))
        batch.add_column(sa.Column("diagnosis_codes", sa.String(500)))
        batch.add_column(sa.Column("procedure_codes", sa.String(500)))
        batch.add_column(sa.Column("grouping_method", sa.String(20), nullable=False, server_default="manual"))
    op.create_index("uq_drg_grouping_home", "hoimsystem_drg_grouping", ["home_id"], unique=True)
    op.create_index("idx_drg_grouping_code_time", "hoimsystem_drg_grouping", ["group_code", "create_time"])


def downgrade() -> None:
    op.drop_index("idx_drg_grouping_code_time", table_name="hoimsystem_drg_grouping")
    op.drop_index("uq_drg_grouping_home", table_name="hoimsystem_drg_grouping")
    with op.batch_alter_table("hoimsystem_drg_grouping") as batch:
        batch.drop_column("grouping_method")
        batch.drop_column("procedure_codes")
        batch.drop_column("diagnosis_codes")
        batch.drop_column("payment_method")
        batch.drop_column("rule_id")
        batch.drop_column("home_id")
    op.drop_index("idx_drg_rule_match", table_name="hoimsystem_drg_rule")
    op.drop_table("hoimsystem_drg_rule")
