"""Additive task artifacts and complete results; no large body enters AIRun TEXT."""

from sqlalchemy import CheckConstraint, Column, ForeignKey, ForeignKeyConstraint, Index, Integer, String, Text, UniqueConstraint

from app.ai.document_change_contract import MAX_CASE_BYTES, MAX_MEMBERS
from app.ai.document_evidence_models import medium_text, utc6
from app.database import Base

ARTIFACT_SCHEMA = "document_change_run_artifact_v1"
ANCHOR_HASH_FIELDS = ("prompt_hash", "context_digest", "input_hash", "evidence_hash", "metadata_hash")
SOURCE_HASH_FIELDS = (
    "scope_content_hash",
    "scope_governance_hash",
    "baseline_original_content_hash",
    "baseline_original_governance_hash",
    "candidate_original_content_hash",
    "candidate_original_governance_hash",
    "inventory_hash",
    "source_digest",
)


def hash_constraint(field, prefix):
    remainder = field
    for character in "0123456789abcdef":
        remainder = f"replace({remainder}, '{character}', '')"
    return CheckConstraint(f"length({field}) = 64 AND length({remainder}) = 0", name=f"ck_dcr_{prefix}_{field}")


class AIDocumentChangeRunArtifact(Base):
    __tablename__ = "hoimsystem_ai_document_change_run_artifact"
    __table_args__ = (
        CheckConstraint(f"schema_version = '{ARTIFACT_SCHEMA}'", name="ck_dcr_artifact_schema"),
        CheckConstraint("requested_by > 0", name="ck_dcr_artifact_actor"),
        CheckConstraint(f"member_count >= 2 AND member_count <= {MAX_MEMBERS}", name="ck_dcr_artifact_members"),
        CheckConstraint(f"source_bytes > 0 AND source_bytes <= {MAX_CASE_BYTES} AND length(source_json) > 0 AND length(source_json) <= {MAX_CASE_BYTES}", name="ck_dcr_artifact_source"),
        CheckConstraint("length(scope_governance_json) > 0 AND length(scope_governance_json) <= 65535", name="ck_dcr_artifact_review"),
        CheckConstraint(
            "created_audit_event_id > 0 AND scope_created_audit_event_id > 0 AND scope_review_audit_event_id > 0 AND (usage_event_id IS NULL OR usage_event_id > 0)", name="ck_dcr_artifact_audits"
        ),
        UniqueConstraint("usage_event_id", name="uq_dcr_usage_event"),
        ForeignKeyConstraint(
            ["baseline_original_id", "baseline_original_content_hash"],
            ["hoimsystem_ai_document_original.original_id", "hoimsystem_ai_document_original.content_hash"],
            name="fk_dcr_artifact_baseline",
        ),
        ForeignKeyConstraint(
            ["candidate_original_id", "candidate_original_content_hash"],
            ["hoimsystem_ai_document_original.original_id", "hoimsystem_ai_document_original.content_hash"],
            name="fk_dcr_artifact_candidate",
        ),
        CheckConstraint("baseline_original_id <> candidate_original_id", name="ck_dcr_artifact_two_originals"),
        *(hash_constraint(field, "a") for field in (*SOURCE_HASH_FIELDS, *ANCHOR_HASH_FIELDS)),
        Index("idx_dcr_artifact_scope", "scope_id", "recorded_at"),
    )
    run_id = Column(String(36), ForeignKey("hoimsystem_ai_run.run_id"), primary_key=True)
    scope_id = Column(String(36), ForeignKey("hoimsystem_ai_document_change_scope.scope_id"), nullable=False)
    requested_by = Column(Integer, ForeignKey("hoimsystem_users.user_id"), nullable=False)
    schema_version = Column(String(48), nullable=False)
    recorded_at = Column(utc6(), nullable=False)
    scope_content_hash = Column(String(64), nullable=False)
    scope_governance_hash = Column(String(64), nullable=False)
    baseline_original_id = Column(String(36), nullable=False)
    baseline_original_content_hash = Column(String(64), nullable=False)
    baseline_original_governance_hash = Column(String(64), nullable=False)
    candidate_original_id = Column(String(36), nullable=False)
    candidate_original_content_hash = Column(String(64), nullable=False)
    candidate_original_governance_hash = Column(String(64), nullable=False)
    inventory_hash = Column(String(64), nullable=False)
    member_count = Column(Integer, nullable=False)
    source_digest = Column(String(64), nullable=False)
    source_bytes = Column(Integer, nullable=False)
    source_json = Column(medium_text(), nullable=False)
    scope_governance_json = Column(Text, nullable=False)
    prompt_hash = Column(String(64), nullable=False)
    context_digest = Column(String(64), nullable=False)
    input_hash = Column(String(64), nullable=False)
    evidence_hash = Column(String(64), nullable=False)
    metadata_hash = Column(String(64), nullable=False)
    scope_created_audit_event_id = Column(Integer, ForeignKey("hoimsystem_ai_audit_event.event_id"), nullable=False)
    scope_review_audit_event_id = Column(Integer, ForeignKey("hoimsystem_ai_audit_event.event_id"), nullable=False)
    created_audit_event_id = Column(Integer, ForeignKey("hoimsystem_ai_audit_event.event_id"), nullable=False)
    # A specific terminal receipt PK, never an audit-range query or fake zero.
    # It is set once, in the same lease-bound transaction as the terminal Run.
    usage_event_id = Column(Integer, ForeignKey("hoimsystem_ai_audit_event.event_id"), nullable=True)


class AIDocumentChangeRunResult(Base):
    __tablename__ = "hoimsystem_ai_document_change_run_result"
    __table_args__ = (
        CheckConstraint("schema_version = 'document_change_run_result_v1'", name="ck_dcr_result_schema"),
        CheckConstraint(f"result_bytes > 0 AND result_bytes <= {MAX_CASE_BYTES} AND length(result_json) > 0 AND length(result_json) <= {MAX_CASE_BYTES}", name="ck_dcr_result_bytes"),
        CheckConstraint("accept_audit_event_id > 0", name="ck_dcr_result_audit"),
        UniqueConstraint("accept_audit_event_id", name="uq_dcr_result_accept_audit"),
        *(hash_constraint(field, "r") for field in ("content_hash", "source_binding_hash")),
    )
    run_id = Column(String(36), ForeignKey("hoimsystem_ai_document_change_run_artifact.run_id"), primary_key=True)
    scope_id = Column(String(36), ForeignKey("hoimsystem_ai_document_change_scope.scope_id"), nullable=False)
    schema_version = Column(String(48), nullable=False)
    lease_token = Column(String(36), nullable=False)
    content_hash = Column(String(64), nullable=False)
    result_bytes = Column(Integer, nullable=False)
    result_json = Column(medium_text(), nullable=False)
    source_binding_hash = Column(String(64), nullable=False)
    accepted_at = Column(utc6(), nullable=False)
    accept_audit_event_id = Column(Integer, ForeignKey("hoimsystem_ai_audit_event.event_id"), nullable=False)


DOCUMENT_CHANGE_RUN_MODELS = (AIDocumentChangeRunArtifact, AIDocumentChangeRunResult)
