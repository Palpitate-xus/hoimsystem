"""Additive training Task frames and accepted drafts; runtime proves authority."""

from sqlalchemy import Column, ForeignKey, ForeignKeyConstraint, Index, Integer, LargeBinary, String, UniqueConstraint, cast, column, func

from app.ai.clinical_training_models import byte_bounds, medium_text, utc6
from app.database import Base
from app.sql_constraints import PortableCheckConstraint as CheckConstraint

ARTIFACT_SCHEMA = "clinical_training_run_artifact_v1"
RESULT_SCHEMA = "clinical_training_run_result_v1"
FRAME_BYTES = 262144
WHOLE_BYTES = 8388608
ARTIFACT_HASHES = (
    "review_hash", "lesson_private_hash", "lesson_public_hash", "lesson_references_hash",
    "submission_hash", "feedback_hash", "reference_state_hash", "source_binding_hash",
    "source_projection_hash", "prompt_snapshot_hash", "execution_snapshot_hash",
    "instructions_digest", "input_hash", "evidence_hash", "metadata_hash", "run_header_hash",
)
ORIGINAL_AUDIT_FIELDS = ("lesson_creation_event_id", "review_creation_event_id", "submission_creation_event_id")
TASK_AUDIT_FIELDS = ("created_audit_event_id", "claim_event_id", "dispatch_event_id", "usage_event_id")


class AITrainingRunArtifact(Base):
    __tablename__ = "hoimsystem_ai_training_run_artifact"
    run_id = Column(String(36), ForeignKey("hoimsystem_ai_run.run_id"), primary_key=True)
    schema_version = Column(String(64), nullable=False)
    submission_id = Column(String(36), ForeignKey("hoimsystem_ai_training_submission.submission_id"), nullable=False)
    review_id = Column(String(36), nullable=False)
    lesson_id = Column(String(36), nullable=False)
    review_hash = Column(String(64), nullable=False)
    lesson_private_hash = Column(String(64), nullable=False)
    lesson_public_hash = Column(String(64), nullable=False)
    lesson_references_hash = Column(String(64), nullable=False)
    requested_by = Column(Integer, ForeignKey("hoimsystem_users.user_id"), nullable=False)
    actor_role = Column(String(32), nullable=False)
    actor_epoch = Column(utc6(), nullable=True)
    recorded_at = Column(utc6(), nullable=False)
    submission_hash = Column(String(64), nullable=False)
    feedback_hash = Column(String(64), nullable=False)
    reference_state_hash = Column(String(64), nullable=False)
    lesson_creation_event_id = Column(Integer, ForeignKey("hoimsystem_ai_audit_event.event_id"), nullable=False)
    review_creation_event_id = Column(Integer, ForeignKey("hoimsystem_ai_audit_event.event_id"), nullable=False)
    submission_creation_event_id = Column(Integer, ForeignKey("hoimsystem_ai_audit_event.event_id"), nullable=False)
    objective = Column(String(40), nullable=False)
    source_binding_json = Column(medium_text(), nullable=False)
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
    claimed_at = Column(utc6(), nullable=True)
    lease_token = Column(String(36), nullable=True)
    dispatch_event_id = Column(Integer, ForeignKey("hoimsystem_ai_audit_event.event_id"), nullable=True, unique=True)
    usage_event_id = Column(Integer, ForeignKey("hoimsystem_ai_audit_event.event_id"), nullable=True, unique=True)
    __table_args__ = (
        ForeignKeyConstraint(["review_id", "lesson_id", "review_hash", "lesson_private_hash", "lesson_public_hash", "lesson_references_hash"], ["hoimsystem_ai_training_review.review_id", "hoimsystem_ai_training_review.lesson_id", "hoimsystem_ai_training_review.review_hash", "hoimsystem_ai_training_review.lesson_private_hash", "hoimsystem_ai_training_review.lesson_public_hash", "hoimsystem_ai_training_review.lesson_references_hash"], name="fk_training_run_exact_review"),
        UniqueConstraint("run_id", "lease_token", "source_projection_hash", "instructions_digest", name="uq_training_run_result_binding"),
        CheckConstraint(f"HEX(schema_version)=HEX('{ARTIFACT_SCHEMA}')", name="ck_training_run_schema"),
        CheckConstraint("objective IN ('explain_practice_feedback','review_supplied_material','identify_reviewed_gaps')", name="ck_training_run_objective"),
        CheckConstraint("actor_role IN ('super_admin','admin','director','doctor','nurse','pharmacist')", name="ck_training_run_actor"),
        CheckConstraint("requested_by>0 AND provider_revision>0 AND config_revision>0 AND prompt_version>=0", name="ck_training_run_positive"),
        CheckConstraint("(prompt_id IS NULL AND prompt_version=0) OR (prompt_id IS NOT NULL AND prompt_version>0)", name="ck_training_run_prompt_origin"),
        CheckConstraint("source_bytes BETWEEN 1 AND 8388608", name="ck_training_run_source_bytes"),
        byte_bounds(source_json, WHOLE_BYTES, "ck_training_run_source_body"),
        CheckConstraint(column("source_bytes") == func.length(cast(column("source_json"), LargeBinary)), name="ck_training_run_exact_source_bytes"),
        byte_bounds(source_binding_json, FRAME_BYTES, "ck_training_run_binding_body"),
        byte_bounds(prompt_snapshot_json, FRAME_BYTES, "ck_training_run_prompt_body"),
        byte_bounds(execution_snapshot_json, FRAME_BYTES, "ck_training_run_execution_body"),
        CheckConstraint("(claim_event_id IS NULL AND claimed_at IS NULL AND lease_token IS NULL) OR (claim_event_id IS NOT NULL AND claimed_at IS NOT NULL AND lease_token IS NOT NULL AND length(lease_token)=36 AND claimed_at>=recorded_at)", name="ck_training_run_claim_identity"),
        CheckConstraint("dispatch_event_id IS NULL OR claim_event_id IS NOT NULL", name="ck_training_run_dispatch_claim"),
        *(CheckConstraint("length(" + field + ")=64", name="ck_training_run_hash_" + str(index)) for index, field in enumerate(ARTIFACT_HASHES)),
        *(CheckConstraint(field + ">0", name="ck_training_run_audit_" + str(index)) for index, field in enumerate((*ORIGINAL_AUDIT_FIELDS, *TASK_AUDIT_FIELDS))),
        *(CheckConstraint(left + " IS NULL OR " + right + " IS NULL OR " + left + "<>" + right, name="ck_training_run_distinct_audit_" + str(index)) for index, (left, right) in enumerate((left, right) for at, left in enumerate((*ORIGINAL_AUDIT_FIELDS, *TASK_AUDIT_FIELDS)) for right in (*ORIGINAL_AUDIT_FIELDS, *TASK_AUDIT_FIELDS)[at + 1:])),
        Index("idx_training_run_owner_time", "requested_by", "recorded_at", "run_id"),
        Index("idx_training_run_submission", "submission_id", "run_id"),
    )


