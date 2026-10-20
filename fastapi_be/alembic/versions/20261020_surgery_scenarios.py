"""Add complete surgery scenarios and lease-bound optimization results without booking."""

import sqlalchemy as sa
from sqlalchemy.dialects import mysql

from alembic import op

revision = "20261020_surgery_scenarios"
down_revision = "20261020_surgery_sources"
branch_labels = None
depends_on = None


def upgrade():
    clock = sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql")
    original = sa.Text().with_variant(mysql.MEDIUMTEXT(), "mysql")
    op.create_table(
        "hoimsystem_ai_surgery_scenario",
        sa.Column("scenario_id", sa.String(36), primary_key=True),
        sa.Column("department_id", sa.Integer(), sa.ForeignKey("hoimsystem_department.department_id"), nullable=False),
        sa.Column("pool_id", sa.String(36), sa.ForeignKey("hoimsystem_ai_surgery_pool.pool_id"), nullable=False),
        sa.Column("schema_version", sa.String(48), nullable=False),
        sa.Column("as_of", clock, nullable=False),
        sa.Column("created_at", clock, nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("hoimsystem_users.user_id"), nullable=False),
        sa.Column("snapshot_json", original, nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("collection_digest", sa.String(64), nullable=False),
        sa.Column("projection_json", original, nullable=True),
        sa.Column("projection_hash", sa.String(64), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("reviewed_by", sa.Integer(), sa.ForeignKey("hoimsystem_users.user_id"), nullable=True),
        sa.Column("reviewed_at", clock, nullable=True),
        sa.Column("review_basis_note", sa.Text(), nullable=False),
        sa.Column("revoked_by", sa.Integer(), sa.ForeignKey("hoimsystem_users.user_id"), nullable=True),
        sa.Column("revoked_at", clock, nullable=True),
        sa.Column("revoke_reason", sa.String(1000), nullable=False),
        sa.CheckConstraint(
            "(status = 'draft' AND revision = 1 AND reviewed_by IS NULL AND reviewed_at IS NULL AND review_basis_note = '' "
            "AND revoked_by IS NULL AND revoked_at IS NULL AND revoke_reason = '' AND projection_json IS NULL AND projection_hash IS NULL) OR "
            "(status = 'published' AND revision = 2 AND reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL AND review_basis_note <> '' "
            "AND revoked_by IS NULL AND revoked_at IS NULL AND revoke_reason = '' AND projection_json IS NOT NULL AND projection_hash IS NOT NULL) OR "
            "(status = 'rejected' AND revision = 2 AND reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL AND review_basis_note <> '' "
            "AND revoked_by IS NULL AND revoked_at IS NULL AND revoke_reason = '' AND projection_json IS NULL AND projection_hash IS NULL) OR "
            "(status = 'revoked' AND revoked_by IS NOT NULL AND revoked_at IS NOT NULL AND revoke_reason <> '' AND "
            "((revision = 2 AND reviewed_by IS NULL AND reviewed_at IS NULL AND review_basis_note = '' AND projection_json IS NULL AND projection_hash IS NULL) OR "
            "(revision = 3 AND reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL AND review_basis_note <> '' AND projection_json IS NOT NULL AND projection_hash IS NOT NULL)))",
            name="ck_surgery_scenario_governance",
        ),
        sa.CheckConstraint(
            "as_of <= created_at AND (reviewed_at IS NULL OR reviewed_at >= created_at) AND (revoked_at IS NULL OR revoked_at >= created_at) "
            "AND (reviewed_at IS NULL OR revoked_at IS NULL OR revoked_at >= reviewed_at)",
            name="ck_surgery_scenario_clocks",
        ),
        sa.CheckConstraint(
            "length(snapshot_json) > 0 AND length(snapshot_json) <= 8388608 "
            "AND (projection_json IS NULL OR (length(projection_json) > 0 AND length(projection_json) <= 8388608)) AND length(review_basis_note) <= 4000",
            name="ck_surgery_scenario_bounds",
        ),
    )
    op.create_index("idx_surgery_scenario_scope", "hoimsystem_ai_surgery_scenario", ["department_id", "pool_id", "created_at"])
    op.create_index("idx_surgery_scenario_creator", "hoimsystem_ai_surgery_scenario", ["created_by", "status"])
    op.create_table(
        "hoimsystem_ai_surgery_run_result",
        sa.Column("run_id", sa.String(36), sa.ForeignKey("hoimsystem_ai_run.run_id"), primary_key=True),
        sa.Column("scenario_id", sa.String(36), sa.ForeignKey("hoimsystem_ai_surgery_scenario.scenario_id"), nullable=False),
        sa.Column("lease_token", sa.String(36), nullable=False),
        sa.Column("schema_version", sa.String(48), nullable=False),
        sa.Column("source_binding_hash", sa.String(64), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("result_json", original, nullable=False),
        sa.Column("result_bytes", sa.Integer(), nullable=False),
        sa.Column("created_at", clock, nullable=False),
        sa.CheckConstraint("result_bytes > 0 AND result_bytes <= 8388608 AND length(result_json) > 0 AND length(result_json) <= 8388608", name="ck_surgery_result_bounds"),
    )
    op.create_index("idx_surgery_result_scenario", "hoimsystem_ai_surgery_run_result", ["scenario_id", "created_at"])


def downgrade():
    op.drop_table("hoimsystem_ai_surgery_run_result")
    op.drop_table("hoimsystem_ai_surgery_scenario")
