"""add equipment, maintenance, inspection and consumable trace records"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260806_equipment"
down_revision: str | Sequence[str] | None = "20260806_infection_control"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    if not sa.inspect(bind).has_table("hoimsystem_equipment"):
        op.create_table("hoimsystem_equipment", sa.Column("equipment_id", sa.Integer(), primary_key=True, autoincrement=True), sa.Column("asset_no", sa.String(40), nullable=False, unique=True), sa.Column("name", sa.String(100), nullable=False), sa.Column("category", sa.String(50)), sa.Column("model", sa.String(100)), sa.Column("manufacturer", sa.String(100)), sa.Column("department_id", sa.Integer(), sa.ForeignKey("hoimsystem_department.department_id")), sa.Column("location", sa.String(100)), sa.Column("purchase_date", sa.Date()), sa.Column("expiry_date", sa.Date()), sa.Column("status", sa.Integer(), nullable=False, server_default="0"), sa.Column("responsible_id", sa.Integer(), sa.ForeignKey("hoimsystem_users.user_id")), sa.Column("last_inventory_time", sa.DateTime()), sa.Column("inventory_status", sa.Integer(), nullable=False, server_default="0"), sa.Column("inventory_note", sa.String(300)), sa.Column("create_time", sa.DateTime(), nullable=False))
    if not sa.inspect(bind).has_table("hoimsystem_equipment_maintenance"):
        op.create_table("hoimsystem_equipment_maintenance", sa.Column("maintenance_id", sa.String(36), primary_key=True), sa.Column("equipment_id", sa.Integer(), sa.ForeignKey("hoimsystem_equipment.equipment_id"), nullable=False), sa.Column("maintenance_type", sa.String(50), nullable=False), sa.Column("description", sa.String(500), nullable=False), sa.Column("cost", sa.Float(), nullable=False, server_default="0"), sa.Column("status", sa.Integer(), nullable=False, server_default="0"), sa.Column("operator_id", sa.Integer(), sa.ForeignKey("hoimsystem_users.user_id"), nullable=False), sa.Column("report_time", sa.DateTime(), nullable=False), sa.Column("complete_time", sa.DateTime()))
    if not sa.inspect(bind).has_table("hoimsystem_equipment_inspection"):
        op.create_table("hoimsystem_equipment_inspection", sa.Column("inspection_id", sa.Integer(), primary_key=True, autoincrement=True), sa.Column("equipment_id", sa.Integer(), sa.ForeignKey("hoimsystem_equipment.equipment_id"), nullable=False), sa.Column("result", sa.String(300), nullable=False), sa.Column("pass_flag", sa.Integer(), nullable=False, server_default="1"), sa.Column("inspector_id", sa.Integer(), sa.ForeignKey("hoimsystem_users.user_id"), nullable=False), sa.Column("inspection_time", sa.DateTime(), nullable=False), sa.Column("next_date", sa.Date()))
    if not sa.inspect(bind).has_table("hoimsystem_consumable_trace"):
        op.create_table("hoimsystem_consumable_trace", sa.Column("trace_id", sa.String(36), primary_key=True), sa.Column("consumable_id", sa.Integer(), sa.ForeignKey("hoimsystem_consumable.consumable_id"), nullable=False), sa.Column("batch_no", sa.String(50), nullable=False), sa.Column("serial_no", sa.String(80)), sa.Column("action", sa.String(30), nullable=False), sa.Column("quantity", sa.Integer(), nullable=False), sa.Column("patient_id", sa.Integer(), sa.ForeignKey("hoimsystem_patient.patient_id")), sa.Column("operator_id", sa.Integer(), sa.ForeignKey("hoimsystem_users.user_id"), nullable=False), sa.Column("action_time", sa.DateTime(), nullable=False), sa.Column("remark", sa.String(300)))


def downgrade() -> None:
    op.drop_table("hoimsystem_consumable_trace")
    op.drop_table("hoimsystem_equipment_inspection")
    op.drop_table("hoimsystem_equipment_maintenance")
    op.drop_table("hoimsystem_equipment")
