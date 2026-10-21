"""Additive inventory-planning originals and a transaction serialization gate."""

from sqlalchemy import CheckConstraint, Column, ForeignKey, ForeignKeyConstraint, Index, Integer, String, Text
from sqlalchemy.dialects import mysql

from app.ai.supply_source_models import utc6
from app.database import Base

PAYLOAD_BYTES = 1048576
PARENT_BYTES = 4194304
SOURCE_BYTES = 8388608
SOURCE_KINDS = ("inventory_observation", "future_quantity_scenario", "purchase_candidate_plan")


def original_text():
    return Text().with_variant(mysql.MEDIUMTEXT(), "mysql")


class AIInventoryWriteGate(Base):
    __tablename__ = "hoimsystem_ai_inventory_write_gate"
    __table_args__ = (CheckConstraint("gate_id = 1 AND revision > 0", name="ck_inventory_gate_singleton"),)

    gate_id = Column(Integer, primary_key=True, autoincrement=False)
    revision = Column(Integer, nullable=False)


class AIInventoryNativeSource(Base):
    __tablename__ = "hoimsystem_ai_inventory_native_source"
    __table_args__ = (
        CheckConstraint("item_kind IN ('pharmaceutical','consumable') AND item_id > 0 AND scope = 'hospital_inventory'", name="ck_inventory_source_scope"),
        CheckConstraint(
            "source_kind IN ('inventory_observation','future_quantity_scenario','purchase_candidate_plan')",
            name="ck_inventory_source_kind",
        ),
        CheckConstraint(
            "(status = 'draft' AND revision = 1 AND reviewed_by IS NULL AND reviewed_at IS NULL AND review_basis_note = '' AND revoked_by IS NULL AND revoked_at IS NULL AND revoke_reason = '') OR "
            "(status IN ('published','rejected') AND revision = 2 AND reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL AND review_basis_note <> '' AND revoked_by IS NULL AND revoked_at IS NULL AND revoke_reason = '') OR "
            "(status = 'revoked' AND revoked_by IS NOT NULL AND revoked_at IS NOT NULL AND revoke_reason <> '' AND ((revision = 2 AND reviewed_by IS NULL AND reviewed_at IS NULL AND review_basis_note = '') OR (revision = 3 AND reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL AND review_basis_note <> '')))",
            name="ck_inventory_source_governance",
        ),
        CheckConstraint(
            "(reviewed_at IS NULL OR reviewed_at >= recorded_at) AND (revoked_at IS NULL OR revoked_at >= recorded_at) AND (reviewed_at IS NULL OR revoked_at IS NULL OR revoked_at >= reviewed_at)",
            name="ck_inventory_source_clocks",
        ),
        CheckConstraint(
            f"length(payload_json) > 0 AND length(payload_json) <= {PAYLOAD_BYTES} AND length(parent_binding_json) > 0 AND length(parent_binding_json) <= {PARENT_BYTES} AND length(review_basis_note) <= 4000",
            name="ck_inventory_source_bounds",
        ),
        ForeignKeyConstraint(
            ["unit_definition_id", "item_kind", "item_id", "scope"],
            [
                "hoimsystem_ai_supply_unit_definition.unit_definition_id",
                "hoimsystem_ai_supply_unit_definition.item_kind",
                "hoimsystem_ai_supply_unit_definition.item_id",
                "hoimsystem_ai_supply_unit_definition.scope",
            ],
            name="fk_inventory_source_unit_scope",
        ),
        Index("idx_inventory_source_scope", "item_kind", "item_id", "recorded_at", "source_record_id"),
        Index("idx_inventory_source_kind", "item_kind", "item_id", "source_kind", "recorded_at"),
        Index("idx_inventory_source_author", "created_by", "status"),
    )

    source_record_id = Column(String(36), primary_key=True)
    source_kind = Column(String(32), nullable=False)
    item_kind = Column(String(20), nullable=False)
    item_id = Column(Integer, nullable=False)
    scope = Column(String(32), nullable=False)
    unit_definition_id = Column(String(36), nullable=True)
    schema_version = Column(String(48), nullable=False)
    recorded_at = Column(utc6(), nullable=False)
    created_by = Column(Integer, ForeignKey("hoimsystem_users.user_id"), nullable=False)
    payload_json = Column(original_text(), nullable=False)
    parent_binding_json = Column(original_text(), nullable=False)
    content_hash = Column(String(64), nullable=False)
    status = Column(String(16), nullable=False)
    revision = Column(Integer, nullable=False)
    reviewed_by = Column(Integer, ForeignKey("hoimsystem_users.user_id"), nullable=True)
    reviewed_at = Column(utc6(), nullable=True)
    review_basis_note = Column(Text, nullable=False)
    revoked_by = Column(Integer, ForeignKey("hoimsystem_users.user_id"), nullable=True)
    revoked_at = Column(utc6(), nullable=True)
    revoke_reason = Column(String(1000), nullable=False)
