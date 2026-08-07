"""add hospital campus master data and department association"""

from collections.abc import Sequence
import datetime

import sqlalchemy as sa
from alembic import op


revision: str = "20260807_multi_campus"
down_revision: str | Sequence[str] | None = "20260807_query_indexes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    campus_table = "hoimsystem_hospital_campus"
    department_table = "hoimsystem_department"
    if not inspector.has_table(campus_table):
        op.create_table(
            campus_table,
            sa.Column("campus_id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("code", sa.String(length=30), nullable=False),
            sa.Column("name", sa.String(length=50), nullable=False),
            sa.Column("address", sa.String(length=200), nullable=False, server_default=""),
            sa.Column("phone", sa.String(length=20), nullable=False, server_default=""),
            sa.Column("status", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("create_time", sa.DateTime(), nullable=False),
            sa.Column("update_time", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("code", name="uq_hospital_campus_code"),
        )
    inspector = sa.inspect(bind)
    if inspector.has_table(department_table):
        existing = {column["name"] for column in inspector.get_columns(department_table)}
        if "campus_id" not in existing:
            op.add_column(department_table, sa.Column("campus_id", sa.Integer(), nullable=True))
    campus_exists = bind.execute(sa.text(f"SELECT campus_id FROM {campus_table} WHERE code = :code"), {"code": "main"}).first()
    if campus_exists is None:
        now = datetime.datetime.now()
        bind.execute(
            sa.text(
                f"INSERT INTO {campus_table} (code, name, address, phone, status, sort_order, create_time, update_time) "
                "VALUES (:code, :name, :address, :phone, :status, :sort_order, :create_time, :update_time)"
            ),
            {"code": "main", "name": "主院区", "address": "", "phone": "", "status": 1, "sort_order": 0, "create_time": now, "update_time": now},
        )
        campus_exists = bind.execute(sa.text(f"SELECT campus_id FROM {campus_table} WHERE code = :code"), {"code": "main"}).first()
    if campus_exists and inspector.has_table(department_table):
        bind.execute(
            sa.text(f"UPDATE {department_table} SET campus_id = :campus_id WHERE campus_id IS NULL"),
            {"campus_id": campus_exists[0]},
        )
    if inspector.has_table(department_table):
        existing_indexes = {index["name"] for index in inspector.get_indexes(department_table)}
        if "idx_department_campus" not in existing_indexes:
            op.create_index("idx_department_campus", department_table, ["campus_id"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("hoimsystem_department"):
        existing_indexes = {index["name"] for index in inspector.get_indexes("hoimsystem_department")}
        if "idx_department_campus" in existing_indexes:
            op.drop_index("idx_department_campus", table_name="hoimsystem_department")
        existing_columns = {column["name"] for column in inspector.get_columns("hoimsystem_department")}
        if "campus_id" in existing_columns:
            op.drop_column("hoimsystem_department", "campus_id")
    if inspector.has_table("hoimsystem_hospital_campus"):
        op.drop_table("hoimsystem_hospital_campus")
