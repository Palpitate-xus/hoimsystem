"""New vasoactive mapping and original-source tables; no legacy table edits."""

import uuid

from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects import mysql

from app.database import Base


class AIVasoactiveDrugMapping(Base):
    __tablename__ = "hoimsystem_ai_vasoactive_drug_mapping"
    __table_args__ = (
        Index("uq_vasoactive_mapping_published", "published_key", unique=True),
        Index("idx_vasoactive_mapping_identity", "identity_hash", "status"),
        CheckConstraint("status IN ('draft','published','revoked')", name="ck_vasoactive_mapping_status"),
    )

    mapping_id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    schema_version = Column(String(48), nullable=False)
    source_namespace = Column(String(120), nullable=False)
    pharmaceutical_id = Column(Integer, ForeignKey("hoimsystem_pharmaceutical.pharmaceutical_id"), nullable=False)
    identity_hash = Column(String(64), nullable=False)
    published_key = Column(String(64), nullable=True)
    drug_key = Column(String(32), nullable=False)
    active_moiety_basis = Column(String(16), nullable=False)
    payload_json = Column(Text, nullable=False)
    content_hash = Column(String(64), nullable=False)
    created_by = Column(Integer, ForeignKey("hoimsystem_users.user_id"), nullable=False)
    created_at = Column(DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=False)
    status = Column(String(16), nullable=False, default="draft")
    revision = Column(Integer, nullable=False, default=1)
    published_at = Column(DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=True)
    published_by = Column(Integer, ForeignKey("hoimsystem_users.user_id"), nullable=True)
    review_note = Column(String(2000), nullable=False, default="")
    revoked_at = Column(DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=True)
    revoked_by = Column(Integer, ForeignKey("hoimsystem_users.user_id"), nullable=True)
    revoke_reason = Column(String(1000), nullable=False, default="")


class InpatientVasoactiveSource(Base):
    __tablename__ = "hoimsystem_inpatient_vasoactive_source"
    __table_args__ = (
        CheckConstraint("event_at IS NULL OR event_at <= recorded_at", name="ck_vasoactive_source_time"),
        CheckConstraint(
            "(status = 'active' AND revision = 1 AND revoked_at IS NULL AND revoked_by IS NULL AND revoke_reason = '') OR "
            "(status = 'revoked' AND revision = 2 AND revoked_at IS NOT NULL AND revoked_by IS NOT NULL AND revoke_reason <> '')",
            name="ck_vasoactive_source_governance",
        ),
        Index("idx_vasoactive_source_scope", "patient_id", "admission_id", "event_at"),
        Index("idx_vasoactive_source_recorded", "recorded_at"),
    )

    support_source_id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    patient_id = Column(Integer, ForeignKey("hoimsystem_patient.patient_id"), nullable=False)
    admission_id = Column(String(36), ForeignKey("hoimsystem_admission.admission_id"), nullable=False)
    event_at = Column(DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=True)
    recorded_at = Column(DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=False)
    created_by = Column(Integer, ForeignKey("hoimsystem_users.user_id"), nullable=False)
    schema_version = Column(String(48), nullable=False)
    payload_json = Column(Text, nullable=False)
    reference_snapshot_json = Column(Text().with_variant(mysql.MEDIUMTEXT(), "mysql"), nullable=False)
    author_qualification_json = Column(Text, nullable=False)
    content_hash = Column(String(64), nullable=False)
    status = Column(String(16), nullable=False, default="active")
    revision = Column(Integer, nullable=False, default=1)
    revoked_at = Column(DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=True)
    revoked_by = Column(Integer, ForeignKey("hoimsystem_users.user_id"), nullable=True)
    revoke_reason = Column(String(1000), nullable=False, default="")
