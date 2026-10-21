"""Release exact drug-label originals with independent pharmacist signatures."""

from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, ForeignKeyConstraint, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects import mysql

from alembic import op

revision = "20261021_drug_label_sources"
down_revision = "20261021_doc_extraction_runs"
branch_labels = None
depends_on = None
MAX_SOURCE_BYTES = 8 * 1024 * 1024


def utc6():
    return DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql")


def medium_text():
    return Text().with_variant(mysql.MEDIUMTEXT(), "mysql")


def sha_constraint(field, prefix, *, nullable=False):
    remainder = field
    for character in "0123456789abcdef":
        remainder = f"replace({remainder}, '{character}', '')"
    sql = f"length({field}) = 64 AND length({remainder}) = 0"
    if nullable:
        sql = f"{field} IS NULL OR ({sql})"
    return CheckConstraint(sql, name=f"ck_drug_label_{prefix}_{field}")


def upgrade():
    op.create_table(
        "hoimsystem_ai_drug_label_source",
        Column("source_binding_id", String(36), primary_key=True),
        Column("pharmaceutical_id", Integer, ForeignKey("hoimsystem_pharmaceutical.pharmaceutical_id"), nullable=False),
        Column("original_id", String(36), nullable=False),
        Column("original_content_hash", String(64), nullable=False),
        Column("original_governance_hash", String(64), nullable=False),
        Column("identity_hash", String(64), nullable=False),
        Column("snapshot_json", medium_text(), nullable=False),
        Column("content_hash", String(64), nullable=False),
        Column("created_by", Integer, ForeignKey("hoimsystem_users.user_id"), nullable=False),
        Column("recorded_at", utc6(), nullable=False),
        Column("status", String(16), nullable=False),
        Column("revision", Integer, nullable=False),
        Column("professional_review_id", String(36), nullable=True),
        Column("professional_content_hash", String(64), nullable=True),
        Column("professional_governance_hash", String(64), nullable=True),
        Column("reviewed_by", Integer, ForeignKey("hoimsystem_users.user_id"), nullable=True),
        Column("reviewed_at", utc6(), nullable=True),
        Column("review_basis_note", Text, nullable=False),
        Column("revoked_by", Integer, ForeignKey("hoimsystem_users.user_id"), nullable=True),
        Column("revoked_at", utc6(), nullable=True),
        Column("revoke_reason", String(1000), nullable=False),
        ForeignKeyConstraint(["original_id", "original_content_hash"], ["hoimsystem_ai_document_original.original_id", "hoimsystem_ai_document_original.content_hash"], name="fk_drug_label_original"),
        UniqueConstraint("source_binding_id", "content_hash", name="uq_drug_label_source_hash"),
        CheckConstraint("pharmaceutical_id > 0 AND created_by > 0", name="ck_drug_label_source_ids"),
        CheckConstraint(f"length(snapshot_json) > 0 AND length(snapshot_json) <= {MAX_SOURCE_BYTES}", name="ck_drug_label_source_storage"),
        CheckConstraint("length(review_basis_note) <= 4000 AND length(revoke_reason) <= 4000", name="ck_drug_label_source_notes"),
        CheckConstraint(
            "(status = 'draft' AND revision = 1 AND reviewed_by IS NULL AND reviewed_at IS NULL AND review_basis_note = '' AND revoked_by IS NULL AND revoked_at IS NULL AND revoke_reason = '') OR (status IN ('published','rejected') AND revision = 2 AND reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL AND review_basis_note <> '' AND revoked_by IS NULL AND revoked_at IS NULL AND revoke_reason = '') OR (status = 'revoked' AND revoked_by IS NOT NULL AND revoked_at IS NOT NULL AND revoke_reason <> '' AND ((revision = 2 AND reviewed_by IS NULL AND reviewed_at IS NULL AND review_basis_note = '') OR (revision = 3 AND reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL AND review_basis_note <> '')))",
            name="ck_drug_label_source_governance",
        ),
        CheckConstraint(
            "(professional_review_id IS NULL AND professional_content_hash IS NULL AND professional_governance_hash IS NULL) OR (professional_review_id IS NOT NULL AND professional_content_hash IS NOT NULL AND professional_governance_hash IS NOT NULL)",
            name="ck_drug_label_source_prof_ref",
        ),
        CheckConstraint("status <> 'published' OR professional_review_id IS NOT NULL", name="ck_drug_label_source_published"),
        CheckConstraint(
            "(reviewed_at IS NULL OR reviewed_at >= recorded_at) AND (revoked_at IS NULL OR revoked_at >= recorded_at) AND (reviewed_at IS NULL OR revoked_at IS NULL OR revoked_at >= reviewed_at)",
            name="ck_drug_label_source_clocks",
        ),
        *(sha_constraint(field, "source") for field in ("original_content_hash", "original_governance_hash", "identity_hash", "content_hash")),
        *(sha_constraint(field, "source", nullable=True) for field in ("professional_content_hash", "professional_governance_hash")),
        Index("idx_drug_label_source_sku", "pharmaceutical_id", "recorded_at", "source_binding_id"),
    )
    op.create_table(
        "hoimsystem_ai_drug_label_professional_review",
        Column("professional_review_id", String(36), primary_key=True),
        Column("source_binding_id", String(36), nullable=False),
        Column("source_content_hash", String(64), nullable=False),
        Column("snapshot_json", Text, nullable=False),
        Column("content_hash", String(64), nullable=False),
        Column("signed_by", Integer, ForeignKey("hoimsystem_users.user_id"), nullable=False),
        Column("signed_at", utc6(), nullable=False),
        Column("status", String(16), nullable=False),
        Column("revision", Integer, nullable=False),
        Column("revoked_by", Integer, ForeignKey("hoimsystem_users.user_id"), nullable=True),
        Column("revoked_at", utc6(), nullable=True),
        Column("revoke_reason", String(1000), nullable=False),
        ForeignKeyConstraint(
            ["source_binding_id", "source_content_hash"], ["hoimsystem_ai_drug_label_source.source_binding_id", "hoimsystem_ai_drug_label_source.content_hash"], name="fk_drug_label_prof_source"
        ),
        UniqueConstraint("source_binding_id", name="uq_drug_label_one_signature"),
        CheckConstraint("signed_by > 0 AND length(snapshot_json) > 0 AND length(snapshot_json) <= 65535", name="ck_drug_label_prof_storage"),
        CheckConstraint("length(revoke_reason) <= 4000", name="ck_drug_label_prof_reason"),
        CheckConstraint(
            "(status = 'signed' AND revision = 1 AND revoked_by IS NULL AND revoked_at IS NULL AND revoke_reason = '') OR (status = 'revoked' AND revision = 2 AND revoked_by IS NOT NULL AND revoked_at IS NOT NULL AND revoked_at >= signed_at AND revoke_reason <> '')",
            name="ck_drug_label_prof_governance",
        ),
        *(sha_constraint(field, "prof") for field in ("source_content_hash", "content_hash")),
        Index("idx_drug_label_prof_signer", "signed_by", "signed_at", "professional_review_id"),
    )


def downgrade():
    op.drop_table("hoimsystem_ai_drug_label_professional_review")
    op.drop_table("hoimsystem_ai_drug_label_source")
