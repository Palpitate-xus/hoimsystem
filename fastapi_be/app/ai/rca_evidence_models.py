"""Additive governed RCA sources; no legacy event/RCA schema is changed."""

from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, ForeignKeyConstraint, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import declared_attr

from app.database import Base


def utc6():
    return DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql")


def whole_json():
    return Text().with_variant(mysql.MEDIUMTEXT(), "mysql")


class AIRcaPurposeGrant(Base):
    __tablename__ = "hoimsystem_ai_rca_purpose_grant"
    __table_args__ = (
        CheckConstraint("purpose = 'incident_rca' AND permission_kind IN ('event_investigation','associated_patient_processing')", name="ck_rca_grant_purpose"),
        CheckConstraint("permission_kind <> 'associated_patient_processing' OR patient_id_at_grant IS NOT NULL", name="ck_rca_grant_patient_scope"),
        CheckConstraint("valid_until > issued_at AND length(grant_json) > 0 AND length(grant_json) <= 65535", name="ck_rca_grant_boundaries"),
        CheckConstraint(
            "(status = 'active' AND revision = 1 AND revoked_by IS NULL AND revoked_at IS NULL AND revoke_reason = '' AND revoked_audit_event_id IS NULL) OR "
            "(status = 'revoked' AND revision = 2 AND revoked_by IS NOT NULL AND revoked_at IS NOT NULL AND revoked_at >= issued_at AND revoke_reason <> '' AND revoked_audit_event_id IS NOT NULL)",
            name="ck_rca_grant_governance",
        ),
        UniqueConstraint("grant_id", "content_hash", name="uq_rca_grant_content"),
        UniqueConstraint("grant_id", "event_id", "grantee_id", name="uq_rca_grant_scope_owner"),
        Index("idx_rca_grant_current_scope", "event_id", "grantee_id", "permission_kind", "status"),
    )
    grant_id = Column(String(36), primary_key=True)
    event_id = Column(Integer, ForeignKey("hoimsystem_adverse_event.event_id"), nullable=False)
    patient_id_at_grant = Column(Integer, ForeignKey("hoimsystem_patient.patient_id"), nullable=True)
    grantee_id = Column(Integer, ForeignKey("hoimsystem_users.user_id"), nullable=False)
    permission_kind = Column(String(40), nullable=False)
    purpose = Column(String(32), nullable=False)
    grant_json = Column(Text, nullable=False)
    content_hash = Column(String(64), nullable=False)
    issued_by = Column(Integer, ForeignKey("hoimsystem_users.user_id"), nullable=False)
    issued_at = Column(utc6(), nullable=False)
    valid_until = Column(utc6(), nullable=False)
    status = Column(String(16), nullable=False)
    revision = Column(Integer, nullable=False)
    revoked_by = Column(Integer, ForeignKey("hoimsystem_users.user_id"), nullable=True)
    revoked_at = Column(utc6(), nullable=True)
    revoke_reason = Column(String(1000), nullable=False)
    created_audit_event_id = Column(Integer, ForeignKey("hoimsystem_ai_audit_event.event_id"), nullable=False, unique=True)
    revoked_audit_event_id = Column(Integer, ForeignKey("hoimsystem_ai_audit_event.event_id"), nullable=True, unique=True)


class ReviewColumns:
    status = Column(String(16), nullable=False)
    revision = Column(Integer, nullable=False)
    privacy_review = Column(String(20), nullable=False)
    faithfulness_review = Column(String(20), nullable=False)
    provenance_review = Column(String(20), nullable=False)
    reviewed_at = Column(utc6(), nullable=True)
    review_basis_note = Column(String(1000), nullable=False)
    revoked_at = Column(utc6(), nullable=True)
    revoke_reason = Column(String(1000), nullable=False)

    @declared_attr
    def reviewed_by(cls):  # noqa: N805
        return Column(Integer, ForeignKey("hoimsystem_users.user_id"), nullable=True)

    @declared_attr
    def revoked_by(cls):  # noqa: N805
        return Column(Integer, ForeignKey("hoimsystem_users.user_id"), nullable=True)

    @declared_attr
    def created_audit_event_id(cls):  # noqa: N805
        return Column(Integer, ForeignKey("hoimsystem_ai_audit_event.event_id"), nullable=False, unique=True)

    @declared_attr
    def reviewed_audit_event_id(cls):  # noqa: N805
        return Column(Integer, ForeignKey("hoimsystem_ai_audit_event.event_id"), nullable=True, unique=True)

    @declared_attr
    def revoked_audit_event_id(cls):  # noqa: N805
        return Column(Integer, ForeignKey("hoimsystem_ai_audit_event.event_id"), nullable=True, unique=True)


