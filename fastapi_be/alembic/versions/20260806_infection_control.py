"""add infection control records"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260806_infection_control"
down_revision: str | Sequence[str] | None = "20260806_antibiotic_approval"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if not sa.inspect(op.get_bind()).has_table("hoimsystem_infection_case"):
        op.create_table("hoimsystem_infection_case", sa.Column("case_id", sa.String(36), primary_key=True), sa.Column("patient_id", sa.Integer(), sa.ForeignKey("hoimsystem_patient.patient_id"), nullable=False), sa.Column("department_id", sa.Integer(), sa.ForeignKey("hoimsystem_department.department_id")), sa.Column("infection_type", sa.String(100), nullable=False), sa.Column("pathogen", sa.String(100)), sa.Column("onset_date", sa.Date(), nullable=False), sa.Column("severity", sa.Integer(), nullable=False, server_default="1"), sa.Column("status", sa.Integer(), nullable=False, server_default="0"), sa.Column("description", sa.String(500)), sa.Column("reporter_id", sa.Integer(), sa.ForeignKey("hoimsystem_users.user_id"), nullable=False), sa.Column("create_time", sa.DateTime(), nullable=False), sa.Column("update_time", sa.DateTime(), nullable=False))
    if not sa.inspect(op.get_bind()).has_table("hoimsystem_disinfection_monitor"):
        op.create_table("hoimsystem_disinfection_monitor", sa.Column("monitor_id", sa.Integer(), primary_key=True, autoincrement=True), sa.Column("area", sa.String(100), nullable=False), sa.Column("item", sa.String(100), nullable=False), sa.Column("result", sa.String(100), nullable=False), sa.Column("standard", sa.String(100)), sa.Column("pass_flag", sa.Integer(), nullable=False, server_default="1"), sa.Column("remark", sa.String(300)), sa.Column("operator_id", sa.Integer(), sa.ForeignKey("hoimsystem_users.user_id"), nullable=False), sa.Column("monitor_time", sa.DateTime(), nullable=False))
    if not sa.inspect(op.get_bind()).has_table("hoimsystem_occupational_exposure"):
        op.create_table("hoimsystem_occupational_exposure", sa.Column("exposure_id", sa.String(36), primary_key=True), sa.Column("exposure_type", sa.String(100), nullable=False), sa.Column("source_patient_id", sa.Integer(), sa.ForeignKey("hoimsystem_patient.patient_id")), sa.Column("body_site", sa.String(100), nullable=False), sa.Column("description", sa.String(500), nullable=False), sa.Column("action_taken", sa.String(500)), sa.Column("status", sa.Integer(), nullable=False, server_default="0"), sa.Column("reporter_id", sa.Integer(), sa.ForeignKey("hoimsystem_users.user_id"), nullable=False), sa.Column("exposure_time", sa.DateTime(), nullable=False), sa.Column("create_time", sa.DateTime(), nullable=False))


def downgrade() -> None:
    op.drop_table("hoimsystem_occupational_exposure")
    op.drop_table("hoimsystem_disinfection_monitor")
    op.drop_table("hoimsystem_infection_case")
