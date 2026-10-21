"""Complete governed Admission ledger evidence; no payment or charge writes."""

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


class AIChargeWriteGate(Base):
    __tablename__ = "hoimsystem_ai_charge_write_gate"
    __table_args__ = (CheckConstraint("gate_id=1 AND revision>0", name="ck_charge_gate_singleton"),)
    gate_id = Column(Integer, primary_key=True, autoincrement=False)
    revision = Column(Integer, nullable=False)


class AIChargeCaseSnapshot(Base):
    __tablename__ = "hoimsystem_ai_charge_case_snapshot"
    __table_args__ = (
        governance_check("charge_case"),
        CheckConstraint(
            f"length(snapshot_json)>0 AND length(snapshot_json)<={MAX_BYTES} AND (projection_json IS NULL OR (length(projection_json)>0 AND length(projection_json)<={MAX_BYTES})) AND length(review_basis_note)<=4000",
            name="ck_charge_case_bounds",
        ),
        CheckConstraint(
            "(status IN ('draft','rejected') AND projection_json IS NULL AND projection_hash IS NULL) OR (status='published' AND projection_json IS NOT NULL AND projection_hash IS NOT NULL) OR (status='revoked' AND ((reviewed_at IS NULL AND projection_json IS NULL AND projection_hash IS NULL) OR (reviewed_at IS NOT NULL AND projection_json IS NOT NULL AND projection_hash IS NOT NULL)))",
            name="ck_charge_case_projection",
        ),
        CheckConstraint(
            "(reviewed_at IS NULL OR reviewed_at>=created_at) AND (revoked_at IS NULL OR revoked_at>=created_at) AND (reviewed_at IS NULL OR revoked_at IS NULL OR revoked_at>=reviewed_at)",
            name="ck_charge_case_clocks",
        ),
        Index("idx_charge_case_scope", "patient_id", "admission_id", "created_at"),
    )
    case_snapshot_id = Column(String(36), primary_key=True)
    admission_id = Column(String(36), ForeignKey("hoimsystem_admission.admission_id"), nullable=False)
    patient_id = Column(Integer, ForeignKey("hoimsystem_patient.patient_id"), nullable=False)
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


CHARGE_RECONCILIATION_MODELS = (AIChargeWriteGate, AIChargeCaseSnapshot)