def review_constraints(prefix):
    return (
        CheckConstraint(
            "privacy_review IN ('unknown','confirmed','not_confirmed') AND faithfulness_review IN ('unknown','confirmed','not_confirmed') AND "
            "provenance_review IN ('unknown','confirmed','not_confirmed')",
            name=f"ck_rca_{prefix}_reviews",
        ),
        CheckConstraint(
            "(status = 'draft' AND revision = 1 AND reviewed_by IS NULL AND reviewed_at IS NULL AND reviewed_audit_event_id IS NULL AND review_basis_note = '' AND "
            "privacy_review = 'unknown' AND faithfulness_review = 'unknown' AND provenance_review = 'unknown' AND revoked_by IS NULL AND revoked_at IS NULL AND revoked_audit_event_id IS NULL AND revoke_reason = '') OR "
            "(status IN ('published','rejected') AND revision = 2 AND reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL AND reviewed_audit_event_id IS NOT NULL AND review_basis_note <> '' AND "
            "revoked_by IS NULL AND revoked_at IS NULL AND revoked_audit_event_id IS NULL AND revoke_reason = '') OR "
            "(status = 'revoked' AND revoked_by IS NOT NULL AND revoked_at IS NOT NULL AND revoked_audit_event_id IS NOT NULL AND revoke_reason <> '' AND "
            "((revision = 2 AND reviewed_by IS NULL AND reviewed_at IS NULL AND reviewed_audit_event_id IS NULL AND review_basis_note = '' AND privacy_review = 'unknown' AND faithfulness_review = 'unknown' AND provenance_review = 'unknown') OR "
            "(revision = 3 AND reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL AND reviewed_audit_event_id IS NOT NULL AND review_basis_note <> '')))",
            name=f"ck_rca_{prefix}_governance",
        ),
        CheckConstraint("status <> 'published' OR (privacy_review = 'confirmed' AND faithfulness_review = 'confirmed' AND provenance_review = 'confirmed')", name=f"ck_rca_{prefix}_publication"),
        CheckConstraint("status <> 'rejected' OR privacy_review <> 'confirmed' OR faithfulness_review <> 'confirmed' OR provenance_review <> 'confirmed'", name=f"ck_rca_{prefix}_rejection"),
        CheckConstraint(
            "(reviewed_at IS NULL OR reviewed_at >= recorded_at) AND (revoked_at IS NULL OR revoked_at >= recorded_at) AND (reviewed_at IS NULL OR revoked_at IS NULL OR revoked_at >= reviewed_at)",
            name=f"ck_rca_{prefix}_clocks",
        ),
        CheckConstraint("json_bytes > 0 AND json_bytes <= 8388608", name=f"ck_rca_{prefix}_json_bytes"),
    )


class AIRcaEvidenceOriginal(ReviewColumns, Base):
    __tablename__ = "hoimsystem_ai_rca_evidence_original"
    __table_args__ = review_constraints("original") + (
        UniqueConstraint("original_id", "content_hash", name="uq_rca_original_content"),
        CheckConstraint("origin_kind IN ('legacy_event','legacy_rca','manual_evidence','human_timeline')", name="ck_rca_original_origin"),
        CheckConstraint("(origin_kind = 'legacy_rca' AND legacy_rca_id IS NOT NULL) OR (origin_kind <> 'legacy_rca' AND legacy_rca_id IS NULL)", name="ck_rca_original_legacy_ref"),
        Index("idx_rca_original_event", "event_id", "recorded_at", "original_id"),
    )
    original_id = Column(String(36), primary_key=True)
    event_id = Column(Integer, ForeignKey("hoimsystem_adverse_event.event_id"), nullable=False)
    patient_id_at_capture = Column(Integer, ForeignKey("hoimsystem_patient.patient_id"), nullable=True)
    legacy_rca_id = Column(Integer, ForeignKey("hoimsystem_adverse_event_rca.rca_id"), nullable=True)
    origin_kind = Column(String(32), nullable=False)
    original_json = Column(whole_json(), nullable=False)
    json_bytes = Column(Integer, nullable=False)
    content_hash = Column(String(64), nullable=False)
    created_by = Column(Integer, ForeignKey("hoimsystem_users.user_id"), nullable=False)
    recorded_at = Column(utc6(), nullable=False)


class AIRcaEvidenceCase(ReviewColumns, Base):
    __tablename__ = "hoimsystem_ai_rca_evidence_case"
    __table_args__ = review_constraints("case") + (
        UniqueConstraint("case_id", "content_hash", name="uq_rca_case_content"),
        ForeignKeyConstraint(
            ["event_grant_id", "event_id", "created_by"],
            ["hoimsystem_ai_rca_purpose_grant.grant_id", "hoimsystem_ai_rca_purpose_grant.event_id", "hoimsystem_ai_rca_purpose_grant.grantee_id"],
            name="fk_rca_case_event_grantee",
        ),
        ForeignKeyConstraint(
            ["patient_grant_id", "event_id", "created_by"],
            ["hoimsystem_ai_rca_purpose_grant.grant_id", "hoimsystem_ai_rca_purpose_grant.event_id", "hoimsystem_ai_rca_purpose_grant.grantee_id"],
            name="fk_rca_case_patient_grantee",
        ),
        CheckConstraint(
            "(patient_id_at_capture IS NULL AND patient_grant_id IS NULL) OR (patient_id_at_capture IS NOT NULL AND patient_grant_id IS NOT NULL AND patient_grant_id <> event_grant_id)",
            name="ck_rca_case_patient_purpose",
        ),
        CheckConstraint("member_count >= 1 AND member_count <= 4096", name="ck_rca_case_members"),
        Index("idx_rca_case_event", "event_id", "recorded_at", "case_id"),
    )
    case_id = Column(String(36), primary_key=True)
    event_id = Column(Integer, ForeignKey("hoimsystem_adverse_event.event_id"), nullable=False)
    patient_id_at_capture = Column(Integer, ForeignKey("hoimsystem_patient.patient_id"), nullable=True)
    event_grant_id = Column(String(36), ForeignKey("hoimsystem_ai_rca_purpose_grant.grant_id"), nullable=False)
    patient_grant_id = Column(String(36), ForeignKey("hoimsystem_ai_rca_purpose_grant.grant_id"), nullable=True)
    case_json = Column(whole_json(), nullable=False)
    json_bytes = Column(Integer, nullable=False)
    member_count = Column(Integer, nullable=False)
    collection_hash = Column(String(64), nullable=False)
    content_hash = Column(String(64), nullable=False)
    created_by = Column(Integer, ForeignKey("hoimsystem_users.user_id"), nullable=False)
    recorded_at = Column(utc6(), nullable=False)


RCA_EVIDENCE_MODELS = (AIRcaPurposeGrant, AIRcaEvidenceOriginal, AIRcaEvidenceCase)
