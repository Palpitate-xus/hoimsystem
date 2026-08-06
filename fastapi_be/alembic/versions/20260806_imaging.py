"""add imaging orders, reports and templates"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260806_imaging"
down_revision: str | Sequence[str] | None = "20260806_referral_mdt_approval"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("hoimsystem_imaging_order"):
        op.create_table(
            "hoimsystem_imaging_order",
            sa.Column("imaging_order_id", sa.String(36), primary_key=True),
            sa.Column("patient_id", sa.Integer(), sa.ForeignKey("hoimsystem_patient.patient_id"), nullable=False),
            sa.Column("doctor_id", sa.Integer(), sa.ForeignKey("hoimsystem_doctor.doctor_id"), nullable=False),
            sa.Column("modality", sa.String(30), nullable=False),
            sa.Column("body_part", sa.String(100), nullable=False),
            sa.Column("clinical_diagnosis", sa.String(300)),
            sa.Column("priority", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("status", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("accession_no", sa.String(40), unique=True),
            sa.Column("viewer_url", sa.String(500)),
            sa.Column("create_time", sa.DateTime(), nullable=False),
            sa.Column("schedule_time", sa.DateTime()),
        )
    if not inspector.has_table("hoimsystem_imaging_template"):
        op.create_table(
            "hoimsystem_imaging_template",
            sa.Column("template_id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("name", sa.String(100), nullable=False),
            sa.Column("modality", sa.String(30), nullable=False),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("creator_id", sa.Integer(), sa.ForeignKey("hoimsystem_users.user_id"), nullable=False),
            sa.Column("status", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("create_time", sa.DateTime(), nullable=False),
            sa.Column("update_time", sa.DateTime(), nullable=False),
        )
    if not inspector.has_table("hoimsystem_imaging_report"):
        op.create_table(
            "hoimsystem_imaging_report",
            sa.Column("report_id", sa.String(36), primary_key=True),
            sa.Column("imaging_order_id", sa.String(36), sa.ForeignKey("hoimsystem_imaging_order.imaging_order_id"), nullable=False, unique=True),
            sa.Column("template_id", sa.Integer(), sa.ForeignKey("hoimsystem_imaging_template.template_id")),
            sa.Column("findings", sa.Text(), nullable=False),
            sa.Column("impression", sa.Text(), nullable=False),
            sa.Column("author_id", sa.Integer(), sa.ForeignKey("hoimsystem_users.user_id"), nullable=False),
            sa.Column("reviewer_id", sa.Integer(), sa.ForeignKey("hoimsystem_users.user_id")),
            sa.Column("status", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("report_time", sa.DateTime()),
            sa.Column("review_time", sa.DateTime()),
            sa.Column("review_note", sa.String(300)),
        )


def downgrade() -> None:
    op.drop_table("hoimsystem_imaging_report")
    op.drop_table("hoimsystem_imaging_template")
    op.drop_table("hoimsystem_imaging_order")
