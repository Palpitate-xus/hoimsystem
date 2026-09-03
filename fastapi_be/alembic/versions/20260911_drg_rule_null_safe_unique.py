"""make DRG rule uniqueness null-safe

Revision ID: 20260911_drg_rule_null_safe_unique
Revises: 20260910_daily_analytics
Create Date: 2026-09-03
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260911_drg_rule_null_safe_unique"
down_revision: str | Sequence[str] | None = "20260910_daily_analytics"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    duplicate = connection.execute(sa.text("""
        SELECT payment_method, group_code, diagnosis_prefix,
               COALESCE(procedure_prefix, '') AS normalized_procedure_prefix,
               version, COUNT(*) AS duplicate_count
        FROM hoimsystem_drg_rule
        GROUP BY payment_method, group_code, diagnosis_prefix,
                 COALESCE(procedure_prefix, ''), version
        HAVING COUNT(*) > 1
        LIMIT 1
    """)).mappings().first()
    if duplicate:
        identity = "/".join(
            str(duplicate[key])
            for key in (
                "payment_method",
                "group_code",
                "diagnosis_prefix",
                "normalized_procedure_prefix",
                "version",
            )
        )
        raise RuntimeError(
            "DRG 规则存在空手术前缀归一化后的重复项；请先合并规则再迁移: "
            f"{identity} ({duplicate['duplicate_count']} rows)"
        )

    connection.execute(
        sa.text("UPDATE hoimsystem_drg_rule SET procedure_prefix = '' WHERE procedure_prefix IS NULL")
    )
    with op.batch_alter_table("hoimsystem_drg_rule") as batch:
        batch.alter_column(
            "procedure_prefix",
            existing_type=sa.String(20),
            nullable=False,
            server_default="",
        )


def downgrade() -> None:
    with op.batch_alter_table("hoimsystem_drg_rule") as batch:
        batch.alter_column(
            "procedure_prefix",
            existing_type=sa.String(20),
            nullable=True,
            server_default=None,
        )
    op.execute("UPDATE hoimsystem_drg_rule SET procedure_prefix = NULL WHERE procedure_prefix = ''")
