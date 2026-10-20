"""Add controlled SKU units and original daily quantities; no inventory writes."""

import sqlalchemy as sa
from sqlalchemy.dialects import mysql

from alembic import op

revision = "20261020_supply_sources"
down_revision = "20261020_surgery_scenarios"
branch_labels = None
depends_on = None


def common():
    clock = sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql")
    original = sa.Text().with_variant(mysql.MEDIUMTEXT(), "mysql")
    return [
        sa.Column("item_kind", sa.String(20), nullable=False),
        sa.Column("item_id", sa.Integer(), nullable=False),
        sa.Column("scope", sa.String(32), nullable=False),
        sa.Column("schema_version", sa.String(48), nullable=False),
        sa.Column("recorded_at", clock, nullable=False),
        sa.Column("payload_json", original, nullable=False),
        sa.Column("parent_binding_json", original, nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("reviewed_at", clock, nullable=True),
        sa.Column("review_basis_note", sa.Text(), nullable=False),
        sa.Column("revoked_at", clock, nullable=True),
        sa.Column("revoke_reason", sa.String(1000), nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("hoimsystem_users.user_id"), nullable=False),
        sa.Column("reviewed_by", sa.Integer(), sa.ForeignKey("hoimsystem_users.user_id"), nullable=True),
        sa.Column("revoked_by", sa.Integer(), sa.ForeignKey("hoimsystem_users.user_id"), nullable=True),
    ]


def checks(kind):
    return [
        sa.CheckConstraint("item_kind IN ('pharmaceutical','consumable') AND item_id > 0 AND scope = 'hospital_inventory'", name=f"ck_supply_{kind}_scope"),
        sa.CheckConstraint(
            "(status = 'draft' AND revision = 1 AND reviewed_by IS NULL AND reviewed_at IS NULL AND review_basis_note = '' AND revoked_by IS NULL AND revoked_at IS NULL AND revoke_reason = '') OR "
            "(status IN ('published','rejected') AND revision = 2 AND reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL AND review_basis_note <> '' AND revoked_by IS NULL AND revoked_at IS NULL AND revoke_reason = '') OR "
            "(status = 'revoked' AND revoked_by IS NOT NULL AND revoked_at IS NOT NULL AND revoke_reason <> '' AND ((revision = 2 AND reviewed_by IS NULL AND reviewed_at IS NULL AND review_basis_note = '') OR (revision = 3 AND reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL AND review_basis_note <> '')))",
            name=f"ck_supply_{kind}_governance",
        ),
        sa.CheckConstraint(
            "(reviewed_at IS NULL OR reviewed_at >= recorded_at) AND (revoked_at IS NULL OR revoked_at >= recorded_at) AND (reviewed_at IS NULL OR revoked_at IS NULL OR revoked_at >= reviewed_at)",
            name=f"ck_supply_{kind}_governance_clocks",
        ),
        sa.CheckConstraint(
            "length(payload_json) > 0 AND length(payload_json) <= 262144 AND length(parent_binding_json) > 0 AND length(parent_binding_json) <= 262144 AND length(review_basis_note) <= 4000",
            name=f"ck_supply_{kind}_bounded_originals",
        ),
    ]


def upgrade():
    op.create_table(
        "hoimsystem_ai_supply_unit_definition",
        sa.Column("unit_definition_id", sa.String(36), primary_key=True),
        *common(),
        *checks("unit"),
        sa.UniqueConstraint("unit_definition_id", "item_kind", "item_id", "scope", name="uq_supply_unit_scope"),
    )
    op.create_index("idx_supply_unit_item", "hoimsystem_ai_supply_unit_definition", ["item_kind", "item_id", "recorded_at"])
    op.create_index("idx_supply_unit_author", "hoimsystem_ai_supply_unit_definition", ["created_by", "status"])
    clock = sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql")
    op.create_table(
        "hoimsystem_ai_supply_daily_quantity",
        sa.Column("source_record_id", sa.String(36), primary_key=True),
        sa.Column("target", sa.String(40), nullable=False),
        sa.Column("business_date", sa.String(10), nullable=False),
        sa.Column("day_start_at", clock, nullable=False),
        sa.Column("day_end_at", clock, nullable=False),
        sa.Column("observed_at", clock, nullable=False),
        sa.Column("unit_definition_id", sa.String(36), nullable=True),
        *common(),
        *checks("day"),
        sa.CheckConstraint(
            "target IN ('recorded_request_quantity','gross_fulfilled_issue_quantity','confirmed_consumed_quantity') AND day_start_at < day_end_at AND day_end_at <= observed_at AND observed_at <= recorded_at",
            name="ck_supply_day_closed_observation",
        ),
        sa.ForeignKeyConstraint(
            ["unit_definition_id", "item_kind", "item_id", "scope"],
            [
                "hoimsystem_ai_supply_unit_definition.unit_definition_id",
                "hoimsystem_ai_supply_unit_definition.item_kind",
                "hoimsystem_ai_supply_unit_definition.item_id",
                "hoimsystem_ai_supply_unit_definition.scope",
            ],
            name="fk_supply_day_unit_scope",
        ),
    )
    op.create_index("idx_supply_day_item", "hoimsystem_ai_supply_daily_quantity", ["item_kind", "item_id", "business_date", "target", "recorded_at"])
    op.create_index("idx_supply_day_span", "hoimsystem_ai_supply_daily_quantity", ["item_kind", "item_id", "day_start_at", "day_end_at"])
    op.create_index("idx_supply_day_author", "hoimsystem_ai_supply_daily_quantity", ["created_by", "status"])
    op.create_index("idx_supply_day_unit", "hoimsystem_ai_supply_daily_quantity", ["unit_definition_id"])


def downgrade():
    op.drop_table("hoimsystem_ai_supply_daily_quantity")
    op.drop_table("hoimsystem_ai_supply_unit_definition")
