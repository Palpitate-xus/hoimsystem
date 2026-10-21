"""Add purpose grants and whole immutable RCA investigation sources."""

import sqlalchemy as sa
from sqlalchemy.dialects import mysql

from alembic import op

revision = "20261021_rca_evidence"
down_revision = "20261021_native_shared_merge"
branch_labels = None
depends_on = None


def utc6():
    return sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql")


def whole_json():
    return sa.Text().with_variant(mysql.MEDIUMTEXT(), "mysql")


def review_constraints(prefix):
    return (
        sa.CheckConstraint(
            "privacy_review IN ('unknown','confirmed','not_confirmed') AND faithfulness_review IN ('unknown','confirmed','not_confirmed') AND provenance_review IN ('unknown','confirmed','not_confirmed')",
            name=f"ck_rca_{prefix}_reviews",
        ),
        sa.CheckConstraint(
            "(status = 'draft' AND revision = 1 AND reviewed_by IS NULL AND reviewed_at IS NULL AND reviewed_audit_event_id IS NULL AND review_basis_note = '' AND privacy_review = 'unknown' AND faithfulness_review = 'unknown' AND provenance_review = 'unknown' AND revoked_by IS NULL AND revoked_at IS NULL AND revoked_audit_event_id IS NULL AND revoke_reason = '') OR (status IN ('published','rejected') AND revision = 2 AND reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL AND reviewed_audit_event_id IS NOT NULL AND review_basis_note <> '' AND revoked_by IS NULL AND revoked_at IS NULL AND revoked_audit_event_id IS NULL AND revoke_reason = '') OR (status = 'revoked' AND revoked_by IS NOT NULL AND revoked_at IS NOT NULL AND revoked_audit_event_id IS NOT NULL AND revoke_reason <> '' AND ((revision = 2 AND reviewed_by IS NULL AND reviewed_at IS NULL AND reviewed_audit_event_id IS NULL AND review_basis_note = '' AND privacy_review = 'unknown' AND faithfulness_review = 'unknown' AND provenance_review = 'unknown') OR (revision = 3 AND reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL AND reviewed_audit_event_id IS NOT NULL AND review_basis_note <> '')))",
            name=f"ck_rca_{prefix}_governance",
        ),
        sa.CheckConstraint("status <> 'published' OR (privacy_review = 'confirmed' AND faithfulness_review = 'confirmed' AND provenance_review = 'confirmed')", name=f"ck_rca_{prefix}_publication"),
        sa.CheckConstraint("status <> 'rejected' OR privacy_review <> 'confirmed' OR faithfulness_review <> 'confirmed' OR provenance_review <> 'confirmed'", name=f"ck_rca_{prefix}_rejection"),
        sa.CheckConstraint(
            "(reviewed_at IS NULL OR reviewed_at >= recorded_at) AND (revoked_at IS NULL OR revoked_at >= recorded_at) AND (reviewed_at IS NULL OR revoked_at IS NULL OR revoked_at >= reviewed_at)",
            name=f"ck_rca_{prefix}_clocks",
        ),
        sa.CheckConstraint("json_bytes > 0 AND json_bytes <= 8388608", name=f"ck_rca_{prefix}_json_bytes"),
    )


