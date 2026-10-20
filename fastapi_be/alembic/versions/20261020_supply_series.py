"""Add immutable single-SKU quantity series and complete results; no stock changes."""

import sqlalchemy as sa
from sqlalchemy.dialects import mysql

from alembic import op

revision = "20261020_supply_series"
down_revision = "20261020_supply_sources"
branch_labels = None
depends_on = None


def upgrade():
    clock = sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql")
    original = sa.Text().with_variant(mysql.MEDIUMTEXT(), "mysql")
    op.create_table(
        "hoimsystem_ai_supply_series",
        sa.Column("series_id", sa.String(36), primary_key=True),
        sa.Column("item_kind", sa.String(20), nullable=False),
        sa.Column("item_id", sa.Integer(), nullable=False),
        sa.Column("scope", sa.String(32), nullable=False),
        sa.Column("unit_definition_id", sa.String(36), nullable=False),
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
        sa.CheckConstraint("item_kind IN ('pharmaceutical','consumable') AND item_id > 0 AND scope = 'hospital_inventory'", name="ck_ai_supply_series_scope"),
        sa.ForeignKeyConstraint(
            ["unit_definition_id", "item_kind", "item_id", "scope"],
            [
                "hoimsystem_ai_supply_unit_definition.unit_definition_id",
                "hoimsystem_ai_supply_unit_definition.item_kind",
                "hoimsystem_ai_supply_unit_definition.item_id",
                "hoimsystem_ai_supply_unit_definition.scope",
            ],
            name="fk_supply_series_unit_scope",
        ),
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
            name="ck_ai_supply_series_governance",
        ),
        sa.CheckConstraint(
            "as_of <= created_at AND (reviewed_at IS NULL OR reviewed_at >= created_at) AND (revoked_at IS NULL OR revoked_at >= created_at) "
            "AND (reviewed_at IS NULL OR revoked_at IS NULL OR revoked_at >= reviewed_at)",
            name="ck_ai_supply_series_clocks",
        ),
        sa.CheckConstraint(
            "length(snapshot_json) > 0 AND length(snapshot_json) <= 8388608 "
            "AND (projection_json IS NULL OR (length(projection_json) > 0 AND length(projection_json) <= 8388608)) AND length(review_basis_note) <= 4000",
            name="ck_ai_supply_series_bounds",
        ),
    )
    op.create_index("idx_ai_supply_series_scope", "hoimsystem_ai_supply_series", ["item_kind", "item_id", "created_at"])
    op.create_index("idx_ai_supply_series_creator", "hoimsystem_ai_supply_series", ["created_by", "status"])
    op.create_table(
        "hoimsystem_ai_supply_run_result",
        sa.Column("run_id", sa.String(36), sa.ForeignKey("hoimsystem_ai_run.run_id"), primary_key=True),
        sa.Column("series_id", sa.String(36), sa.ForeignKey("hoimsystem_ai_supply_series.series_id"), nullable=False),
        sa.Column("lease_token", sa.String(36), nullable=False),
        sa.Column("schema_version", sa.String(48), nullable=False),
        sa.Column("source_binding_hash", sa.String(64), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("result_json", original, nullable=False),
        sa.Column("result_bytes", sa.Integer(), nullable=False),
        sa.Column("created_at", clock, nullable=False),
        sa.CheckConstraint("result_bytes > 0 AND result_bytes <= 8388608 AND length(result_json) > 0 AND length(result_json) <= 8388608", name="ck_ai_supply_result_bounds"),
    )
    op.create_index("idx_ai_supply_result_series", "hoimsystem_ai_supply_run_result", ["series_id", "created_at"])


def downgrade():
    op.drop_table("hoimsystem_ai_supply_run_result")
    op.drop_table("hoimsystem_ai_supply_series")
