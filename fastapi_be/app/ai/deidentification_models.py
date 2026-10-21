"""Selected-field originals and independently reviewed controlled releases.

No clinical record is changed. Technical governance alone grants no clinical
purpose, model transfer or export authority. All bodies have real UTF8 caps.
"""

from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Index, Integer, LargeBinary, String, Text, cast, column, func
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import declared_attr

from app.database import Base

BODY_BYTES = 8 * 1024 * 1024
NOTE_BYTES = 4000
MANUAL_BYTES = 65535


def utc6():
    return DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql")


def body():
    return Text().with_variant(mysql.MEDIUMTEXT(), "mysql")


def byte_length(name):
    return func.length(cast(column(name), LargeBinary))


def json_check(name, maximum, label):
    return CheckConstraint((byte_length(name) > 0) & (byte_length(name) <= maximum) & (func.json_valid(column(name)) == 1), name=label)


def hash_check(name, label):
    remaining = name
    for character in "0123456789abcdef":
        remaining = "replace(" + remaining + ",'" + character + "','')"
    return CheckConstraint("length(" + name + ")=64 AND length(" + remaining + ")=0", name=label)


class Governance:
    status = Column(String(16), nullable=False)
    revision = Column(Integer, nullable=False)
    created_at = Column(utc6(), nullable=False)
    reviewed_at = Column(utc6(), nullable=True)
    review_basis_note = Column(Text, nullable=False)
    revoked_at = Column(utc6(), nullable=True)
    revoke_reason = Column(String(1000), nullable=False)

    @declared_attr
    def created_by(cls):  # noqa: N805
        return Column(Integer, ForeignKey("hoimsystem_users.user_id"), nullable=False)

    @declared_attr
    def reviewed_by(cls):  # noqa: N805
        return Column(Integer, ForeignKey("hoimsystem_users.user_id"), nullable=True)

    @declared_attr
    def revoked_by(cls):  # noqa: N805
        return Column(Integer, ForeignKey("hoimsystem_users.user_id"), nullable=True)


class ManualReview:
    manual_status = Column(String(40), nullable=False)
    manual_reviewed_at = Column(utc6(), nullable=True)
    manual_review_json = Column(Text, nullable=True)

    @declared_attr
    def manual_reviewed_by(cls):  # noqa: N805
        return Column(Integer, ForeignKey("hoimsystem_users.user_id"), nullable=True)


def governance_constraints(prefix):
    return (
        CheckConstraint(
            "(HEX(status)=HEX('draft') AND revision=1 AND reviewed_by IS NULL AND reviewed_at IS NULL AND review_basis_note='' AND revoked_by IS NULL AND revoked_at IS NULL AND revoke_reason='') OR "
            "(HEX(status) IN (HEX('published'),HEX('rejected')) AND revision=2 AND reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL AND review_basis_note<>'' AND revoked_by IS NULL AND revoked_at IS NULL AND revoke_reason='') OR "
            "(HEX(status)=HEX('revoked') AND revoked_by IS NOT NULL AND revoked_at IS NOT NULL AND revoke_reason<>'' AND ((revision=2 AND reviewed_by IS NULL AND reviewed_at IS NULL AND review_basis_note='') OR (revision=3 AND reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL AND review_basis_note<>'')))",
            name="ck_deid_" + prefix + "_governance",
        ),
        CheckConstraint(
            "created_by>0 AND (reviewed_at IS NULL OR reviewed_at>=created_at) AND (revoked_at IS NULL OR revoked_at>=created_at) AND (reviewed_at IS NULL OR revoked_at IS NULL OR revoked_at>=reviewed_at)",
            name="ck_deid_" + prefix + "_clocks",
        ),
        CheckConstraint((byte_length("review_basis_note") <= NOTE_BYTES) & (byte_length("revoke_reason") <= NOTE_BYTES), name="ck_deid_" + prefix + "_notes"),
        hash_check("content_hash", "ck_deid_" + prefix + "_content"),
    )


def manual_constraints(prefix):
    return (
        CheckConstraint(
            "(HEX(manual_status)=HEX('unknown') AND manual_reviewed_by IS NULL AND manual_reviewed_at IS NULL AND manual_review_json IS NULL) OR "
            "(HEX(manual_status) IN (HEX('reviewed_residual_risk_remains'),HEX('not_confirmed')) AND manual_reviewed_by IS NOT NULL AND manual_reviewed_by>0 AND manual_reviewed_by<>created_by AND manual_reviewed_at IS NOT NULL AND manual_review_json IS NOT NULL)",
            name="ck_deid_" + prefix + "_manual",
        ),
        CheckConstraint("manual_reviewed_at IS NULL OR (manual_reviewed_at>=created_at AND (reviewed_at IS NULL OR reviewed_at>=manual_reviewed_at))", name="ck_deid_" + prefix + "_manual_clock"),
        CheckConstraint(
            column("manual_review_json").is_(None)
            | ((byte_length("manual_review_json") > 0) & (byte_length("manual_review_json") <= MANUAL_BYTES) & (func.json_valid(column("manual_review_json")) == 1)),
            name="ck_deid_" + prefix + "_manual_json",
        ),
    )


