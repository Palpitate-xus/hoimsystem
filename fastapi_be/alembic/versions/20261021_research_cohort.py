"""Bounded explicitly authorized research originals, independently additive.

Revision ID: 20261021_research_cohort
Revises: 20261021_doc_extraction_runs
"""

from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Integer, LargeBinary, String, Text, cast, column, func
from sqlalchemy.dialects import mysql

from alembic import op

revision = "20261021_research_cohort"
down_revision = "20261021_doc_extraction_runs"
branch_labels = None
depends_on = None

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


def upgrade():
    op.create_table(
        "hoimsystem_ai_research_write_gate",
        Column("gate_id", Integer, primary_key=True, autoincrement=False),
        Column("revision", Integer, nullable=False),
        CheckConstraint("gate_id=1 AND revision=1", name="ck_research_write_gate"),
    )
    op.create_table(
        "hoimsystem_ai_research_study_scope",
        Column("scope_id", String(36), primary_key=True),
        Column("schema_version", String(48), nullable=False),
        Column("scope_json", original_json(), nullable=False),
        Column("parent_binding_json", original_json(), nullable=False),
        Column("content_hash", String(64), nullable=False),
        Column("valid_from", utc6(), nullable=False),
        Column("valid_until", utc6(), nullable=False),
        Column("status", String(16), nullable=False),
        Column("revision", Integer, nullable=False),
        Column("reviewed_at", utc6(), nullable=True),
        Column("review_basis_note", Text, nullable=False),
        Column("revoked_at", utc6(), nullable=True),
        Column("revoke_reason", String(1000), nullable=False),
        Column("created_at", utc6(), nullable=False),
        Column("created_by", Integer, ForeignKey("hoimsystem_users.user_id"), nullable=False),
        Column("reviewed_by", Integer, ForeignKey("hoimsystem_users.user_id"), nullable=True),
        Column("revoked_by", Integer, ForeignKey("hoimsystem_users.user_id"), nullable=True),
        Column("authorization_review_status", String(24), nullable=False),
        Column("authorization_reviewed_at", utc6(), nullable=True),
        Column("authorization_review_basis", Text, nullable=False),
        Column("authorization_reviewed_by", Integer, ForeignKey("hoimsystem_users.user_id"), nullable=True),
        *governance_constraints("scope"),
        *manual_review_constraints("scope"),
        CheckConstraint("HEX(schema_version)=HEX('research_study_scope_v1') AND valid_until>valid_from", name="ck_research_scope_identity"),
        _json_constraint("scope_json", SOURCE_BYTES, "ck_research_scope_body"),
        _json_constraint("parent_binding_json", PARENT_BYTES, "ck_research_scope_parent"),
    )
    op.create_index("idx_research_scope_status_clock", "hoimsystem_ai_research_study_scope", ["status", "created_at", "scope_id"])
    op.create_table(
        "hoimsystem_ai_research_project_acl",
        Column("acl_id", String(36), primary_key=True),
        Column("scope_id", String(36), ForeignKey("hoimsystem_ai_research_study_scope.scope_id"), nullable=False),
        Column("user_id", Integer, ForeignKey("hoimsystem_users.user_id"), nullable=False),
        Column("schema_version", String(48), nullable=False),
        Column("permission", String(20), nullable=False),
        Column("payload_json", original_json(), nullable=False),
        Column("parent_binding_json", original_json(), nullable=False),
        Column("content_hash", String(64), nullable=False),
        Column("valid_from", utc6(), nullable=False),
        Column("valid_until", utc6(), nullable=False),
        Column("status", String(16), nullable=False),
        Column("revision", Integer, nullable=False),
        Column("reviewed_at", utc6(), nullable=True),
        Column("review_basis_note", Text, nullable=False),
        Column("revoked_at", utc6(), nullable=True),
        Column("revoke_reason", String(1000), nullable=False),
        Column("created_at", utc6(), nullable=False),
        Column("created_by", Integer, ForeignKey("hoimsystem_users.user_id"), nullable=False),
        Column("reviewed_by", Integer, ForeignKey("hoimsystem_users.user_id"), nullable=True),
        Column("revoked_by", Integer, ForeignKey("hoimsystem_users.user_id"), nullable=True),
        *governance_constraints("acl"),
        CheckConstraint("HEX(schema_version)=HEX('research_project_acl_v1') AND HEX(permission) IN (HEX('read_only'),HEX('read_capture')) AND valid_until>valid_from", name="ck_research_acl_identity"),
        _json_constraint("payload_json", SOURCE_BYTES, "ck_research_acl_body"),
        _json_constraint("parent_binding_json", PARENT_BYTES, "ck_research_acl_parent"),
    )
    op.create_index("idx_research_acl_scope_user", "hoimsystem_ai_research_project_acl", ["scope_id", "user_id", "status", "acl_id"])
    op.create_table(
        "hoimsystem_ai_research_patient_authorization",
        Column("authorization_id", String(36), primary_key=True),
        Column("scope_id", String(36), ForeignKey("hoimsystem_ai_research_study_scope.scope_id"), nullable=False),
        Column("patient_id", Integer, ForeignKey("hoimsystem_patient.patient_id"), nullable=False),
        Column("schema_version", String(48), nullable=False),
        Column("authorization_kind", String(24), nullable=False),
        Column("access_basis", String(24), nullable=False),
        Column("payload_json", original_json(), nullable=False),
        Column("parent_binding_json", original_json(), nullable=False),
        Column("content_hash", String(64), nullable=False),
        Column("valid_from", utc6(), nullable=True),
        Column("valid_until", utc6(), nullable=True),
        Column("status", String(16), nullable=False),
        Column("revision", Integer, nullable=False),
        Column("reviewed_at", utc6(), nullable=True),
        Column("review_basis_note", Text, nullable=False),
        Column("revoked_at", utc6(), nullable=True),
        Column("revoke_reason", String(1000), nullable=False),
        Column("created_at", utc6(), nullable=False),
        Column("created_by", Integer, ForeignKey("hoimsystem_users.user_id"), nullable=False),
        Column("reviewed_by", Integer, ForeignKey("hoimsystem_users.user_id"), nullable=True),
        Column("revoked_by", Integer, ForeignKey("hoimsystem_users.user_id"), nullable=True),
        Column("authorization_review_status", String(24), nullable=False),
        Column("authorization_reviewed_at", utc6(), nullable=True),
        Column("authorization_review_basis", Text, nullable=False),
        Column("authorization_reviewed_by", Integer, ForeignKey("hoimsystem_users.user_id"), nullable=True),
        *governance_constraints("patient_auth"),
        *manual_review_constraints("patient_auth"),
        CheckConstraint(
            "HEX(schema_version)=HEX('research_patient_auth_v1') AND HEX(authorization_kind) IN (HEX('permission_recorded'),HEX('waiver_recorded'),HEX('unknown'),HEX('withdrawn'),HEX('denied')) AND HEX(access_basis) IN (HEX('explicit_project_acl'),HEX('current_care_or_grant'))",
            name="ck_research_patient_auth_identity",
        ),
        CheckConstraint("(valid_from IS NULL AND valid_until IS NULL) OR (valid_from IS NOT NULL AND valid_until IS NOT NULL AND valid_until>valid_from)", name="ck_research_patient_auth_validity"),
        _json_constraint("payload_json", SOURCE_BYTES, "ck_research_patient_auth_body"),
        _json_constraint("parent_binding_json", PARENT_BYTES, "ck_research_patient_auth_parent"),
    )
    op.create_index("idx_research_auth_scope_patient", "hoimsystem_ai_research_patient_authorization", ["scope_id", "patient_id", "status", "authorization_id"])
    op.create_table(
        "hoimsystem_ai_research_cohort_case",
        Column("case_id", String(36), primary_key=True),
        Column("scope_id", String(36), ForeignKey("hoimsystem_ai_research_study_scope.scope_id"), nullable=False),
        Column("schema_version", String(48), nullable=False),
        Column("snapshot_json", original_json(), nullable=False),
        Column("content_hash", String(64), nullable=False),
        Column("collection_digest", String(64), nullable=False),
        Column("scope_binding_hash", String(64), nullable=False),
        Column("member_manifest_hash", String(64), nullable=False),
        Column("projection_json", original_json(), nullable=True),
        Column("projection_hash", String(64), nullable=True),
        Column("status", String(16), nullable=False),
        Column("revision", Integer, nullable=False),
        Column("reviewed_at", utc6(), nullable=True),
        Column("review_basis_note", Text, nullable=False),
        Column("revoked_at", utc6(), nullable=True),
        Column("revoke_reason", String(1000), nullable=False),
        Column("created_at", utc6(), nullable=False),
        Column("created_by", Integer, ForeignKey("hoimsystem_users.user_id"), nullable=False),
        Column("reviewed_by", Integer, ForeignKey("hoimsystem_users.user_id"), nullable=True),
        Column("revoked_by", Integer, ForeignKey("hoimsystem_users.user_id"), nullable=True),
        *governance_constraints("case"),
        CheckConstraint("HEX(schema_version)=HEX('research_cohort_case_v1')", name="ck_research_case_identity"),
        _json_constraint("snapshot_json", SNAPSHOT_BYTES, "ck_research_case_snapshot"),
        CheckConstraint(
            column("projection_json").is_(None) & column("projection_hash").is_(None)
            | column("projection_json").is_not(None)
            & column("projection_hash").is_not(None)
            & (_bytes("projection_json") > 0)
            & (_bytes("projection_json") <= SNAPSHOT_BYTES)
            & (func.json_valid(column("projection_json")) == 1),
            name="ck_research_case_projection",
        ),
        *(_hash_constraint(name, "ck_research_case_" + name, nullable=name == "projection_hash") for name in ("collection_digest", "scope_binding_hash", "member_manifest_hash", "projection_hash")),
    )
    op.create_index("idx_research_case_scope_status", "hoimsystem_ai_research_cohort_case", ["scope_id", "status", "created_at", "case_id"])


def downgrade():
    op.drop_table("hoimsystem_ai_research_cohort_case")
    op.drop_table("hoimsystem_ai_research_patient_authorization")
    op.drop_table("hoimsystem_ai_research_project_acl")
    op.drop_table("hoimsystem_ai_research_study_scope")
    op.drop_table("hoimsystem_ai_research_write_gate")
