"""Additive operations task artifacts; actual authority and receipts are runtime proofs."""

from sqlalchemy import CheckConstraint, Column, ForeignKey, ForeignKeyConstraint, Index, Integer, LargeBinary, String, UniqueConstraint, cast, column, func

from app.ai.operations_support_models import byte_bounds, medium_text, utc6
from app.database import Base

ARTIFACT_SCHEMA = "operations_support_artifact_v1"
RESULT_SCHEMA = "operations_support_result_v1"
FRAME_BYTES = 262144
WHOLE_BYTES = 8388608
ARTIFACT_HASHES = (
    "case_private_hash",
    "case_public_hash",
    "case_membership_hash",
    "source_binding_hash",
    "source_projection_hash",
    "prompt_snapshot_hash",
    "execution_snapshot_hash",
    "instructions_digest",
    "input_hash",
    "evidence_hash",
    "metadata_hash",
    "run_header_hash",
)
AUDIT_FIELDS = ("created_audit_event_id", "claim_event_id", "dispatch_event_id", "usage_event_id")


class AIOperationsRunArtifact(Base):
    __tablename__ = "hoimsystem_ai_operations_run_artifact"
    run_id = Column(String(36), ForeignKey("hoimsystem_ai_run.run_id"), primary_key=True)
    schema_version = Column(String(48), nullable=False)
    case_id = Column(String(36), nullable=False)
    case_requested_by = Column(Integer, nullable=False)
    case_private_hash = Column(String(64), nullable=False)
    case_public_hash = Column(String(64), nullable=False)
    case_membership_hash = Column(String(64), nullable=False)
    requested_by = Column(Integer, ForeignKey("hoimsystem_users.user_id"), nullable=False)
    actor_token_invalid_before = Column(utc6(), nullable=True)
    recorded_at = Column(utc6(), nullable=False)
    objective = Column(String(40), nullable=False)
    source_binding_hash = Column(String(64), nullable=False)
    source_json = Column(medium_text(), nullable=False)
    source_bytes = Column(Integer, nullable=False)
    source_projection_hash = Column(String(64), nullable=False)
    prompt_id = Column(String(36), ForeignKey("hoimsystem_ai_prompt_version.prompt_id"), nullable=True)
    prompt_version = Column(Integer, nullable=False)
    prompt_snapshot_json = Column(medium_text(), nullable=False)
    prompt_snapshot_hash = Column(String(64), nullable=False)
    provider_id = Column(Integer, ForeignKey("hoimsystem_ai_provider.provider_id"), nullable=False)
    provider_revision = Column(Integer, nullable=False)
    config_revision = Column(Integer, nullable=False)
    execution_snapshot_json = Column(medium_text(), nullable=False)
    execution_snapshot_hash = Column(String(64), nullable=False)
    instructions_digest = Column(String(64), nullable=False)
    input_hash = Column(String(64), nullable=False)
    evidence_hash = Column(String(64), nullable=False)
    metadata_hash = Column(String(64), nullable=False)
    run_header_hash = Column(String(64), nullable=False)
    created_audit_event_id = Column(Integer, ForeignKey("hoimsystem_ai_audit_event.event_id"), nullable=False, unique=True)
    claim_event_id = Column(Integer, ForeignKey("hoimsystem_ai_audit_event.event_id"), nullable=True, unique=True)
    dispatch_event_id = Column(Integer, ForeignKey("hoimsystem_ai_audit_event.event_id"), nullable=True, unique=True)
    usage_event_id = Column(Integer, ForeignKey("hoimsystem_ai_audit_event.event_id"), nullable=True, unique=True)
    __table_args__ = (
        ForeignKeyConstraint(
            ["case_id", "case_private_hash", "case_public_hash", "case_requested_by"],
            ["hoimsystem_ai_operations_case.case_id", "hoimsystem_ai_operations_case.private_hash", "hoimsystem_ai_operations_case.public_hash", "hoimsystem_ai_operations_case.requested_by"],
            name="fk_ops_run_case",
        ),
        UniqueConstraint("run_id", "source_binding_hash", "instructions_digest", name="uq_ops_run_result_binding"),
        CheckConstraint(f"HEX(schema_version)=HEX('{ARTIFACT_SCHEMA}')", name="ck_ops_run_schema"),
        CheckConstraint("objective IN ('explain_observations','prepare_reviewed_checks','compare_declared_versions')", name="ck_ops_run_objective"),
        CheckConstraint("requested_by>0 AND case_requested_by>0 AND provider_revision>0 AND config_revision>0 AND prompt_version>=0", name="ck_ops_run_positive"),
        CheckConstraint("(prompt_id IS NULL AND prompt_version=0) OR (prompt_id IS NOT NULL AND prompt_version>0)", name="ck_ops_run_prompt_origin"),
        CheckConstraint("source_bytes>0 AND source_bytes<=8388608", name="ck_ops_run_source_bytes"),
        CheckConstraint(column("source_projection_hash") == column("case_public_hash"), name="ck_ops_run_public_identity"),
        byte_bounds(source_json, WHOLE_BYTES, "ck_ops_run_source_body"),
        CheckConstraint(column("source_bytes") == func.length(cast(column("source_json"), LargeBinary)), name="ck_ops_run_exact_source_bytes"),
        byte_bounds(prompt_snapshot_json, FRAME_BYTES, "ck_ops_run_prompt_body"),
        byte_bounds(execution_snapshot_json, FRAME_BYTES, "ck_ops_run_execution_body"),
        *(CheckConstraint("length(" + field + ")=64", name="ck_ops_run_" + field) for field in ARTIFACT_HASHES),
        *(CheckConstraint(field + ">0", name="ck_ops_run_" + field + "_positive") for field in AUDIT_FIELDS),
        *(
            CheckConstraint(left + " IS NULL OR " + right + " IS NULL OR " + left + "<>" + right, name="ck_ops_run_audit_distinct_" + str(i))
            for i, (left, right) in enumerate((left, right) for at, left in enumerate(AUDIT_FIELDS) for right in AUDIT_FIELDS[at + 1 :])
        ),
        Index("idx_ops_run_case_actor", "case_id", "requested_by", "recorded_at"),
    )