class AIDeidentificationCase(Governance, Base):
    __tablename__ = "hoimsystem_ai_deidentification_case"
    case_id = Column(String(36), primary_key=True)
    scope_id = Column(String(36), ForeignKey("hoimsystem_ai_research_study_scope.scope_id"), nullable=False)
    patient_id = Column(Integer, ForeignKey("hoimsystem_patient.patient_id"), nullable=False)
    schema_version = Column(String(48), nullable=False)
    snapshot_json = Column(body(), nullable=False)
    content_hash = Column(String(64), nullable=False)
    collection_digest = Column(String(64), nullable=False)
    parent_binding_hash = Column(String(64), nullable=False)
    manifest_hash = Column(String(64), nullable=False)
    __table_args__ = (
        *governance_constraints("case"),
        CheckConstraint("HEX(schema_version)=HEX('deidentification_case_v1') AND patient_id>0", name="ck_deid_case_schema"),
        json_check("snapshot_json", BODY_BYTES, "ck_deid_case_body"),
        *(hash_check(n, "ck_deid_case_" + n) for n in ("collection_digest", "parent_binding_hash", "manifest_hash")),
        Index("idx_deid_case_scope_patient", "scope_id", "patient_id", "status", "case_id"),
    )


class AIDeidentificationReview(ManualReview, Governance, Base):
    __tablename__ = "hoimsystem_ai_deidentification_review"
    review_id = Column(String(36), primary_key=True)
    case_id = Column(String(36), ForeignKey("hoimsystem_ai_deidentification_case.case_id"), nullable=False)
    schema_version = Column(String(48), nullable=False)
    review_json = Column(body(), nullable=False)
    content_hash = Column(String(64), nullable=False)
    output_json = Column(body(), nullable=False)
    output_hash = Column(String(64), nullable=False)
    output_bytes = Column(Integer, nullable=False)
    __table_args__ = (
        *governance_constraints("review"),
        *manual_constraints("review"),
        CheckConstraint("HEX(schema_version)=HEX('deidentification_review_v1')", name="ck_deid_review_schema"),
        json_check("review_json", BODY_BYTES, "ck_deid_review_body"),
        json_check("output_json", BODY_BYTES, "ck_deid_review_output"),
        CheckConstraint((column("output_bytes") > 0) & (column("output_bytes") <= BODY_BYTES) & (column("output_bytes") == byte_length("output_json")), name="ck_deid_review_output_bytes"),
        hash_check("output_hash", "ck_deid_review_output_hash"),
        Index("idx_deid_review_case", "case_id", "status", "review_id"),
    )


class AIDeidentificationExportRelease(ManualReview, Governance, Base):
    __tablename__ = "hoimsystem_ai_deidentification_release"
    release_id = Column(String(36), primary_key=True)
    review_id = Column(String(36), ForeignKey("hoimsystem_ai_deidentification_review.review_id"), nullable=False)
    schema_version = Column(String(48), nullable=False)
    release_json = Column(body(), nullable=False)
    content_hash = Column(String(64), nullable=False)
    artifact_json = Column(body(), nullable=False)
    artifact_hash = Column(String(64), nullable=False)
    artifact_bytes = Column(Integer, nullable=False)
    valid_from = Column(utc6(), nullable=True)
    valid_until = Column(utc6(), nullable=True)
    maximum_downloads = Column(Integer, nullable=False)
    download_count = Column(Integer, nullable=False)
    last_download_event_id = Column(Integer, ForeignKey("hoimsystem_ai_audit_event.event_id"), nullable=True)
    last_download_at = Column(utc6(), nullable=True)
    __table_args__ = (
        *governance_constraints("release"),
        *manual_constraints("release"),
        CheckConstraint("HEX(schema_version)=HEX('deidentification_release_v1')", name="ck_deid_release_schema"),
        json_check("release_json", BODY_BYTES, "ck_deid_release_body"),
        json_check("artifact_json", BODY_BYTES, "ck_deid_release_artifact"),
        CheckConstraint((column("artifact_bytes") > 0) & (column("artifact_bytes") <= BODY_BYTES) & (column("artifact_bytes") == byte_length("artifact_json")), name="ck_deid_release_artifact_bytes"),
        hash_check("artifact_hash", "ck_deid_release_artifact_hash"),
        CheckConstraint("(valid_from IS NULL AND valid_until IS NULL) OR (valid_from IS NOT NULL AND valid_until IS NOT NULL AND valid_until>valid_from)", name="ck_deid_release_validity"),
        CheckConstraint("maximum_downloads BETWEEN 1 AND 100 AND download_count>=0 AND download_count<=maximum_downloads", name="ck_deid_release_quota"),
        CheckConstraint(
            "(download_count=0 AND last_download_event_id IS NULL AND last_download_at IS NULL) OR (download_count>0 AND last_download_event_id IS NOT NULL AND last_download_at IS NOT NULL AND last_download_event_id>0 AND last_download_at>=created_at)",
            name="ck_deid_release_receipt",
        ),
        Index("idx_deid_release_review", "review_id", "status", "release_id"),
    )


DEIDENTIFICATION_MODELS = (AIDeidentificationCase, AIDeidentificationReview, AIDeidentificationExportRelease)
