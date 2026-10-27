"""Additive governed finite-report sources; no surveillance model or clinical result."""

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, LargeBinary, String, Text, UniqueConstraint, cast, column, func
from sqlalchemy import LargeBinary as Binary
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import declared_attr

from app.database import Base
from app.sql_constraints import PortableCheckConstraint as CheckConstraint


def utc6():
    return DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql")


def medium_text():
    return Text().with_variant(mysql.MEDIUMTEXT(), "mysql")


def governance_checks(prefix):
    return (
        CheckConstraint(
            "privacy_review IN ('unknown','confirmed','not_confirmed') AND faithfulness_review IN ('unknown','confirmed','not_confirmed') AND ((reviewed_by IS NULL AND privacy_review='unknown' AND faithfulness_review='unknown') OR (reviewed_by IS NOT NULL AND privacy_review<>'unknown' AND faithfulness_review<>'unknown')) AND (status<>'published' OR (privacy_review='confirmed' AND faithfulness_review='confirmed')) AND (status<>'rejected' OR privacy_review='not_confirmed' OR faithfulness_review='not_confirmed')",
            name=f"ck_inf_{prefix}_review_flags",
        ),
        CheckConstraint(func.length(cast(column("payload_json"), Binary)) <= 8388608, name=f"ck_inf_{prefix}_utf8"),
        CheckConstraint(
            "(status='draft' AND revision=1 AND reviewed_by IS NULL AND reviewed_at IS NULL AND review_event_id IS NULL AND review_basis='' AND revoked_by IS NULL AND revoked_at IS NULL AND revoke_event_id IS NULL AND revoke_basis='') OR (status IN ('published','rejected') AND revision=2 AND reviewed_by IS NOT NULL AND reviewed_by<>created_by AND reviewed_at IS NOT NULL AND review_event_id IS NOT NULL AND review_basis<>'' AND revoked_by IS NULL AND revoked_at IS NULL AND revoke_event_id IS NULL AND revoke_basis='') OR (status='revoked' AND revoked_by IS NOT NULL AND revoked_at IS NOT NULL AND revoke_event_id IS NOT NULL AND revoke_basis<>'' AND ((revision=2 AND reviewed_by IS NULL AND review_event_id IS NULL) OR (revision=3 AND reviewed_by IS NOT NULL AND review_event_id IS NOT NULL)))",
            name=f"ck_inf_{prefix}_governance",
        ),
        CheckConstraint(
            "(reviewed_at IS NULL OR reviewed_at>=recorded_at) AND (revoked_at IS NULL OR revoked_at>=recorded_at) AND (reviewed_at IS NULL OR revoked_at IS NULL OR revoked_at>=reviewed_at)",
            name=f"ck_inf_{prefix}_clock",
        ),
        CheckConstraint(
            "length(payload_json)>0 AND length(payload_json)<=8388608 AND length(content_hash)=64 AND length(review_basis)<=4000 AND length(revoke_basis)<=4000", name=f"ck_inf_{prefix}_bounds"
        ),
    )


class Governed:
    payload_json = Column(medium_text(), nullable=False)
    content_hash = Column(String(64), nullable=False)
    status = Column(String(16), nullable=False)
    revision = Column(Integer, nullable=False)
    recorded_at = Column(utc6(), nullable=False)
    reviewed_at = Column(utc6(), nullable=True)
    review_basis = Column(Text, nullable=False)
    privacy_review = Column(String(20), nullable=False)
    faithfulness_review = Column(String(20), nullable=False)
    revoked_at = Column(utc6(), nullable=True)
    revoke_basis = Column(Text, nullable=False)

    @declared_attr
    def created_by(cls):  # noqa: N805
        return Column(Integer, ForeignKey("hoimsystem_users.user_id"), nullable=False)

    @declared_attr
    def reviewed_by(cls):  # noqa: N805
        return Column(Integer, ForeignKey("hoimsystem_users.user_id"), nullable=True)

    @declared_attr
    def revoked_by(cls):  # noqa: N805
        return Column(Integer, ForeignKey("hoimsystem_users.user_id"), nullable=True)

    @declared_attr
    def create_event_id(cls):  # noqa: N805
        return Column(Integer, ForeignKey("hoimsystem_ai_audit_event.event_id"), nullable=False)

    @declared_attr
    def review_event_id(cls):  # noqa: N805
        return Column(Integer, ForeignKey("hoimsystem_ai_audit_event.event_id"), nullable=True)

    @declared_attr
    def revoke_event_id(cls):  # noqa: N805
        return Column(Integer, ForeignKey("hoimsystem_ai_audit_event.event_id"), nullable=True)


