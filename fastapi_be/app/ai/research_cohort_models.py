"""Bounded research originals; authorization records are not IRB certification.

Project access, each patient's recorded research permission, independent manual
review and Super technical governance remain separate. None of these tables
writes a clinical record, exports a dataset or grants unrestricted patient data.
"""

from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Index, Integer, LargeBinary, String, Text, cast, column, func
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import declared_attr

from app.database import Base

SOURCE_BYTES = 262144
PARENT_BYTES = 32768
SNAPSHOT_BYTES = 8388608
BASIS_BYTES = 4000


def utc6():
    return DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql")


def original_json():
    return Text().with_variant(mysql.MEDIUMTEXT(), "mysql")


def _bytes(name):
    return func.length(cast(column(name), LargeBinary))


def _json_constraint(name, maximum, label):
    return CheckConstraint((_bytes(name) > 0) & (_bytes(name) <= maximum) & (func.json_valid(column(name)) == 1), name=label)


def _hash_constraint(name, label, *, nullable=False):
    remaining = name
    for character in "0123456789abcdef":
        remaining = "replace(" + remaining + ",'" + character + "','')"
    expression = "length(" + name + ")=64 AND length(" + remaining + ")=0"
    return CheckConstraint((name + " IS NULL OR (" + expression + ")") if nullable else expression, name=label)


class GovernanceColumns:
    status = Column(String(16), nullable=False)
    revision = Column(Integer, nullable=False)
    reviewed_at = Column(utc6(), nullable=True)
    review_basis_note = Column(Text, nullable=False)
    revoked_at = Column(utc6(), nullable=True)
    revoke_reason = Column(String(1000), nullable=False)
    created_at = Column(utc6(), nullable=False)

    @declared_attr
    def created_by(cls):  # noqa: N805
        return Column(Integer, ForeignKey("hoimsystem_users.user_id"), nullable=False)

    @declared_attr
    def reviewed_by(cls):  # noqa: N805
        return Column(Integer, ForeignKey("hoimsystem_users.user_id"), nullable=True)

    @declared_attr
    def revoked_by(cls):  # noqa: N805
        return Column(Integer, ForeignKey("hoimsystem_users.user_id"), nullable=True)


class ManualAuthorizationReviewColumns:
    authorization_review_status = Column(String(24), nullable=False)
    authorization_reviewed_at = Column(utc6(), nullable=True)
    authorization_review_basis = Column(Text, nullable=False)

    @declared_attr
    def authorization_reviewed_by(cls):  # noqa: N805
        return Column(Integer, ForeignKey("hoimsystem_users.user_id"), nullable=True)


def governance_constraints(prefix):
    return (
        CheckConstraint(
            "(HEX(status)=HEX('draft') AND revision=1 AND reviewed_by IS NULL AND reviewed_at IS NULL AND review_basis_note='' AND revoked_by IS NULL AND revoked_at IS NULL AND revoke_reason='') OR "
            "(HEX(status) IN (HEX('published'),HEX('rejected')) AND revision=2 AND reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL AND review_basis_note<>'' AND revoked_by IS NULL AND revoked_at IS NULL AND revoke_reason='') OR "
            "(HEX(status)=HEX('revoked') AND revoked_by IS NOT NULL AND revoked_at IS NOT NULL AND revoke_reason<>'' AND ((revision=2 AND reviewed_by IS NULL AND reviewed_at IS NULL AND review_basis_note='') OR (revision=3 AND reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL AND review_basis_note<>'')))",
            name="ck_research_" + prefix + "_governance",
        ),
        CheckConstraint(
            "created_by>0 AND (reviewed_at IS NULL OR reviewed_at>=created_at) AND (revoked_at IS NULL OR revoked_at>=created_at) AND (reviewed_at IS NULL OR revoked_at IS NULL OR revoked_at>=reviewed_at)",
            name="ck_research_" + prefix + "_clocks",
        ),
        CheckConstraint((_bytes("review_basis_note") <= BASIS_BYTES) & (_bytes("revoke_reason") <= BASIS_BYTES), name="ck_research_" + prefix + "_basis_bytes"),
        _hash_constraint("content_hash", "ck_research_" + prefix + "_content_hash"),
    )


