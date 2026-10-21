"""Additive governed case evidence; no diagnosis, code or settlement writes."""

from sqlalchemy import CheckConstraint, Column, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects import mysql

from app.ai.supply_source_models import utc6
from app.database import Base

MAX_BYTES = 8 * 1024 * 1024


def original_json():
    return Text().with_variant(mysql.MEDIUMTEXT(), "mysql")


def governance_check(prefix):
    return CheckConstraint(
        "(status='draft' AND revision=1 AND reviewed_at IS NULL AND reviewed_by IS NULL AND review_basis_note='' AND revoked_at IS NULL AND revoked_by IS NULL AND revoke_reason='') OR (status IN ('published','rejected') AND revision=2 AND reviewed_at IS NOT NULL AND reviewed_by IS NOT NULL AND review_basis_note<>'' AND revoked_at IS NULL AND revoked_by IS NULL AND revoke_reason='') OR (status='revoked' AND revoked_at IS NOT NULL AND revoked_by IS NOT NULL AND revoke_reason<>'' AND ((revision=2 AND reviewed_at IS NULL AND reviewed_by IS NULL AND review_basis_note='') OR (revision=3 AND reviewed_at IS NOT NULL AND reviewed_by IS NOT NULL AND review_basis_note<>'')))",
        name="ck_" + prefix + "_governance",
    )


class AICodingWriteGate(Base):
    __tablename__ = "hoimsystem_ai_coding_write_gate"
    __table_args__ = (CheckConstraint("gate_id=1 AND revision>0", name="ck_coding_gate_singleton"),)
    gate_id = Column(Integer, primary_key=True, autoincrement=False)
    revision = Column(Integer, nullable=False)


class AICodingRulePackage(Base):
    __tablename__ = "hoimsystem_ai_coding_rule_package"
    __table_args__ = (
        governance_check("coding_package"),
        CheckConstraint("package_kind='local_prefix_snapshot'", name="ck_coding_package_kind"),
        CheckConstraint(f"length(snapshot_json)>0 AND length(snapshot_json)<={MAX_BYTES} AND length(review_basis_note)<=4000", name="ck_coding_package_bounds"),
        CheckConstraint(
            "(reviewed_at IS NULL OR reviewed_at>=created_at) AND (revoked_at IS NULL OR revoked_at>=created_at) AND (reviewed_at IS NULL OR revoked_at IS NULL OR revoked_at>=reviewed_at)",
            name="ck_coding_package_clocks",
        ),
        Index("idx_coding_package_created", "created_at", "package_id"),
    )
    package_id = Column(String(36), primary_key=True)
    package_kind = Column(String(32), nullable=False)
    schema_version = Column(String(48), nullable=False)
    created_at = Column(utc6(), nullable=False)
    created_by = Column(Integer, ForeignKey("hoimsystem_users.user_id"), nullable=False)
    snapshot_json = Column(original_json(), nullable=False)
    content_hash = Column(String(64), nullable=False)
    collection_digest = Column(String(64), nullable=False)
    status = Column(String(16), nullable=False)
    revision = Column(Integer, nullable=False)
    reviewed_at = Column(utc6(), nullable=True)
    reviewed_by = Column(Integer, ForeignKey("hoimsystem_users.user_id"), nullable=True)
    review_basis_note = Column(Text, nullable=False)
    revoked_at = Column(utc6(), nullable=True)
    revoked_by = Column(Integer, ForeignKey("hoimsystem_users.user_id"), nullable=True)
    revoke_reason = Column(String(1000), nullable=False)


class AICodingCaseSnapshot(Base):
    __tablename__ = "hoimsystem_ai_coding_case_snapshot"
    __table_args__ = (
        governance_check("coding_case"),
        CheckConstraint(
            f"length(snapshot_json)>0 AND length(snapshot_json)<={MAX_BYTES} AND (projection_json IS NULL OR (length(projection_json)>0 AND length(projection_json)<={MAX_BYTES})) AND length(review_basis_note)<=4000",
            name="ck_coding_case_bounds",
        ),
        CheckConstraint(
            "(status IN ('draft','rejected') AND projection_json IS NULL AND projection_hash IS NULL) OR (status='published' AND projection_json IS NOT NULL AND projection_hash IS NOT NULL) OR (status='revoked' AND ((reviewed_at IS NULL AND projection_json IS NULL AND projection_hash IS NULL) OR (reviewed_at IS NOT NULL AND projection_json IS NOT NULL AND projection_hash IS NOT NULL)))",
            name="ck_coding_case_projection",
        ),
        CheckConstraint(
            "(reviewed_at IS NULL OR reviewed_at>=created_at) AND (revoked_at IS NULL OR revoked_at>=created_at) AND (reviewed_at IS NULL OR revoked_at IS NULL OR revoked_at>=reviewed_at)",
            name="ck_coding_case_clocks",
        ),
        Index("idx_coding_case_scope", "patient_id", "admission_id", "home_id", "created_at"),
    )
    case_snapshot_id = Column(String(36), primary_key=True)
    home_id = Column(String(36), ForeignKey("hoimsystem_medical_record_home.home_id"), nullable=False)
    admission_id = Column(String(36), ForeignKey("hoimsystem_admission.admission_id"), nullable=False)
    patient_id = Column(Integer, ForeignKey("hoimsystem_patient.patient_id"), nullable=False)
    rule_package_id = Column(String(36), ForeignKey("hoimsystem_ai_coding_rule_package.package_id"), nullable=True)
    schema_version = Column(String(48), nullable=False)
    created_at = Column(utc6(), nullable=False)
    created_by = Column(Integer, ForeignKey("hoimsystem_users.user_id"), nullable=False)
    snapshot_json = Column(original_json(), nullable=False)
    content_hash = Column(String(64), nullable=False)
    collection_digest = Column(String(64), nullable=False)
    projection_json = Column(original_json(), nullable=True)
    projection_hash = Column(String(64), nullable=True)
    status = Column(String(16), nullable=False)
    revision = Column(Integer, nullable=False)
    reviewed_at = Column(utc6(), nullable=True)
    reviewed_by = Column(Integer, ForeignKey("hoimsystem_users.user_id"), nullable=True)
    review_basis_note = Column(Text, nullable=False)
    revoked_at = Column(utc6(), nullable=True)
    revoked_by = Column(Integer, ForeignKey("hoimsystem_users.user_id"), nullable=True)
    revoke_reason = Column(String(1000), nullable=False)


class AICodingRunResult(Base):
    __tablename__ = "hoimsystem_ai_coding_run_result"
    __table_args__ = (
        CheckConstraint(f"result_bytes>0 AND result_bytes<={MAX_BYTES} AND length(result_json)>0 AND length(result_json)<={MAX_BYTES}", name="ck_coding_result_bounds"),
        Index("idx_coding_result_case", "case_snapshot_id", "created_at"),
    )
    run_id = Column(String(36), ForeignKey("hoimsystem_ai_run.run_id"), primary_key=True)
    case_snapshot_id = Column(String(36), ForeignKey("hoimsystem_ai_coding_case_snapshot.case_snapshot_id"), nullable=False)
    lease_token = Column(String(36), nullable=False)
    schema_version = Column(String(48), nullable=False)
    source_binding_hash = Column(String(64), nullable=False)
    content_hash = Column(String(64), nullable=False)
    result_json = Column(original_json(), nullable=False)
    result_bytes = Column(Integer, nullable=False)
    created_at = Column(utc6(), nullable=False)


CODING_EVIDENCE_MODELS = (AICodingWriteGate, AICodingRulePackage, AICodingCaseSnapshot, AICodingRunResult)
