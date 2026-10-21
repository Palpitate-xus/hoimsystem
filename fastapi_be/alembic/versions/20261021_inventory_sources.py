"""Add immutable stock observations and finite future-plan originals."""

import sqlalchemy as sa
from sqlalchemy.dialects import mysql

from alembic import op

revision = "20261021_inventory_sources"
down_revision = "20261021_inventory_gate"
branch_labels = None
depends_on = None


def upgrade():
    clock = sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql")
    original = sa.Text().with_variant(mysql.MEDIUMTEXT(), "mysql")
    op.create_table(
        "hoimsystem_ai_inventory_native_source",
        sa.Column("source_record_id", sa.String(36), primary_key=True),
        sa.Column("source_kind", sa.String(32), nullable=False),
        sa.Column("item_kind", sa.String(20), nullable=False),
        sa.Column("item_id", sa.Integer(), nullable=False),
        sa.Column("scope", sa.String(32), nullable=False),
        sa.Column("unit_definition_id", sa.String(36), nullable=True),
        sa.Column("date_from", sa.String(10), nullable=True),
        sa.Column("date_to", sa.String(10), nullable=True),
        sa.Column("timezone", sa.String(100), nullable=True),
        sa.Column("schema_version", sa.String(48), nullable=False),
        sa.Column("recorded_at", clock, nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("hoimsystem_users.user_id"), nullable=False),
        sa.Column("payload_json", original, nullable=False),
        sa.Column("parent_binding_json", original, nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("reviewed_by", sa.Integer(), sa.ForeignKey("hoimsystem_users.user_id"), nullable=True),
        sa.Column("reviewed_at", clock, nullable=True),
        sa.Column("review_basis_note", sa.Text(), nullable=False),
        sa.Column("revoked_by", sa.Integer(), sa.ForeignKey("hoimsystem_users.user_id"), nullable=True),
        sa.Column("revoked_at", clock, nullable=True),
        sa.Column("revoke_reason", sa.String(1000), nullable=False),
        sa.CheckConstraint("item_kind IN ('pharmaceutical','consumable') AND item_id > 0 AND scope = 'hospital_inventory'", name="ck_inventory_source_scope"),
        sa.CheckConstraint("source_kind IN ('inventory_observation','future_quantity_scenario','purchase_candidate_plan')", name="ck_inventory_source_kind"),
        sa.CheckConstraint(
            "(source_kind = 'inventory_observation' AND date_from IS NULL AND date_to IS NULL AND timezone IS NULL) OR "
            "(source_kind IN ('future_quantity_scenario','purchase_candidate_plan') AND date_from IS NOT NULL AND date_to IS NOT NULL AND timezone IS NOT NULL AND date_from <= date_to)",
            name="ck_inventory_source_period_header",
        ),
        sa.CheckConstraint(
            "(status = 'draft' AND revision = 1 AND reviewed_by IS NULL AND reviewed_at IS NULL AND review_basis_note = '' AND revoked_by IS NULL AND revoked_at IS NULL AND revoke_reason = '') OR "
            "(status IN ('published','rejected') AND revision = 2 AND reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL AND review_basis_note <> '' AND revoked_by IS NULL AND revoked_at IS NULL AND revoke_reason = '') OR "
            "(status = 'revoked' AND revoked_by IS NOT NULL AND revoked_at IS NOT NULL AND revoke_reason <> '' AND ((revision = 2 AND reviewed_by IS NULL AND reviewed_at IS NULL AND review_basis_note = '') OR (revision = 3 AND reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL AND review_basis_note <> '')))",
            name="ck_inventory_source_governance",
        ),
        sa.CheckConstraint(
            "(reviewed_at IS NULL OR reviewed_at >= recorded_at) AND (revoked_at IS NULL OR revoked_at >= recorded_at) AND (reviewed_at IS NULL OR revoked_at IS NULL OR revoked_at >= reviewed_at)",
            name="ck_inventory_source_clocks",
        ),
        sa.CheckConstraint(
            "length(payload_json) > 0 AND length(payload_json) <= 1048576 AND length(parent_binding_json) > 0 AND length(parent_binding_json) <= 4194304 AND length(review_basis_note) <= 4000",
            name="ck_inventory_source_bounds",
        ),
        sa.ForeignKeyConstraint(
            ["unit_definition_id", "item_kind", "item_id", "scope"],
            [
                "hoimsystem_ai_supply_unit_definition.unit_definition_id",
                "hoimsystem_ai_supply_unit_definition.item_kind",
                "hoimsystem_ai_supply_unit_definition.item_id",
                "hoimsystem_ai_supply_unit_definition.scope",
            ],
            name="fk_inventory_source_unit_scope",
        ),
    )
    op.create_index("idx_inventory_source_scope", "hoimsystem_ai_inventory_native_source", ["item_kind", "item_id", "recorded_at", "source_record_id"])
    op.create_index("idx_inventory_source_kind", "hoimsystem_ai_inventory_native_source", ["item_kind", "item_id", "source_kind", "recorded_at"])
    op.create_index("idx_inventory_source_author", "hoimsystem_ai_inventory_native_source", ["created_by", "status"])


def downgrade():
    op.drop_table("hoimsystem_ai_inventory_native_source")
