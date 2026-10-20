"""Record explicit physician assertions without changing signed or historical diagnosis text."""

import sqlalchemy as sa

from alembic import op

revision = "20261020_diagnosis_review"
down_revision = "20261020_lab_observations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "hoimsystem_clinical_diagnosis_review",
        sa.Column("review_id", sa.String(36), primary_key=True),
        sa.Column("source_kind", sa.String(24), nullable=False),
        sa.Column("source_id", sa.String(36), nullable=False),
        sa.Column("patient_id", sa.Integer(), sa.ForeignKey("hoimsystem_patient.patient_id"), nullable=False),
        sa.Column("encounter_ref", sa.String(36), nullable=True),
        sa.Column("diagnosis_text", sa.String(300), nullable=False),
        sa.Column("source_hash", sa.String(64), nullable=False),
        sa.Column("certainty", sa.String(24), nullable=False),
        sa.Column("reason", sa.String(1000), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("reviewed_by", sa.Integer(), sa.ForeignKey("hoimsystem_users.user_id"), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("source_kind", "source_id", "revision", name="uq_diagnosis_review_source_revision"),
    )
    op.create_index("idx_diagnosis_review_patient_encounter", "hoimsystem_clinical_diagnosis_review", ["patient_id", "encounter_ref"])


def downgrade() -> None:
    op.drop_table("hoimsystem_clinical_diagnosis_review")
