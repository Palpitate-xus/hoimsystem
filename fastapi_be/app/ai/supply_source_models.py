"""Additive controlled SKU unit/day originals. Never changes business stock."""

from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, ForeignKeyConstraint, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import declared_attr

from app.database import Base

PAYLOAD_BYTES = 262144
PARENT_BYTES = 262144
REVIEW_BYTES = 4000


def utc6():
    return DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql")


def original_text():
    return Text().with_variant(mysql.MEDIUMTEXT(), "mysql")


def constraints(kind):
    return (
        CheckConstraint("item_kind IN ('pharmaceutical','consumable') AND item_id > 0 AND scope = 'hospital_inventory'", name=f"ck_supply_{kind}_scope"),
        CheckConstraint(
            "(status = 'draft' AND revision = 1 AND reviewed_by IS NULL AND reviewed_at IS NULL AND review_basis_note = '' AND revoked_by IS NULL AND revoked_at IS NULL AND revoke_reason = '') OR "
            "(status IN ('published','rejected') AND revision = 2 AND reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL AND review_basis_note <> '' AND revoked_by IS NULL AND revoked_at IS NULL AND revoke_reason = '') OR "
            "(status = 'revoked' AND revoked_by IS NOT NULL AND revoked_at IS NOT NULL AND revoke_reason <> '' AND ((revision = 2 AND reviewed_by IS NULL AND reviewed_at IS NULL AND review_basis_note = '') OR (revision = 3 AND reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL AND review_basis_note <> '')))",
            name=f"ck_supply_{kind}_governance",
        ),
        CheckConstraint(
            "(reviewed_at IS NULL OR reviewed_at >= recorded_at) AND (revoked_at IS NULL OR revoked_at >= recorded_at) AND (reviewed_at IS NULL OR revoked_at IS NULL OR revoked_at >= reviewed_at)",
            name=f"ck_supply_{kind}_governance_clocks",
        ),
        CheckConstraint(
            f"length(payload_json) > 0 AND length(payload_json) <= {PAYLOAD_BYTES} AND length(parent_binding_json) > 0 AND length(parent_binding_json) <= {PARENT_BYTES} AND length(review_basis_note) <= {REVIEW_BYTES}",
            name=f"ck_supply_{kind}_bounded_originals",
        ),
    )


class GovernedSupplyOriginal:
    item_kind = Column(String(20), nullable=False)
    item_id = Column(Integer, nullable=False)
    scope = Column(String(32), nullable=False, default="hospital_inventory")
    schema_version = Column(String(48), nullable=False)
    recorded_at = Column(utc6(), nullable=False)
    payload_json = Column(original_text(), nullable=False)
    parent_binding_json = Column(original_text(), nullable=False)
    content_hash = Column(String(64), nullable=False)
    status = Column(String(16), nullable=False, default="draft")
    revision = Column(Integer, nullable=False, default=1)
    reviewed_at = Column(utc6(), nullable=True)
    review_basis_note = Column(Text, nullable=False, default="")
    revoked_at = Column(utc6(), nullable=True)
    revoke_reason = Column(String(1000), nullable=False, default="")

    @declared_attr
    def created_by(cls):  # noqa: N805
        return Column(Integer, ForeignKey("hoimsystem_users.user_id"), nullable=False)

    @declared_attr
    def reviewed_by(cls):  # noqa: N805
        return Column(Integer, ForeignKey("hoimsystem_users.user_id"), nullable=True)

    @declared_attr
    def revoked_by(cls):  # noqa: N805
        return Column(Integer, ForeignKey("hoimsystem_users.user_id"), nullable=True)


class AISupplyUnitDefinition(GovernedSupplyOriginal, Base):
    __tablename__ = "hoimsystem_ai_supply_unit_definition"
    __table_args__ = constraints("unit") + (
        UniqueConstraint("unit_definition_id", "item_kind", "item_id", "scope", name="uq_supply_unit_scope"),
        Index("idx_supply_unit_item", "item_kind", "item_id", "recorded_at"),
        Index("idx_supply_unit_author", "created_by", "status"),
    )
    unit_definition_id = Column(String(36), primary_key=True)


class AISupplyDailyQuantity(GovernedSupplyOriginal, Base):
    __tablename__ = "hoimsystem_ai_supply_daily_quantity"
    __table_args__ = constraints("day") + (
        ForeignKeyConstraint(
            ["unit_definition_id", "item_kind", "item_id", "scope"],
            [
                "hoimsystem_ai_supply_unit_definition.unit_definition_id",
                "hoimsystem_ai_supply_unit_definition.item_kind",
                "hoimsystem_ai_supply_unit_definition.item_id",
                "hoimsystem_ai_supply_unit_definition.scope",
            ],
            name="fk_supply_day_unit_scope",
        ),
        CheckConstraint(
            "target IN ('recorded_request_quantity','gross_fulfilled_issue_quantity','confirmed_consumed_quantity') AND day_start_at < day_end_at AND day_end_at <= observed_at AND observed_at <= recorded_at",
            name="ck_supply_day_closed_observation",
        ),
        Index("idx_supply_day_item", "item_kind", "item_id", "business_date", "target", "recorded_at"),
        Index("idx_supply_day_span", "item_kind", "item_id", "day_start_at", "day_end_at"),
        Index("idx_supply_day_author", "created_by", "status"),
        Index("idx_supply_day_unit", "unit_definition_id"),
    )
    source_record_id = Column(String(36), primary_key=True)
    target = Column(String(40), nullable=False)
    business_date = Column(String(10), nullable=False)
    day_start_at = Column(utc6(), nullable=False)
    day_end_at = Column(utc6(), nullable=False)
    observed_at = Column(utc6(), nullable=False)
    unit_definition_id = Column(String(36), nullable=True)


SUPPLY_SOURCE_MODELS = (AISupplyUnitDefinition, AISupplyDailyQuantity)
