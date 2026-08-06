"""add insurance and DRG records"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260806_insurance"
down_revision: str | Sequence[str] | None = "20260806_blood"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    if not sa.inspect(bind).has_table("hoimsystem_insurance_catalog"):
        op.create_table("hoimsystem_insurance_catalog", sa.Column("catalog_id", sa.Integer(), primary_key=True, autoincrement=True), sa.Column("code", sa.String(40), nullable=False, unique=True), sa.Column("name", sa.String(100), nullable=False), sa.Column("category", sa.String(50)), sa.Column("reimbursement_ratio", sa.Float(), nullable=False, server_default="0"), sa.Column("status", sa.Integer(), nullable=False, server_default="1"), sa.Column("update_time", sa.DateTime(), nullable=False))
    if not sa.inspect(bind).has_table("hoimsystem_insurance_settlement"):
        op.create_table("hoimsystem_insurance_settlement", sa.Column("settlement_id", sa.String(36), primary_key=True), sa.Column("patient_id", sa.Integer(), sa.ForeignKey("hoimsystem_patient.patient_id"), nullable=False), sa.Column("insurance_no", sa.String(50), nullable=False), sa.Column("total_amount", sa.Float(), nullable=False), sa.Column("covered_amount", sa.Float(), nullable=False), sa.Column("self_amount", sa.Float(), nullable=False), sa.Column("status", sa.Integer(), nullable=False, server_default="0"), sa.Column("operator_id", sa.Integer(), sa.ForeignKey("hoimsystem_users.user_id"), nullable=False), sa.Column("settlement_time", sa.DateTime(), nullable=False))
    if not sa.inspect(bind).has_table("hoimsystem_chronic_disease_registration"):
        op.create_table("hoimsystem_chronic_disease_registration", sa.Column("registration_id", sa.String(36), primary_key=True), sa.Column("patient_id", sa.Integer(), sa.ForeignKey("hoimsystem_patient.patient_id"), nullable=False), sa.Column("disease_name", sa.String(100), nullable=False), sa.Column("card_no", sa.String(50)), sa.Column("limit_amount", sa.Float()), sa.Column("status", sa.Integer(), nullable=False, server_default="1"), sa.Column("doctor_id", sa.Integer(), sa.ForeignKey("hoimsystem_doctor.doctor_id")), sa.Column("create_time", sa.DateTime(), nullable=False))
    if not sa.inspect(bind).has_table("hoimsystem_drg_grouping"):
        op.create_table("hoimsystem_drg_grouping", sa.Column("grouping_id", sa.String(36), primary_key=True), sa.Column("patient_id", sa.Integer(), sa.ForeignKey("hoimsystem_patient.patient_id"), nullable=False), sa.Column("group_code", sa.String(30), nullable=False), sa.Column("diagnosis", sa.String(300), nullable=False), sa.Column("expected_amount", sa.Float(), nullable=False, server_default="0"), sa.Column("actual_amount", sa.Float(), nullable=False, server_default="0"), sa.Column("profit", sa.Float(), nullable=False, server_default="0"), sa.Column("create_time", sa.DateTime(), nullable=False))


def downgrade() -> None:
    op.drop_table("hoimsystem_drg_grouping")
    op.drop_table("hoimsystem_chronic_disease_registration")
    op.drop_table("hoimsystem_insurance_settlement")
    op.drop_table("hoimsystem_insurance_catalog")