def upgrade():
    op.create_table(
        "hoimsystem_ai_rca_purpose_grant",
        sa.Column("grant_id", sa.String(36), primary_key=True),
        sa.Column("event_id", sa.Integer, sa.ForeignKey("hoimsystem_adverse_event.event_id"), nullable=False),
        sa.Column("patient_id_at_grant", sa.Integer, sa.ForeignKey("hoimsystem_patient.patient_id"), nullable=True),
        sa.Column("grantee_id", sa.Integer, sa.ForeignKey("hoimsystem_users.user_id"), nullable=False),
        sa.Column("permission_kind", sa.String(40), nullable=False),
        sa.Column("purpose", sa.String(32), nullable=False),
        sa.Column("grant_json", sa.Text, nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("issued_by", sa.Integer, sa.ForeignKey("hoimsystem_users.user_id"), nullable=False),
        sa.Column("issued_at", utc6(), nullable=False),
        sa.Column("valid_until", utc6(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("revision", sa.Integer, nullable=False),
        sa.Column("revoked_by", sa.Integer, sa.ForeignKey("hoimsystem_users.user_id"), nullable=True),
        sa.Column("revoked_at", utc6(), nullable=True),
        sa.Column("revoke_reason", sa.String(1000), nullable=False),
        sa.Column("created_audit_event_id", sa.Integer, sa.ForeignKey("hoimsystem_ai_audit_event.event_id"), nullable=False, unique=True),
        sa.Column("revoked_audit_event_id", sa.Integer, sa.ForeignKey("hoimsystem_ai_audit_event.event_id"), nullable=True, unique=True),
        sa.CheckConstraint("purpose = 'incident_rca' AND permission_kind IN ('event_investigation','associated_patient_processing')", name="ck_rca_grant_purpose"),
        sa.CheckConstraint("permission_kind <> 'associated_patient_processing' OR patient_id_at_grant IS NOT NULL", name="ck_rca_grant_patient_scope"),
        sa.CheckConstraint("valid_until > issued_at AND length(grant_json) > 0 AND length(grant_json) <= 65535", name="ck_rca_grant_boundaries"),
        sa.CheckConstraint(
            "(status = 'active' AND revision = 1 AND revoked_by IS NULL AND revoked_at IS NULL AND revoke_reason = '' AND revoked_audit_event_id IS NULL) OR (status = 'revoked' AND revision = 2 AND revoked_by IS NOT NULL AND revoked_at IS NOT NULL AND revoked_at >= issued_at AND revoke_reason <> '' AND revoked_audit_event_id IS NOT NULL)",
            name="ck_rca_grant_governance",
        ),
        sa.UniqueConstraint("grant_id", "content_hash", name="uq_rca_grant_content"),
        sa.UniqueConstraint("grant_id", "event_id", "grantee_id", name="uq_rca_grant_scope_owner"),
    )
    op.create_table(
        "hoimsystem_ai_rca_evidence_original",
        sa.Column("original_id", sa.String(36), primary_key=True),
        sa.Column("event_id", sa.Integer, sa.ForeignKey("hoimsystem_adverse_event.event_id"), nullable=False),
        sa.Column("patient_id_at_capture", sa.Integer, sa.ForeignKey("hoimsystem_patient.patient_id"), nullable=True),
        sa.Column("legacy_rca_id", sa.Integer, sa.ForeignKey("hoimsystem_adverse_event_rca.rca_id"), nullable=True),
        sa.Column("origin_kind", sa.String(32), nullable=False),
        sa.Column("original_json", whole_json(), nullable=False),
        sa.Column("json_bytes", sa.Integer, nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("created_by", sa.Integer, sa.ForeignKey("hoimsystem_users.user_id"), nullable=False),
        sa.Column("recorded_at", utc6(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("revision", sa.Integer, nullable=False),
        sa.Column("privacy_review", sa.String(20), nullable=False),
        sa.Column("faithfulness_review", sa.String(20), nullable=False),
        sa.Column("provenance_review", sa.String(20), nullable=False),
        sa.Column("reviewed_at", utc6(), nullable=True),
        sa.Column("review_basis_note", sa.String(1000), nullable=False),
        sa.Column("revoked_at", utc6(), nullable=True),
        sa.Column("revoke_reason", sa.String(1000), nullable=False),
        sa.Column("reviewed_by", sa.Integer, sa.ForeignKey("hoimsystem_users.user_id"), nullable=True),
        sa.Column("revoked_by", sa.Integer, sa.ForeignKey("hoimsystem_users.user_id"), nullable=True),
        sa.Column("created_audit_event_id", sa.Integer, sa.ForeignKey("hoimsystem_ai_audit_event.event_id"), nullable=False, unique=True),
        sa.Column("reviewed_audit_event_id", sa.Integer, sa.ForeignKey("hoimsystem_ai_audit_event.event_id"), nullable=True, unique=True),
        sa.Column("revoked_audit_event_id", sa.Integer, sa.ForeignKey("hoimsystem_ai_audit_event.event_id"), nullable=True, unique=True),
        *review_constraints("original"),
        sa.UniqueConstraint("original_id", "content_hash", name="uq_rca_original_content"),
        sa.CheckConstraint("origin_kind IN ('legacy_event','legacy_rca','manual_evidence','human_timeline')", name="ck_rca_original_origin"),
        sa.CheckConstraint("(origin_kind = 'legacy_rca' AND legacy_rca_id IS NOT NULL) OR (origin_kind <> 'legacy_rca' AND legacy_rca_id IS NULL)", name="ck_rca_original_legacy_ref"),
    )
    op.create_table(
        "hoimsystem_ai_rca_evidence_case",
        sa.Column("case_id", sa.String(36), primary_key=True),
        sa.Column("event_id", sa.Integer, sa.ForeignKey("hoimsystem_adverse_event.event_id"), nullable=False),
        sa.Column("patient_id_at_capture", sa.Integer, sa.ForeignKey("hoimsystem_patient.patient_id"), nullable=True),
        sa.Column("event_grant_id", sa.String(36), sa.ForeignKey("hoimsystem_ai_rca_purpose_grant.grant_id"), nullable=False),
        sa.Column("patient_grant_id", sa.String(36), sa.ForeignKey("hoimsystem_ai_rca_purpose_grant.grant_id"), nullable=True),
        sa.Column("case_json", whole_json(), nullable=False),
        sa.Column("json_bytes", sa.Integer, nullable=False),
        sa.Column("member_count", sa.Integer, nullable=False),
        sa.Column("collection_hash", sa.String(64), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("created_by", sa.Integer, sa.ForeignKey("hoimsystem_users.user_id"), nullable=False),
        sa.Column("recorded_at", utc6(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("revision", sa.Integer, nullable=False),
        sa.Column("privacy_review", sa.String(20), nullable=False),
        sa.Column("faithfulness_review", sa.String(20), nullable=False),
        sa.Column("provenance_review", sa.String(20), nullable=False),
        sa.Column("reviewed_at", utc6(), nullable=True),
        sa.Column("review_basis_note", sa.String(1000), nullable=False),
        sa.Column("revoked_at", utc6(), nullable=True),
        sa.Column("revoke_reason", sa.String(1000), nullable=False),
        sa.Column("reviewed_by", sa.Integer, sa.ForeignKey("hoimsystem_users.user_id"), nullable=True),
        sa.Column("revoked_by", sa.Integer, sa.ForeignKey("hoimsystem_users.user_id"), nullable=True),
        sa.Column("created_audit_event_id", sa.Integer, sa.ForeignKey("hoimsystem_ai_audit_event.event_id"), nullable=False, unique=True),
        sa.Column("reviewed_audit_event_id", sa.Integer, sa.ForeignKey("hoimsystem_ai_audit_event.event_id"), nullable=True, unique=True),
        sa.Column("revoked_audit_event_id", sa.Integer, sa.ForeignKey("hoimsystem_ai_audit_event.event_id"), nullable=True, unique=True),
        *review_constraints("case"),
        sa.UniqueConstraint("case_id", "content_hash", name="uq_rca_case_content"),
        sa.ForeignKeyConstraint(
            ["event_grant_id", "event_id", "created_by"],
            ["hoimsystem_ai_rca_purpose_grant.grant_id", "hoimsystem_ai_rca_purpose_grant.event_id", "hoimsystem_ai_rca_purpose_grant.grantee_id"],
            name="fk_rca_case_event_grantee",
        ),
        sa.ForeignKeyConstraint(
            ["patient_grant_id", "event_id", "created_by"],
            ["hoimsystem_ai_rca_purpose_grant.grant_id", "hoimsystem_ai_rca_purpose_grant.event_id", "hoimsystem_ai_rca_purpose_grant.grantee_id"],
            name="fk_rca_case_patient_grantee",
        ),
        sa.CheckConstraint(
            "(patient_id_at_capture IS NULL AND patient_grant_id IS NULL) OR (patient_id_at_capture IS NOT NULL AND patient_grant_id IS NOT NULL AND patient_grant_id <> event_grant_id)",
            name="ck_rca_case_patient_purpose",
        ),
        sa.CheckConstraint("member_count >= 1 AND member_count <= 4096", name="ck_rca_case_members"),
    )
    op.create_index("idx_rca_grant_current_scope", "hoimsystem_ai_rca_purpose_grant", ["event_id", "grantee_id", "permission_kind", "status"])
    op.create_index("idx_rca_original_event", "hoimsystem_ai_rca_evidence_original", ["event_id", "recorded_at", "original_id"])
    op.create_index("idx_rca_case_event", "hoimsystem_ai_rca_evidence_case", ["event_id", "recorded_at", "case_id"])


def downgrade():
    op.drop_index("idx_rca_case_event", table_name="hoimsystem_ai_rca_evidence_case")
    op.drop_table("hoimsystem_ai_rca_evidence_case")
    op.drop_index("idx_rca_original_event", table_name="hoimsystem_ai_rca_evidence_original")
    op.drop_table("hoimsystem_ai_rca_evidence_original")
    op.drop_index("idx_rca_grant_current_scope", table_name="hoimsystem_ai_rca_purpose_grant")
    op.drop_table("hoimsystem_ai_rca_purpose_grant")
