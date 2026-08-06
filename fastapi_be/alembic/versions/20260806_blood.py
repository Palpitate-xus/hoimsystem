"""add blood bank workflow records"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260806_blood"
down_revision: str | Sequence[str] | None = "20260806_equipment"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    if not sa.inspect(bind).has_table("hoimsystem_blood_request"):
        op.create_table("hoimsystem_blood_request", sa.Column("request_id", sa.String(36), primary_key=True), sa.Column("patient_id", sa.Integer(), sa.ForeignKey("hoimsystem_patient.patient_id"), nullable=False), sa.Column("doctor_id", sa.Integer(), sa.ForeignKey("hoimsystem_doctor.doctor_id")), sa.Column("blood_type", sa.String(20), nullable=False), sa.Column("component", sa.String(50), nullable=False), sa.Column("volume", sa.Integer(), nullable=False), sa.Column("reason", sa.String(300), nullable=False), sa.Column("blood_type_verified", sa.Integer(), nullable=False, server_default="0"), sa.Column("status", sa.Integer(), nullable=False, server_default="0"), sa.Column("applicant_id", sa.Integer(), sa.ForeignKey("hoimsystem_users.user_id"), nullable=False), sa.Column("reviewer_id", sa.Integer(), sa.ForeignKey("hoimsystem_users.user_id")), sa.Column("create_time", sa.DateTime(), nullable=False), sa.Column("review_time", sa.DateTime()))
    if not sa.inspect(bind).has_table("hoimsystem_blood_cross_match"):
        op.create_table("hoimsystem_blood_cross_match", sa.Column("cross_match_id", sa.String(36), primary_key=True), sa.Column("request_id", sa.String(36), sa.ForeignKey("hoimsystem_blood_request.request_id"), nullable=False), sa.Column("donor_blood_type", sa.String(20), nullable=False), sa.Column("result", sa.String(100), nullable=False), sa.Column("pass_flag", sa.Integer(), nullable=False, server_default="0"), sa.Column("operator_id", sa.Integer(), sa.ForeignKey("hoimsystem_users.user_id"), nullable=False), sa.Column("match_time", sa.DateTime(), nullable=False))
    if not sa.inspect(bind).has_table("hoimsystem_blood_issue"):
        op.create_table("hoimsystem_blood_issue", sa.Column("issue_id", sa.String(36), primary_key=True), sa.Column("request_id", sa.String(36), sa.ForeignKey("hoimsystem_blood_request.request_id"), nullable=False), sa.Column("unit_no", sa.String(50), nullable=False), sa.Column("component", sa.String(50), nullable=False), sa.Column("volume", sa.Integer(), nullable=False), sa.Column("issuer_id", sa.Integer(), sa.ForeignKey("hoimsystem_users.user_id"), nullable=False), sa.Column("issue_time", sa.DateTime(), nullable=False))
    if not sa.inspect(bind).has_table("hoimsystem_transfusion_reaction"):
        op.create_table("hoimsystem_transfusion_reaction", sa.Column("reaction_id", sa.String(36), primary_key=True), sa.Column("request_id", sa.String(36), sa.ForeignKey("hoimsystem_blood_request.request_id"), nullable=False), sa.Column("symptoms", sa.String(500), nullable=False), sa.Column("severity", sa.Integer(), nullable=False, server_default="1"), sa.Column("action_taken", sa.String(500), nullable=False), sa.Column("reporter_id", sa.Integer(), sa.ForeignKey("hoimsystem_users.user_id"), nullable=False), sa.Column("report_time", sa.DateTime(), nullable=False), sa.Column("status", sa.Integer(), nullable=False, server_default="0"))


def downgrade() -> None:
    op.drop_table("hoimsystem_transfusion_reaction")
    op.drop_table("hoimsystem_blood_issue")
    op.drop_table("hoimsystem_blood_cross_match")
    op.drop_table("hoimsystem_blood_request")
