"""Immutable complete SOFA originals and lease-bound large results.

Only new tables use bounded MEDIUMTEXT. Existing AIRun TEXT remains unchanged;
its new mode stores verified references to these complete objects.
"""

from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects import mysql

from app.database import Base

PRIVATE_BYTES = 8 * 1024 * 1024
DAILY_PROJECTION_BYTES = 2 * 1024 * 1024
CHANGE_PROJECTION_BYTES = 6 * 1024 * 1024
RESULT_BYTES = 8 * 1024 * 1024


def utc6():
    return DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql")


def complete_json():
    return Text().with_variant(mysql.MEDIUMTEXT(), "mysql")


def lifecycle_constraint(name):
    return CheckConstraint(
        "(status = 'active' AND revision = 1 AND revoked_at IS NULL AND revoked_by IS NULL AND revoke_reason = '') OR "
        "(status = 'revoked' AND revision = 2 AND revoked_at IS NOT NULL AND revoked_by IS NOT NULL AND revoke_reason <> '')",
        name=name,
    )


class AISofaAssessment(Base):
    __tablename__ = "hoimsystem_ai_sofa_assessment"
    __table_args__ = (
        lifecycle_constraint("ck_ai_sofa_assessment_governance"),
        CheckConstraint("period_start < period_end AND period_end <= as_of AND as_of <= evaluation_at AND evaluation_at <= created_at", name="ck_ai_sofa_assessment_clocks"),
        CheckConstraint("revoked_at IS NULL OR revoked_at >= created_at", name="ck_ai_sofa_assessment_revocation_clock"),
        CheckConstraint(f"length(snapshot_json) <= {PRIVATE_BYTES} AND length(projection_json) <= {DAILY_PROJECTION_BYTES}", name="ck_ai_sofa_assessment_json_bounds"),
        Index("idx_ai_sofa_assessment_scope", "patient_id", "admission_id", "created_at"),
        Index("idx_ai_sofa_assessment_profile", "rule_profile_id", "status"),
    )

    assessment_id = Column(String(36), primary_key=True)
    patient_id = Column(Integer, ForeignKey("hoimsystem_patient.patient_id"), nullable=False)
    admission_id = Column(String(36), ForeignKey("hoimsystem_admission.admission_id"), nullable=False)
    rule_profile_id = Column(String(36), ForeignKey("hoimsystem_ai_risk_rule_profile.rule_profile_id"), nullable=False)
    rule_profile_content_hash = Column(String(64), nullable=False)
    recipe_digest = Column(String(64), nullable=False)
    policy_digest = Column(String(64), nullable=False)
    manifest_digest = Column(String(64), nullable=False)
    period_start = Column(utc6(), nullable=False)
    period_end = Column(utc6(), nullable=False)
    as_of = Column(utc6(), nullable=False)
    evaluation_at = Column(utc6(), nullable=False)
    created_at = Column(utc6(), nullable=False)
    created_by = Column(Integer, ForeignKey("hoimsystem_users.user_id"), nullable=False)
    schema_version = Column(String(48), nullable=False)
    snapshot_json = Column(complete_json(), nullable=False)
    projection_json = Column(complete_json(), nullable=False)
    projection_hash = Column(String(64), nullable=False)
    content_hash = Column(String(64), nullable=False)
    status = Column(String(16), nullable=False, default="active")
    revision = Column(Integer, nullable=False, default=1)
    revoked_at = Column(utc6(), nullable=True)
    revoked_by = Column(Integer, ForeignKey("hoimsystem_users.user_id"), nullable=True)
    revoke_reason = Column(String(1000), nullable=False, default="")


class AISofaChangeAssessment(Base):
    __tablename__ = "hoimsystem_ai_sofa_change_assessment"
    __table_args__ = (
        lifecycle_constraint("ck_ai_sofa_change_governance"),
        CheckConstraint("evaluation_at <= created_at AND (revoked_at IS NULL OR revoked_at >= created_at)", name="ck_ai_sofa_change_clocks"),
        CheckConstraint(f"length(snapshot_json) <= {PRIVATE_BYTES} AND length(projection_json) <= {CHANGE_PROJECTION_BYTES}", name="ck_ai_sofa_change_json_bounds"),
        Index("idx_ai_sofa_change_scope", "patient_id", "admission_id", "created_at"),
        Index("idx_ai_sofa_change_current", "current_assessment_id", "status"),
    )

    change_assessment_id = Column(String(36), primary_key=True)
    patient_id = Column(Integer, ForeignKey("hoimsystem_patient.patient_id"), nullable=False)
    admission_id = Column(String(36), ForeignKey("hoimsystem_admission.admission_id"), nullable=False)
    current_assessment_id = Column(String(36), ForeignKey("hoimsystem_ai_sofa_assessment.assessment_id"), nullable=False)
    baseline_assessment_id = Column(String(36), ForeignKey("hoimsystem_ai_sofa_assessment.assessment_id"), nullable=True)
    infection_source_id = Column(String(36), ForeignKey("hoimsystem_inpatient_infection_episode_source.support_source_id"), nullable=False)
    evaluation_at = Column(utc6(), nullable=False)
    created_at = Column(utc6(), nullable=False)
    created_by = Column(Integer, ForeignKey("hoimsystem_users.user_id"), nullable=False)
    schema_version = Column(String(48), nullable=False)
    snapshot_json = Column(complete_json(), nullable=False)
    projection_json = Column(complete_json(), nullable=False)
    projection_hash = Column(String(64), nullable=False)
    content_hash = Column(String(64), nullable=False)
    status = Column(String(16), nullable=False, default="active")
    revision = Column(Integer, nullable=False, default=1)
    revoked_at = Column(utc6(), nullable=True)
    revoked_by = Column(Integer, ForeignKey("hoimsystem_users.user_id"), nullable=True)
    revoke_reason = Column(String(1000), nullable=False, default="")


class AISofaRunResult(Base):
    __tablename__ = "hoimsystem_ai_sofa_run_result"
    __table_args__ = (
        CheckConstraint(f"result_bytes > 0 AND result_bytes <= {RESULT_BYTES} AND length(result_json) <= {RESULT_BYTES}", name="ck_ai_sofa_result_json_bounds"),
        Index("idx_ai_sofa_result_created", "created_at"),
    )

    run_id = Column(String(36), ForeignKey("hoimsystem_ai_run.run_id"), primary_key=True)
    lease_token = Column(String(36), nullable=False)
    schema_version = Column(String(48), nullable=False)
    content_hash = Column(String(64), nullable=False)
    result_json = Column(complete_json(), nullable=False)
    result_bytes = Column(Integer, nullable=False)
    created_at = Column(utc6(), nullable=False)
