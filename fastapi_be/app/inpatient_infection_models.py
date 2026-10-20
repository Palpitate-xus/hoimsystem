"""Immutable clinician-reviewed infection episode originals, separate from diagnosis."""

from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects import mysql

from app.database import Base


class InpatientInfectionEpisodeSource(Base):
    __tablename__ = "hoimsystem_inpatient_infection_episode_source"
    __table_args__ = (
        CheckConstraint("event_at IS NULL OR event_at <= recorded_at", name="ck_inpatient_infection_episode_time"),
        CheckConstraint(
            "(status = 'active' AND revision = 1 AND revoked_at IS NULL AND revoked_by IS NULL AND revoke_reason = '') OR "
            "(status = 'revoked' AND revision = 2 AND revoked_at IS NOT NULL AND revoked_by IS NOT NULL AND revoke_reason <> '')",
            name="ck_inpatient_infection_episode_governance",
        ),
        Index("idx_inpatient_infection_episode_scope", "patient_id", "admission_id", "event_at"),
        Index("idx_inpatient_infection_episode_recorded", "recorded_at"),
    )

    support_source_id = Column(String(36), primary_key=True)
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
    status = Column(String(16), nullable=False, default="active", server_default="active")
    revision = Column(Integer, nullable=False, default=1, server_default="1")
    revoked_at = Column(DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=True)
    revoked_by = Column(Integer, ForeignKey("hoimsystem_users.user_id"), nullable=True)
    revoke_reason = Column(String(1000), nullable=False, default="", server_default="")