class AITrainingRunResult(Base):
    __tablename__ = "hoimsystem_ai_training_run_result"
    run_id = Column(String(36), primary_key=True)
    schema_version = Column(String(64), nullable=False)
    lease_token = Column(String(36), nullable=False)
    accepted_at = Column(utc6(), nullable=False)
    result_json = Column(medium_text(), nullable=False)
    result_bytes = Column(Integer, nullable=False)
    result_hash = Column(String(64), nullable=False)
    source_projection_hash = Column(String(64), nullable=False)
    instructions_digest = Column(String(64), nullable=False)
    accept_audit_event_id = Column(Integer, ForeignKey("hoimsystem_ai_audit_event.event_id"), nullable=False, unique=True)
    __table_args__ = (
        ForeignKeyConstraint(["run_id", "lease_token", "source_projection_hash", "instructions_digest"], ["hoimsystem_ai_training_run_artifact.run_id", "hoimsystem_ai_training_run_artifact.lease_token", "hoimsystem_ai_training_run_artifact.source_projection_hash", "hoimsystem_ai_training_run_artifact.instructions_digest"], name="fk_training_result_original_claim"),
        CheckConstraint(f"HEX(schema_version)=HEX('{RESULT_SCHEMA}')", name="ck_training_result_schema"),
        CheckConstraint("result_bytes BETWEEN 1 AND 8388608 AND accept_audit_event_id>0 AND length(lease_token)=36", name="ck_training_result_size_receipt"),
        byte_bounds(result_json, WHOLE_BYTES, "ck_training_result_body"),
        CheckConstraint(column("result_bytes") == func.length(cast(column("result_json"), LargeBinary)), name="ck_training_result_exact_bytes"),
        *(CheckConstraint("length(" + field + ")=64", name="ck_training_result_hash_" + str(index)) for index, field in enumerate(("result_hash", "source_projection_hash", "instructions_digest"))),
    )


TRAINING_RUN_MODELS = (AITrainingRunArtifact, AITrainingRunResult)