class AIOperationsRunResult(Base):
    __tablename__ = "hoimsystem_ai_operations_run_result"
    run_id = Column(String(36), primary_key=True)
    schema_version = Column(String(48), nullable=False)
    lease_token = Column(String(36), nullable=False)
    accepted_at = Column(utc6(), nullable=False)
    result_json = Column(medium_text(), nullable=False)
    result_bytes = Column(Integer, nullable=False)
    result_hash = Column(String(64), nullable=False)
    source_binding_hash = Column(String(64), nullable=False)
    instructions_digest = Column(String(64), nullable=False)
    accept_audit_event_id = Column(Integer, ForeignKey("hoimsystem_ai_audit_event.event_id"), nullable=False, unique=True)
    __table_args__ = (
        ForeignKeyConstraint(
            ["run_id", "source_binding_hash", "instructions_digest"],
            ["hoimsystem_ai_operations_run_artifact.run_id", "hoimsystem_ai_operations_run_artifact.source_binding_hash", "hoimsystem_ai_operations_run_artifact.instructions_digest"],
            name="fk_ops_result_original_binding",
        ),
        CheckConstraint(f"HEX(schema_version)=HEX('{RESULT_SCHEMA}')", name="ck_ops_result_schema"),
        CheckConstraint("result_bytes>0 AND result_bytes<=8388608 AND accept_audit_event_id>0", name="ck_ops_result_bytes_receipt"),
        byte_bounds(result_json, WHOLE_BYTES, "ck_ops_result_body"),
        CheckConstraint(column("result_bytes") == func.length(cast(column("result_json"), LargeBinary)), name="ck_ops_result_exact_bytes"),
        *(CheckConstraint("length(" + field + ")=64", name="ck_ops_result_" + field) for field in ("result_hash", "source_binding_hash", "instructions_digest")),
    )


OPERATIONS_RUN_MODELS = (AIOperationsRunArtifact, AIOperationsRunResult)
