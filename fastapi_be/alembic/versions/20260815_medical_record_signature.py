"""add signature state to outpatient medical records"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260815_medical_record_signature"
down_revision: str | Sequence[str] | None = "20260814_lab_critical_closure"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("hoimsystem_medical_record"):
        return
    columns = {column["name"] for column in inspector.get_columns("hoimsystem_medical_record")}
    with op.batch_alter_table("hoimsystem_medical_record") as batch_op:
        if "status" not in columns:
            batch_op.add_column(sa.Column("status", sa.Integer(), nullable=False, server_default="0"))
        if "sign_time" not in columns:
            batch_op.add_column(sa.Column("sign_time", sa.DateTime(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("hoimsystem_medical_record"):
        return
    columns = {column["name"] for column in inspector.get_columns("hoimsystem_medical_record")}
    with op.batch_alter_table("hoimsystem_medical_record") as batch_op:
        if "sign_time" in columns:
            batch_op.drop_column("sign_time")
        if "status" in columns:
            batch_op.drop_column("status")
