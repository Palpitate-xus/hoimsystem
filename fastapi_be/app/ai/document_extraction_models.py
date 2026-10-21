"""Immutable task anchors keep document extraction identifiable after JSON loss.

Input, evidence and metadata hashes bind the complete persisted Run JSON UTF8
bytes. The response remains in the existing Run TEXT; this table stores no text
copy, model result or mutable governance state and exposes no update/delete API.
"""

from sqlalchemy import CheckConstraint, Column, ForeignKey, Index, Integer, String

from app.ai.document_evidence_models import utc6
from app.database import Base

ANCHOR_SCHEMA = "document_extraction_run_anchor_v1"
ANCHOR_HASH_FIELDS = (
    "original_content_hash",
    "original_governance_hash",
    "source_digest",
    "prompt_hash",
    "context_digest",
    "input_hash",
    "evidence_hash",
    "metadata_hash",
)


def hash_constraint(field):
    """Enforce lowercase hex without dialect-specific regular expressions."""
    remainder = field
    for character in "0123456789abcdef":
        remainder = f"replace({remainder}, '{character}', '')"
    return CheckConstraint(f"length({field}) = 64 AND {remainder} = ''", name=f"ck_doc_extract_{field}")


class AIDocumentExtractionRunAnchor(Base):
    __tablename__ = "hoimsystem_ai_document_extraction_run_anchor"
    __table_args__ = (
        CheckConstraint(f"schema_version = '{ANCHOR_SCHEMA}'", name="ck_doc_extract_schema"),
        CheckConstraint("requested_by > 0", name="ck_doc_extract_actor"),
        *(hash_constraint(field) for field in ANCHOR_HASH_FIELDS),
        Index("idx_doc_extract_original", "original_id", "recorded_at"),
    )

    run_id = Column(String(36), ForeignKey("hoimsystem_ai_run.run_id"), primary_key=True)
    original_id = Column(String(36), ForeignKey("hoimsystem_ai_document_original.original_id"), nullable=False)
    requested_by = Column(Integer, ForeignKey("hoimsystem_users.user_id"), nullable=False)
    schema_version = Column(String(48), nullable=False)
    recorded_at = Column(utc6(), nullable=False)
    original_content_hash = Column(String(64), nullable=False)
    original_governance_hash = Column(String(64), nullable=False)
    source_digest = Column(String(64), nullable=False)
    prompt_hash = Column(String(64), nullable=False)
    context_digest = Column(String(64), nullable=False)
    input_hash = Column(String(64), nullable=False)
    evidence_hash = Column(String(64), nullable=False)
    metadata_hash = Column(String(64), nullable=False)


DOCUMENT_EXTRACTION_MODELS = (AIDocumentExtractionRunAnchor,)
