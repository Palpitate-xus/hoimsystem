"""病案借阅审批流字段 + 科室绩效核算表

Revision ID: 20260822_borrow_perf
Revises: 20260821_his_modules
Create Date: 2026-08-22
"""
import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260822_borrow_perf"
down_revision: str | None = "20260821_his_modules"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 病案借阅审批流字段（逻辑外键由 ORM 维护，避免 SQLite 批重建环依赖）
    with op.batch_alter_table("hoimsystem_medical_record_archive") as batch:
        batch.add_column(sa.Column("borrow_status", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("approver_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("approve_time", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("reject_reason", sa.String(300), nullable=True))

    # 科室绩效核算表
    op.create_table(
        "hoimsystem_department_performance",
        sa.Column("performance_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("period", sa.String(10), nullable=False, index=True),
        sa.Column("department_id", sa.Integer(), sa.ForeignKey("hoimsystem_department.department_id"), nullable=False),
        sa.Column("workload_items", sa.Text()),
        sa.Column("total_workload", sa.Numeric(14, 2), server_default="0"),
        sa.Column("cost_items", sa.Text()),
        sa.Column("total_cost", sa.Numeric(14, 2), server_default="0"),
        sa.Column("coefficient", sa.Numeric(6, 3), server_default="1.000"),
        sa.Column("performance_amount", sa.Numeric(14, 2), server_default="0"),
        sa.Column("status", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("creator_id", sa.Integer(), sa.ForeignKey("hoimsystem_users.user_id")),
        sa.Column("auditor_id", sa.Integer(), sa.ForeignKey("hoimsystem_users.user_id")),
        sa.Column("create_time", sa.DateTime(), nullable=False),
        sa.Column("update_time", sa.DateTime()),
        sa.Column("remark", sa.String(300)),
    )


def downgrade() -> None:
    op.drop_table("hoimsystem_department_performance")
    with op.batch_alter_table("hoimsystem_medical_record_archive") as batch:
        batch.drop_column("reject_reason")
        batch.drop_column("approve_time")
        batch.drop_column("approver_id")
        batch.drop_column("borrow_status")