def manual_review_constraints(prefix):
    return (
        CheckConstraint(
            "(HEX(authorization_review_status)=HEX('unknown') AND authorization_reviewed_by IS NULL AND authorization_reviewed_at IS NULL AND authorization_review_basis='') OR "
            "(HEX(authorization_review_status) IN (HEX('recorded_reviewed'),HEX('not_confirmed')) AND authorization_reviewed_by IS NOT NULL AND authorization_reviewed_by<>created_by AND authorization_reviewed_at IS NOT NULL AND authorization_review_basis<>'')",
            name="ck_research_" + prefix + "_manual_review",
        ),
        CheckConstraint(
            "(authorization_reviewed_at IS NULL OR authorization_reviewed_at>=created_at) AND (reviewed_at IS NULL OR authorization_reviewed_at IS NULL OR reviewed_at>=authorization_reviewed_at)",
            name="ck_research_" + prefix + "_manual_clocks",
        ),
        CheckConstraint(_bytes("authorization_review_basis") <= BASIS_BYTES, name="ck_research_" + prefix + "_manual_bytes"),
    )


class AIResearchWriteGate(Base):
    __tablename__ = "hoimsystem_ai_research_write_gate"
    gate_id = Column(Integer, primary_key=True, autoincrement=False)
    revision = Column(Integer, nullable=False)
    __table_args__ = (CheckConstraint("gate_id=1 AND revision=1", name="ck_research_write_gate"),)


class AIResearchStudyScope(ManualAuthorizationReviewColumns, GovernanceColumns, Base):
    __tablename__ = "hoimsystem_ai_research_study_scope"
    scope_id = Column(String(36), primary_key=True)
    schema_version = Column(String(48), nullable=False)
    scope_json = Column(original_json(), nullable=False)
    parent_binding_json = Column(original_json(), nullable=False)
    content_hash = Column(String(64), nullable=False)
    valid_from = Column(utc6(), nullable=False)
    valid_until = Column(utc6(), nullable=False)
    __table_args__ = (
        *governance_constraints("scope"),
        *manual_review_constraints("scope"),
        CheckConstraint("HEX(schema_version)=HEX('research_study_scope_v1') AND valid_until>valid_from", name="ck_research_scope_identity"),
        _json_constraint("scope_json", SOURCE_BYTES, "ck_research_scope_body"),
        _json_constraint("parent_binding_json", PARENT_BYTES, "ck_research_scope_parent"),
        Index("idx_research_scope_status_clock", "status", "created_at", "scope_id"),
    )


class AIResearchProjectACL(GovernanceColumns, Base):
    __tablename__ = "hoimsystem_ai_research_project_acl"
    acl_id = Column(String(36), primary_key=True)
    scope_id = Column(String(36), ForeignKey("hoimsystem_ai_research_study_scope.scope_id"), nullable=False)
    user_id = Column(Integer, ForeignKey("hoimsystem_users.user_id"), nullable=False)
    schema_version = Column(String(48), nullable=False)
    permission = Column(String(20), nullable=False)
    payload_json = Column(original_json(), nullable=False)
    parent_binding_json = Column(original_json(), nullable=False)
    content_hash = Column(String(64), nullable=False)
    valid_from = Column(utc6(), nullable=False)
    valid_until = Column(utc6(), nullable=False)
    __table_args__ = (
        *governance_constraints("acl"),
        CheckConstraint("HEX(schema_version)=HEX('research_project_acl_v1') AND HEX(permission) IN (HEX('read_only'),HEX('read_capture')) AND valid_until>valid_from", name="ck_research_acl_identity"),
        _json_constraint("payload_json", SOURCE_BYTES, "ck_research_acl_body"),
        _json_constraint("parent_binding_json", PARENT_BYTES, "ck_research_acl_parent"),
        Index("idx_research_acl_scope_user", "scope_id", "user_id", "status", "acl_id"),
    )


