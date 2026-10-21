"""Add immutable coding evidence and a current-write serialization gate."""

import sqlalchemy as sa
from sqlalchemy.dialects import mysql

from alembic import op

revision = "20261021_coding_evidence"
down_revision = "20261021_inventory_scenarios"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "hoimsystem_ai_coding_write_gate",
        sa.Column("gate_id", sa.Integer(), nullable=False, primary_key=True, autoincrement=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.CheckConstraint("gate_id=1 AND revision>0", name="ck_coding_gate_singleton"),
    )
    op.create_table(
        "hoimsystem_ai_coding_rule_package",
        sa.Column("package_id", sa.String(36), nullable=False, primary_key=True),
        sa.Column("package_kind", sa.String(32), nullable=False),
        sa.Column("schema_version", sa.String(48), nullable=False),
        sa.Column("created_at", sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("hoimsystem_users.user_id"), nullable=False),
        sa.Column("snapshot_json", sa.Text().with_variant(mysql.MEDIUMTEXT(), "mysql"), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("collection_digest", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("reviewed_at", sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=True),
        sa.Column("reviewed_by", sa.Integer(), sa.ForeignKey("hoimsystem_users.user_id"), nullable=True),
        sa.Column("review_basis_note", sa.Text(), nullable=False),
        sa.Column("revoked_at", sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=True),
        sa.Column("revoked_by", sa.Integer(), sa.ForeignKey("hoimsystem_users.user_id"), nullable=True),
        sa.Column("revoke_reason", sa.String(1000), nullable=False),
        sa.CheckConstraint("package_kind='local_prefix_snapshot'", name="ck_coding_package_kind"),
        sa.CheckConstraint(
            "(status='draft' AND revision=1 AND reviewed_at IS NULL AND reviewed_by IS NULL AND review_basis_note='' AND revoked_at IS NULL AND revoked_by IS NULL AND revoke_reason='') OR (status IN ('published','rejected') AND revision=2 AND reviewed_at IS NOT NULL AND reviewed_by IS NOT NULL AND review_basis_note<>'' AND revoked_at IS NULL AND revoked_by IS NULL AND revoke_reason='') OR (status='revoked' AND revoked_at IS NOT NULL AND revoked_by IS NOT NULL AND revoke_reason<>'' AND ((revision=2 AND reviewed_at IS NULL AND reviewed_by IS NULL AND review_basis_note='') OR (revision=3 AND reviewed_at IS NOT NULL AND reviewed_by IS NOT NULL AND review_basis_note<>'')))",
            name="ck_coding_package_governance",
        ),
        sa.CheckConstraint(
            "(reviewed_at IS NULL OR reviewed_at>=created_at) AND (revoked_at IS NULL OR revoked_at>=created_at) AND (reviewed_at IS NULL OR revoked_at IS NULL OR revoked_at>=reviewed_at)",
            name="ck_coding_package_clocks",
        ),
        sa.CheckConstraint("length(snapshot_json)>0 AND length(snapshot_json)<=8388608 AND length(review_basis_note)<=4000", name="ck_coding_package_bounds"),
    )
    op.create_index("idx_coding_package_created", "hoimsystem_ai_coding_rule_package", ["created_at", "package_id"], unique=False)
    op.create_table(
        "hoimsystem_ai_coding_case_snapshot",
        sa.Column("case_snapshot_id", sa.String(36), nullable=False, primary_key=True),
        sa.Column("home_id", sa.String(36), sa.ForeignKey("hoimsystem_medical_record_home.home_id"), nullable=False),
        sa.Column("admission_id", sa.String(36), sa.ForeignKey("hoimsystem_admission.admission_id"), nullable=False),
        sa.Column("patient_id", sa.Integer(), sa.ForeignKey("hoimsystem_patient.patient_id"), nullable=False),
        sa.Column("rule_package_id", sa.String(36), sa.ForeignKey("hoimsystem_ai_coding_rule_package.package_id"), nullable=True),
        sa.Column("schema_version", sa.String(48), nullable=False),
        sa.Column("created_at", sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("hoimsystem_users.user_id"), nullable=False),
        sa.Column("snapshot_json", sa.Text().with_variant(mysql.MEDIUMTEXT(), "mysql"), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("collection_digest", sa.String(64), nullable=False),
        sa.Column("projection_json", sa.Text().with_variant(mysql.MEDIUMTEXT(), "mysql"), nullable=True),
        sa.Column("projection_hash", sa.String(64), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("reviewed_at", sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=True),
        sa.Column("reviewed_by", sa.Integer(), sa.ForeignKey("hoimsystem_users.user_id"), nullable=True),
        sa.Column("review_basis_note", sa.Text(), nullable=False),
        sa.Column("revoked_at", sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=True),
        sa.Column("revoked_by", sa.Integer(), sa.ForeignKey("hoimsystem_users.user_id"), nullable=True),
        sa.Column("revoke_reason", sa.String(1000), nullable=False),
        sa.CheckConstraint(
            "(status='draft' AND revision=1 AND reviewed_at IS NULL AND reviewed_by IS NULL AND review_basis_note='' AND revoked_at IS NULL AND revoked_by IS NULL AND revoke_reason='') OR (status IN ('published','rejected') AND revision=2 AND reviewed_at IS NOT NULL AND reviewed_by IS NOT NULL AND review_basis_note<>'' AND revoked_at IS NULL AND revoked_by IS NULL AND revoke_reason='') OR (status='revoked' AND revoked_at IS NOT NULL AND revoked_by IS NOT NULL AND revoke_reason<>'' AND ((revision=2 AND reviewed_at IS NULL AND reviewed_by IS NULL AND review_basis_note='') OR (revision=3 AND reviewed_at IS NOT NULL AND reviewed_by IS NOT NULL AND review_basis_note<>'')))",
            name="ck_coding_case_governance",
        ),
        sa.CheckConstraint(
            "(reviewed_at IS NULL OR reviewed_at>=created_at) AND (revoked_at IS NULL OR revoked_at>=created_at) AND (reviewed_at IS NULL OR revoked_at IS NULL OR revoked_at>=reviewed_at)",
            name="ck_coding_case_clocks",
        ),
        sa.CheckConstraint(
            "length(snapshot_json)>0 AND length(snapshot_json)<=8388608 AND (projection_json IS NULL OR (length(projection_json)>0 AND length(projection_json)<=8388608)) AND length(review_basis_note)<=4000",
            name="ck_coding_case_bounds",
        ),
        sa.CheckConstraint(
            "(status IN ('draft','rejected') AND projection_json IS NULL AND projection_hash IS NULL) OR (status='published' AND projection_json IS NOT NULL AND projection_hash IS NOT NULL) OR (status='revoked' AND ((reviewed_at IS NULL AND projection_json IS NULL AND projection_hash IS NULL) OR (reviewed_at IS NOT NULL AND projection_json IS NOT NULL AND projection_hash IS NOT NULL)))",
            name="ck_coding_case_projection",
        ),
    )
    op.create_index("idx_coding_case_scope", "hoimsystem_ai_coding_case_snapshot", ["patient_id", "admission_id", "home_id", "created_at"], unique=False)
    op.create_table(
        "hoimsystem_ai_coding_run_result",
        sa.Column("run_id", sa.String(36), sa.ForeignKey("hoimsystem_ai_run.run_id"), nullable=False, primary_key=True),
        sa.Column("case_snapshot_id", sa.String(36), sa.ForeignKey("hoimsystem_ai_coding_case_snapshot.case_snapshot_id"), nullable=False),
        sa.Column("lease_token", sa.String(36), nullable=False),
        sa.Column("schema_version", sa.String(48), nullable=False),
        sa.Column("source_binding_hash", sa.String(64), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("result_json", sa.Text().with_variant(mysql.MEDIUMTEXT(), "mysql"), nullable=False),
        sa.Column("result_bytes", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=False),
        sa.CheckConstraint("result_bytes>0 AND result_bytes<=8388608 AND length(result_json)>0 AND length(result_json)<=8388608", name="ck_coding_result_bounds"),
    )
    op.create_index("idx_coding_result_case", "hoimsystem_ai_coding_run_result", ["case_snapshot_id", "created_at"], unique=False)
    op.execute(sa.text("INSERT INTO hoimsystem_ai_coding_write_gate(gate_id,revision) VALUES(1,1)"))


def downgrade():
    op.drop_table("hoimsystem_ai_coding_run_result")
    op.drop_table("hoimsystem_ai_coding_case_snapshot")
    op.drop_table("hoimsystem_ai_coding_rule_package")
    op.drop_table("hoimsystem_ai_coding_write_gate")
