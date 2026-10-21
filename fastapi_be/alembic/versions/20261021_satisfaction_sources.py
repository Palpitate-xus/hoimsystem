"""Add a review write gate and immutable, governed satisfaction evidence cases."""

import sqlalchemy as sa
from sqlalchemy.dialects import mysql

from alembic import op

revision = "20261021_satisfaction_sources"
down_revision = "20261021_coding_evidence"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "hoimsystem_ai_satisfaction_write_gate",
        sa.Column("gate_id", sa.Integer(), nullable=False, primary_key=True, autoincrement=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.CheckConstraint("gate_id=1 AND revision>0", name="ck_satisfaction_gate_singleton"),
    )
    utc = sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql")
    original = sa.Text().with_variant(mysql.MEDIUMTEXT(), "mysql")
    op.create_table(
        "hoimsystem_ai_satisfaction_case",
        sa.Column("case_id", sa.String(36), nullable=False, primary_key=True),
        sa.Column("schema_version", sa.String(48), nullable=False),
        sa.Column("scope_kind", sa.String(32), nullable=False),
        sa.Column("doctor_ids_json", sa.Text(), nullable=False),
        sa.Column("date_from", sa.Date(), nullable=False),
        sa.Column("date_to", sa.Date(), nullable=False),
        sa.Column("created_at", utc, nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("hoimsystem_users.user_id"), nullable=False),
        sa.Column("snapshot_json", original, nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("collection_digest", sa.String(64), nullable=False),
        sa.Column("projection_json", original, nullable=True),
        sa.Column("projection_hash", sa.String(64), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("reviewed_at", utc, nullable=True),
        sa.Column("reviewed_by", sa.Integer(), sa.ForeignKey("hoimsystem_users.user_id"), nullable=True),
        sa.Column("review_basis_note", sa.Text(), nullable=False),
        sa.Column("revoked_at", utc, nullable=True),
        sa.Column("revoked_by", sa.Integer(), sa.ForeignKey("hoimsystem_users.user_id"), nullable=True),
        sa.Column("revoke_reason", sa.String(1000), nullable=False),
        sa.CheckConstraint("scope_kind IN ('hospital_reviews','explicit_doctor_cohort') AND date_to>=date_from", name="ck_satisfaction_case_scope"),
        sa.CheckConstraint("length(doctor_ids_json)>0 AND length(doctor_ids_json)<=4096", name="ck_satisfaction_case_doctors"),
        sa.CheckConstraint(
            "length(snapshot_json)>0 AND length(snapshot_json)<=8388608 AND (projection_json IS NULL OR (length(projection_json)>0 AND length(projection_json)<=8388608)) AND length(review_basis_note)<=4000",
            name="ck_satisfaction_case_bounds",
        ),
        sa.CheckConstraint(
            "(status='draft' AND revision=1 AND reviewed_at IS NULL AND reviewed_by IS NULL AND review_basis_note='' AND revoked_at IS NULL AND revoked_by IS NULL AND revoke_reason='') OR (status IN ('published','rejected') AND revision=2 AND reviewed_at IS NOT NULL AND reviewed_by IS NOT NULL AND review_basis_note<>'' AND revoked_at IS NULL AND revoked_by IS NULL AND revoke_reason='') OR (status='revoked' AND revoked_at IS NOT NULL AND revoked_by IS NOT NULL AND revoke_reason<>'' AND ((revision=2 AND reviewed_at IS NULL AND reviewed_by IS NULL AND review_basis_note='') OR (revision=3 AND reviewed_at IS NOT NULL AND reviewed_by IS NOT NULL AND review_basis_note<>'')))",
            name="ck_satisfaction_case_governance",
        ),
        sa.CheckConstraint(
            "(status IN ('draft','rejected') AND projection_json IS NULL AND projection_hash IS NULL) OR (status='published' AND projection_json IS NOT NULL AND projection_hash IS NOT NULL) OR (status='revoked' AND ((reviewed_at IS NULL AND projection_json IS NULL AND projection_hash IS NULL) OR (reviewed_at IS NOT NULL AND projection_json IS NOT NULL AND projection_hash IS NOT NULL)))",
            name="ck_satisfaction_case_projection",
        ),
        sa.CheckConstraint(
            "(reviewed_at IS NULL OR reviewed_at>=created_at) AND (revoked_at IS NULL OR revoked_at>=created_at) AND (reviewed_at IS NULL OR revoked_at IS NULL OR revoked_at>=reviewed_at)",
            name="ck_satisfaction_case_clocks",
        ),
    )
    op.create_index("idx_satisfaction_case_scope", "hoimsystem_ai_satisfaction_case", ["scope_kind", "date_from", "date_to", "created_at", "case_id"], unique=False)
    op.execute(sa.text("INSERT INTO hoimsystem_ai_satisfaction_write_gate(gate_id,revision) VALUES(1,1)"))


def downgrade():
    op.drop_table("hoimsystem_ai_satisfaction_case")
    op.drop_table("hoimsystem_ai_satisfaction_write_gate")
