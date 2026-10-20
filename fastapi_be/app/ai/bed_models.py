"""Governed original physical bed observations, separate from live ward state."""

from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects import mysql

from app.database import Base

FACT_BYTES = 262144
PARENT_BYTES = 32768
REVIEW_BYTES = 4000


def utc6():
    return DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql")


def complete_json():
    return Text().with_variant(mysql.MEDIUMTEXT(), "mysql")


class AIBedSource(Base):
    """Immutable submitted fact with independent administrative review and CAS."""

    __tablename__ = "hoimsystem_ai_bed_source"
    __table_args__ = (
        CheckConstraint("source_kind IN ('census','flow_day','capacity_interval')", name="ck_ai_bed_source_kind"),
        CheckConstraint(
            "(status = 'draft' AND revision = 1 AND reviewed_at IS NULL AND reviewed_by IS NULL AND review_basis_note = '' "
            "AND revoked_at IS NULL AND revoked_by IS NULL AND revoke_reason = '') OR "
            "(status IN ('published','rejected') AND revision = 2 AND reviewed_at IS NOT NULL AND reviewed_by IS NOT NULL AND review_basis_note <> '' "
            "AND revoked_at IS NULL AND revoked_by IS NULL AND revoke_reason = '') OR "
            "(status = 'revoked' AND revoked_at IS NOT NULL AND revoked_by IS NOT NULL AND revoke_reason <> '' AND "
            "((revision = 2 AND reviewed_at IS NULL AND reviewed_by IS NULL AND review_basis_note = '') OR "
            "(revision = 3 AND reviewed_at IS NOT NULL AND reviewed_by IS NOT NULL AND review_basis_note <> '')))",
            name="ck_ai_bed_source_governance",
        ),
        CheckConstraint(
            "(reviewed_at IS NULL OR reviewed_at >= recorded_at) AND (revoked_at IS NULL OR revoked_at >= recorded_at) AND (reviewed_at IS NULL OR revoked_at IS NULL OR revoked_at >= reviewed_at)",
            name="ck_ai_bed_source_clocks",
        ),
        CheckConstraint(
            f"length(payload_json) > 0 AND length(payload_json) <= {FACT_BYTES} AND length(parent_binding_json) > 0 AND length(parent_binding_json) <= {PARENT_BYTES} AND length(review_basis_note) <= {REVIEW_BYTES}",
            name="ck_ai_bed_source_bounds",
        ),
        Index("idx_ai_bed_source_scope", "department_id", "ward_id", "source_kind", "recorded_at"),
        Index("idx_ai_bed_source_ward_status", "ward_id", "source_kind", "status"),
    )

    source_record_id = Column(String(36), primary_key=True)
    source_kind = Column(String(32), nullable=False)
    department_id = Column(Integer, ForeignKey("hoimsystem_department.department_id"), nullable=False)
    ward_id = Column(Integer, ForeignKey("hoimsystem_ward.ward_id"), nullable=False)
    schema_version = Column(String(40), nullable=False, default="bed_source_private_v1")
    payload_json = Column(complete_json(), nullable=False)
    parent_binding_json = Column(complete_json(), nullable=False)
    content_hash = Column(String(64), nullable=False)
    recorded_at = Column(utc6(), nullable=False)
    created_by = Column(Integer, ForeignKey("hoimsystem_users.user_id"), nullable=False)
    status = Column(String(16), nullable=False, default="draft")
    revision = Column(Integer, nullable=False, default=1)
    reviewed_by = Column(Integer, ForeignKey("hoimsystem_users.user_id"), nullable=True)
    reviewed_at = Column(utc6(), nullable=True)
    review_basis_note = Column(Text, nullable=False, default="")
    revoked_by = Column(Integer, ForeignKey("hoimsystem_users.user_id"), nullable=True)
    revoked_at = Column(utc6(), nullable=True)
    revoke_reason = Column(String(1000), nullable=False, default="")
