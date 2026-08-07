"""persist critical laboratory value acknowledgement workflow"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260814_lab_critical_closure"
down_revision: str | Sequence[str] | None = "20260813_appointment_schedule"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("hoimsystem_lab_result"):
        return
    columns = {column["name"] for column in inspector.get_columns("hoimsystem_lab_result")}
    with op.batch_alter_table("hoimsystem_lab_result") as batch_op:
        additions = (
            ("critical_status", sa.Column("critical_status", sa.Integer(), nullable=False, server_default="0")),
            ("critical_notified_by", sa.Column("critical_notified_by", sa.Integer(), nullable=True)),
            ("critical_notified_time", sa.Column("critical_notified_time", sa.DateTime(), nullable=True)),
            ("critical_acknowledged_by", sa.Column("critical_acknowledged_by", sa.Integer(), nullable=True)),
            ("critical_acknowledged_time", sa.Column("critical_acknowledged_time", sa.DateTime(), nullable=True)),
            ("critical_handled_by", sa.Column("critical_handled_by", sa.Integer(), nullable=True)),
            ("critical_handled_time", sa.Column("critical_handled_time", sa.DateTime(), nullable=True)),
            ("critical_handling_note", sa.Column("critical_handling_note", sa.String(500), nullable=True)),
        )
        for name, column in additions:
            if name not in columns:
                batch_op.add_column(column)
        foreign_keys = {foreign_key["name"] for foreign_key in inspector.get_foreign_keys("hoimsystem_lab_result")}
        for name, column in additions:
            if name.endswith("_by") and f"fk_lab_result_{name}" not in foreign_keys:
                batch_op.create_foreign_key(
                    f"fk_lab_result_{name}", "hoimsystem_users", [name], ["user_id"]
                )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("hoimsystem_lab_result"):
        return
    columns = {column["name"] for column in inspector.get_columns("hoimsystem_lab_result")}
    foreign_keys = {foreign_key["name"] for foreign_key in inspector.get_foreign_keys("hoimsystem_lab_result")}
    with op.batch_alter_table("hoimsystem_lab_result") as batch_op:
        for name in ("critical_notified_by", "critical_acknowledged_by", "critical_handled_by"):
            constraint = f"fk_lab_result_{name}"
            if constraint in foreign_keys:
                batch_op.drop_constraint(constraint, type_="foreignkey")
        for name in (
            "critical_handling_note", "critical_handled_time", "critical_handled_by",
            "critical_acknowledged_time", "critical_acknowledged_by", "critical_notified_time",
            "critical_notified_by", "critical_status",
        ):
            if name in columns:
                batch_op.drop_column(name)
