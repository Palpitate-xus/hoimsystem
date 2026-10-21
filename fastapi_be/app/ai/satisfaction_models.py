"""Additive frozen review evidence; never rewrites a rating or a manual excerpt."""

from sqlalchemy import CheckConstraint, Column, Date, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects import mysql

from app.database import Base

MAX_BYTES = 8 * 1024 * 1024
MAX_ROOTS = 8192


def utc6():
    return DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql")


def original_json():
    return Text().with_variant(mysql.MEDIUMTEXT(), "mysql")


class AISatisfactionWriteGate(Base):
    __tablename__ = "hoimsystem_ai_satisfaction_write_gate"
    __table_args__ = (CheckConstraint("gate_id=1 AND revision>0", name="ck_satisfaction_gate_singleton"),)
    gate_id = Column(Integer, primary_key=True, autoincrement=False)
    revision = Column(Integer, nullable=False)


class AISatisfactionCase(Base):
    __tablename__ = "hoimsystem_ai_satisfaction_case"
    __table_args__ = (
        CheckConstraint("scope_kind IN ('hospital_reviews','explicit_doctor_cohort') AND date_to>=date_from", name="ck_satisfaction_case_scope"),
        CheckConstraint("length(doctor_ids_json)>0 AND length(doctor_ids_json)<=4096", name="ck_satisfaction_case_doctors"),
        CheckConstraint(
            f"length(snapshot_json)>0 AND length(snapshot_json)<={MAX_BYTES} AND (projection_json IS NULL OR (length(projection_json)>0 AND length(projection_json)<={MAX_BYTES})) AND length(review_basis_note)<=4000",
            name="ck_satisfaction_case_bounds",
        ),
        CheckConstraint(
            "(status='draft' AND revision=1 AND reviewed_at IS NULL AND reviewed_by IS NULL AND review_basis_note='' AND revoked_at IS NULL AND revoked_by IS NULL AND revoke_reason='') OR (status IN ('published','rejected') AND revision=2 AND reviewed_at IS NOT NULL AND reviewed_by IS NOT NULL AND review_basis_note<>'' AND revoked_at IS NULL AND revoked_by IS NULL AND revoke_reason='') OR (status='revoked' AND revoked_at IS NOT NULL AND revoked_by IS NOT NULL AND revoke_reason<>'' AND ((revision=2 AND reviewed_at IS NULL AND reviewed_by IS NULL AND review_basis_note='') OR (revision=3 AND reviewed_at IS NOT NULL AND reviewed_by IS NOT NULL AND review_basis_note<>'')))",
            name="ck_satisfaction_case_governance",
        ),
        CheckConstraint(
            "(status IN ('draft','rejected') AND projection_json IS NULL AND projection_hash IS NULL) OR (status='published' AND projection_json IS NOT NULL AND projection_hash IS NOT NULL) OR (status='revoked' AND ((reviewed_at IS NULL AND projection_json IS NULL AND projection_hash IS NULL) OR (reviewed_at IS NOT NULL AND projection_json IS NOT NULL AND projection_hash IS NOT NULL)))",
            name="ck_satisfaction_case_projection",
        ),
        CheckConstraint(
            "(reviewed_at IS NULL OR reviewed_at>=created_at) AND (revoked_at IS NULL OR revoked_at>=created_at) AND (reviewed_at IS NULL OR revoked_at IS NULL OR revoked_at>=reviewed_at)",
            name="ck_satisfaction_case_clocks",
        ),
        Index("idx_satisfaction_case_scope", "scope_kind", "date_from", "date_to", "created_at", "case_id"),
    )
    case_id = Column(String(36), primary_key=True)
    schema_version = Column(String(48), nullable=False)
    scope_kind = Column(String(32), nullable=False)
    # Technical scope header avoids loading protected comments to authorize a row.
    doctor_ids_json = Column(Text, nullable=False)
    date_from = Column(Date, nullable=False)
    date_to = Column(Date, nullable=False)
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


SATISFACTION_MODELS = (AISatisfactionWriteGate, AISatisfactionCase)
