"""store the source schedule on registrations"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260812_registration_schedule"
down_revision: str | Sequence[str] | None = "20260811_payment_failure_reason"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("hoimsystem_registration"):
        return
    columns = {column["name"] for column in inspector.get_columns("hoimsystem_registration")}
    with op.batch_alter_table("hoimsystem_registration") as batch_op:
        if "schedule_id" not in columns:
            batch_op.add_column(sa.Column("schedule_id", sa.Integer(), nullable=True))
            batch_op.create_foreign_key(
                "fk_registration_schedule_id",
                "hoimsystem_doctor_schedule",
                ["schedule_id"],
                ["schedule_id"],
            )
            batch_op.create_index("ix_hoimsystem_registration_schedule_id", ["schedule_id"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("hoimsystem_registration"):
        return
    columns = {column["name"] for column in inspector.get_columns("hoimsystem_registration")}
    indexes = {index["name"] for index in inspector.get_indexes("hoimsystem_registration")}
    with op.batch_alter_table("hoimsystem_registration") as batch_op:
        if "fk_registration_schedule_id" in {foreign_key["name"] for foreign_key in inspector.get_foreign_keys("hoimsystem_registration")}:
            batch_op.drop_constraint("fk_registration_schedule_id", type_="foreignkey")
        if "ix_hoimsystem_registration_schedule_id" in indexes:
            batch_op.drop_index("ix_hoimsystem_registration_schedule_id")
        if "schedule_id" in columns:
            batch_op.drop_column("schedule_id")