class AIResearchPatientAuthorization(ManualAuthorizationReviewColumns, GovernanceColumns, Base):
    __tablename__ = "hoimsystem_ai_research_patient_authorization"
    authorization_id = Column(String(36), primary_key=True)
    scope_id = Column(String(36), ForeignKey("hoimsystem_ai_research_study_scope.scope_id"), nullable=False)
    patient_id = Column(Integer, ForeignKey("hoimsystem_patient.patient_id"), nullable=False)
    schema_version = Column(String(48), nullable=False)
    authorization_kind = Column(String(24), nullable=False)
    access_basis = Column(String(24), nullable=False)
    payload_json = Column(original_json(), nullable=False)
    parent_binding_json = Column(original_json(), nullable=False)
    content_hash = Column(String(64), nullable=False)
    valid_from = Column(utc6(), nullable=True)
    valid_until = Column(utc6(), nullable=True)
    __table_args__ = (
        *governance_constraints("patient_auth"),
        *manual_review_constraints("patient_auth"),
        CheckConstraint(
            "HEX(schema_version)=HEX('research_patient_auth_v1') AND HEX(authorization_kind) IN (HEX('permission_recorded'),HEX('waiver_recorded'),HEX('unknown'),HEX('withdrawn'),HEX('denied')) AND HEX(access_basis) IN (HEX('explicit_project_acl'),HEX('current_care_or_grant'))",
            name="ck_research_patient_auth_identity",
        ),
        CheckConstraint("(valid_from IS NULL AND valid_until IS NULL) OR (valid_from IS NOT NULL AND valid_until IS NOT NULL AND valid_until>valid_from)", name="ck_research_patient_auth_validity"),
        _json_constraint("payload_json", SOURCE_BYTES, "ck_research_patient_auth_body"),
        _json_constraint("parent_binding_json", PARENT_BYTES, "ck_research_patient_auth_parent"),
        Index("idx_research_auth_scope_patient", "scope_id", "patient_id", "status", "authorization_id"),
    )


class AIResearchCohortCase(GovernanceColumns, Base):
    __tablename__ = "hoimsystem_ai_research_cohort_case"
    case_id = Column(String(36), primary_key=True)
    scope_id = Column(String(36), ForeignKey("hoimsystem_ai_research_study_scope.scope_id"), nullable=False)
    schema_version = Column(String(48), nullable=False)
    snapshot_json = Column(original_json(), nullable=False)
    content_hash = Column(String(64), nullable=False)
    collection_digest = Column(String(64), nullable=False)
    scope_binding_hash = Column(String(64), nullable=False)
    member_manifest_hash = Column(String(64), nullable=False)
    projection_json = Column(original_json(), nullable=True)
    projection_hash = Column(String(64), nullable=True)
    __table_args__ = (
        *governance_constraints("case"),
        CheckConstraint("HEX(schema_version)=HEX('research_cohort_case_v1')", name="ck_research_case_identity"),
        _json_constraint("snapshot_json", SNAPSHOT_BYTES, "ck_research_case_snapshot"),
        CheckConstraint(
            (column("projection_json").is_(None) & column("projection_hash").is_(None))
            | (
                column("projection_json").is_not(None)
                & column("projection_hash").is_not(None)
                & (_bytes("projection_json") > 0)
                & (_bytes("projection_json") <= SNAPSHOT_BYTES)
                & (func.json_valid(column("projection_json")) == 1)
            ),
            name="ck_research_case_projection",
        ),
        *(_hash_constraint(name, "ck_research_case_" + name, nullable=name == "projection_hash") for name in ("collection_digest", "scope_binding_hash", "member_manifest_hash", "projection_hash")),
        Index("idx_research_case_scope_status", "scope_id", "status", "created_at", "case_id"),
    )


RESEARCH_COHORT_MODELS = (AIResearchWriteGate, AIResearchStudyScope, AIResearchProjectACL, AIResearchPatientAuthorization, AIResearchCohortCase)