class AIInfectionWriteGate(Base):
    __tablename__ = "hoimsystem_ai_infection_write_gate"
    __table_args__ = (CheckConstraint("gate_id=1 AND revision=1", name="ck_inf_gate_singleton"),)
    gate_id = Column(Integer, primary_key=True, autoincrement=False)
    revision = Column(Integer, nullable=False)


class AIInfectionPurposeGrant(Governed, Base):
    __tablename__ = "hoimsystem_ai_infection_purpose_grant"
    __table_args__ = governance_checks("grant") + (
        CheckConstraint("purpose IN ('infection_surveillance_processing','external_model_transfer') AND valid_to>valid_from", name="ck_inf_grant_purpose"),
        Index("idx_inf_grant_subject", "patient_id", "user_id", "purpose", "grant_id"),
    )
    grant_id = Column(String(36), primary_key=True)
    patient_id = Column(Integer, ForeignKey("hoimsystem_patient.patient_id"), nullable=False)
    user_id = Column(Integer, ForeignKey("hoimsystem_users.user_id"), nullable=False)
    purpose = Column(String(40), nullable=False)
    valid_from = Column(utc6(), nullable=False)
    valid_to = Column(utc6(), nullable=False)


class AIInfectionDefinition(Governed, Base):
    __tablename__ = "hoimsystem_ai_infection_definition"
    __table_args__ = governance_checks("definition")
    definition_id = Column(String(36), primary_key=True)


class AIInfectionCaseReview(Governed, Base):
    __tablename__ = "hoimsystem_ai_infection_case_review"
    __table_args__ = governance_checks("review") + (
        UniqueConstraint("case_id", "original_content_hash", "definition_content_hash", "definition_governance_hash", name="uq_inf_review_exact_root"),
        Index("idx_inf_review_definition", "definition_id", "case_id"),
    )
    review_id = Column(String(36), primary_key=True)
    case_id = Column(String(36), ForeignKey("hoimsystem_infection_case.case_id"), nullable=False)
    patient_id = Column(Integer, ForeignKey("hoimsystem_patient.patient_id"), nullable=False)
    definition_id = Column(String(36), ForeignKey("hoimsystem_ai_infection_definition.definition_id"), nullable=False)
    original_content_hash = Column(String(64), nullable=False)
    definition_content_hash = Column(String(64), nullable=False)
    definition_governance_hash = Column(String(64), nullable=False)


class AIInfectionSnapshot(Base):
    __tablename__ = "hoimsystem_ai_infection_snapshot"
    __table_args__ = (
        *(CheckConstraint(func.length(cast(column(field), Binary)) <= 8388608, name=f"ck_inf_snapshot_{field}_utf8") for field in ("private_json", "public_json", "witness_json")),
        CheckConstraint(
            "schema_version='infection_cluster_snapshot_v1' AND length(private_json)>0 AND length(private_json)<=8388608 AND length(public_json)>0 AND length(public_json)<=8388608 AND length(witness_json)>0 AND length(witness_json)<=8388608 AND length(mapping_key)=32",
            name="ck_inf_snapshot_storage",
        ),
        CheckConstraint("length(private_hash)=64 AND length(public_hash)=64 AND length(witness_hash)=64", name="ck_inf_snapshot_hashes"),
        Index("idx_inf_snapshot_created", "created_by", "captured_at", "snapshot_id"),
    )
    snapshot_id = Column(String(36), primary_key=True)
    definition_id = Column(String(36), ForeignKey("hoimsystem_ai_infection_definition.definition_id"), nullable=False)
    created_by = Column(Integer, ForeignKey("hoimsystem_users.user_id"), nullable=False)
    create_event_id = Column(Integer, ForeignKey("hoimsystem_ai_audit_event.event_id"), nullable=False)
    schema_version = Column(String(40), nullable=False)
    captured_at = Column(utc6(), nullable=False)
    scope_json = Column(Text, nullable=False)
    private_json = Column(medium_text(), nullable=False)
    private_hash = Column(String(64), nullable=False)
    public_json = Column(medium_text(), nullable=False)
    public_hash = Column(String(64), nullable=False)
    witness_json = Column(medium_text(), nullable=False)
    witness_hash = Column(String(64), nullable=False)
    mapping_key = Column(LargeBinary(32), nullable=False)


INFECTION_SOURCE_MODELS = (AIInfectionWriteGate, AIInfectionPurposeGrant, AIInfectionDefinition, AIInfectionCaseReview, AIInfectionSnapshot)
