"""add ICD-10 diagnosis and operation catalogs"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260806_icd10"
down_revision: str | Sequence[str] | None = "20260806_medical_record_archive"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _create(name: str, id_name: str) -> None:
    bind = op.get_bind()
    if sa.inspect(bind).has_table(name):
        return
    op.create_table(name, sa.Column(id_name, sa.Integer(), primary_key=True, autoincrement=True), sa.Column("code", sa.String(length=20), nullable=False, unique=True), sa.Column("name", sa.String(length=200), nullable=False), sa.Column("category", sa.String(length=100), nullable=True), sa.Column("status", sa.Integer(), nullable=False, server_default="1"), sa.Column("create_time", sa.DateTime(), nullable=False), sa.Column("update_time", sa.DateTime(), nullable=False))


def upgrade() -> None:
    _create("hoimsystem_icd10_diagnosis", "diagnosis_id")
    _create("hoimsystem_icd10_operation", "operation_id")


def downgrade() -> None:
    bind = op.get_bind()
    for name in ("hoimsystem_icd10_operation", "hoimsystem_icd10_diagnosis"):
        if sa.inspect(bind).has_table(name):
            op.drop_table(name)
