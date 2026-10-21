"""Additive SKU-to-original releases and independent pharmacist signatures."""

from sqlalchemy import CheckConstraint, Column, ForeignKey, ForeignKeyConstraint, Index, Integer, String, Text, UniqueConstraint

from app.ai.document_evidence_models import medium_text, utc6
from app.database import Base

MAX_SOURCE_BYTES = 8 * 1024 * 1024


def sha_constraint(field, prefix, *, nullable=False):
    remainder = field
    for character in "0123456789abcdef":
        remainder = f"replace({remainder}, '{character}', '')"
    sql = f"length({field}) = 64 AND length({remainder}) = 0"
    if nullable:
        sql = f"{field} IS NULL OR ({sql})"
    return CheckConstraint(sql, name=f"ck_drug_label_{prefix}_{field}")


class AIDrugLabelSource(Base):
    __tablename__ = "hoimsystem_ai_drug_label_source"
    __table_args__ = (
        ForeignKeyConstraint(["original_id", "original_content_hash"], ["hoimsystem_ai_document_original.original_id", "hoimsystem_ai_document_original.content_hash"], name="fk_drug_label_original"),
        UniqueConstraint("source_binding_id", "content_hash", name="uq_drug_label_source_hash"),
        CheckConstraint("pharmaceutical_id > 0 AND created_by > 0", name="ck_drug_label_source_ids"),
        CheckConstraint(f"length(snapshot_json) > 0 AND length(snapshot_json) <= {MAX_SOURCE_BYTES}", name="ck_drug_label_source_storage"),
        CheckConstraint("length(review_basis_note) <= 4000 AND length(revoke_reason) <= 4000", name="ck_drug_label_source_notes"),
        CheckConstraint(
            "(status = 'draft' AND revision = 1 AND reviewed_by IS NULL AND reviewed_at IS NULL AND review_basis_note = '' AND revoked_by IS NULL AND revoked_at IS NULL AND revoke_reason = '') OR "
            "(status IN ('published','rejected') AND revision = 2 AND reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL AND review_basis_note <> '' AND revoked_by IS NULL AND revoked_at IS NULL AND revoke_reason = '') OR "
            "(status = 'revoked' AND revoked_by IS NOT NULL AND revoked_at IS NOT NULL AND revoke_reason <> '' AND ((revision = 2 AND reviewed_by IS NULL AND reviewed_at IS NULL AND review_basis_note = '') OR (revision = 3 AND reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL AND review_basis_note <> '')))",
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
    source_binding_id = Column(String(36), primary_key=True)
    pharmaceutical_id = Column(Integer, ForeignKey("hoimsystem_pharmaceutical.pharmaceutical_id"), nullable=False)
    original_id = Column(String(36), nullable=False)
    original_content_hash = Column(String(64), nullable=False)
    original_governance_hash = Column(String(64), nullable=False)
    identity_hash = Column(String(64), nullable=False)
    snapshot_json = Column(medium_text(), nullable=False)
    content_hash = Column(String(64), nullable=False)
    created_by = Column(Integer, ForeignKey("hoimsystem_users.user_id"), nullable=False)
    recorded_at = Column(utc6(), nullable=False)
    status = Column(String(16), nullable=False)
    revision = Column(Integer, nullable=False)
    professional_review_id = Column(String(36), nullable=True)
    professional_content_hash = Column(String(64), nullable=True)
    professional_governance_hash = Column(String(64), nullable=True)
    reviewed_by = Column(Integer, ForeignKey("hoimsystem_users.user_id"), nullable=True)
    reviewed_at = Column(utc6(), nullable=True)
    review_basis_note = Column(Text, nullable=False)
    revoked_by = Column(Integer, ForeignKey("hoimsystem_users.user_id"), nullable=True)
    revoked_at = Column(utc6(), nullable=True)
    revoke_reason = Column(String(1000), nullable=False)


class AIDrugLabelProfessionalReview(Base):
    __tablename__ = "hoimsystem_ai_drug_label_professional_review"
    __table_args__ = (
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
    professional_review_id = Column(String(36), primary_key=True)
    source_binding_id = Column(String(36), nullable=False)
    source_content_hash = Column(String(64), nullable=False)
    snapshot_json = Column(Text, nullable=False)
    content_hash = Column(String(64), nullable=False)
    signed_by = Column(Integer, ForeignKey("hoimsystem_users.user_id"), nullable=False)
    signed_at = Column(utc6(), nullable=False)
    status = Column(String(16), nullable=False)
    revision = Column(Integer, nullable=False)
    revoked_by = Column(Integer, ForeignKey("hoimsystem_users.user_id"), nullable=True)
    revoked_at = Column(utc6(), nullable=True)
    revoke_reason = Column(String(1000), nullable=False)


DRUG_LABEL_MODELS = (AIDrugLabelSource, AIDrugLabelProfessionalReview)
