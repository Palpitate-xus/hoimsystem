"""Split research task storage; no large Source or Result enters AIRun.TEXT.

Specific creation, usage and acceptance audit keys have different meanings.
These tables grant no research, model, archival or export permission.
"""

from sqlalchemy import CheckConstraint, Column, ForeignKey, Index, Integer, String, Text, UniqueConstraint, column

from app.ai.research_cohort_models import SNAPSHOT_BYTES, _bytes, _hash_constraint, _json_constraint, original_json, utc6
from app.database import Base

ARTIFACT_SCHEMA = "research_cohort_run_artifact_v1"
RESULT_SCHEMA = "research_cohort_run_result_v1"
FRAME_BYTES = 262144
BINDING_BYTES = 32768
ANCHOR_HASHES = (
    "source_projection_hash",
    "source_binding_hash",
    "prompt_snapshot_hash",
    "execution_snapshot_hash",
    "instructions_digest",
    "context_digest",
    "input_hash",
    "evidence_hash",
    "metadata_hash",
)


class AIResearchCohortRunArtifact(Base):
    __tablename__ = "hoimsystem_ai_research_cohort_run_artifact"
    run_id = Column(String(36), ForeignKey("hoimsystem_ai_run.run_id"), primary_key=True)
    case_id = Column(String(36), ForeignKey("hoimsystem_ai_research_cohort_case.case_id"), nullable=False)
    scope_id = Column(String(36), ForeignKey("hoimsystem_ai_research_study_scope.scope_id"), nullable=False)
    requested_by = Column(Integer, ForeignKey("hoimsystem_users.user_id"), nullable=False)
    schema_version = Column(String(48), nullable=False)
    recorded_at = Column(utc6(), nullable=False)
    source_bytes = Column(Integer, nullable=False)
    source_json = Column(original_json(), nullable=False)
    source_projection_hash = Column(String(64), nullable=False)
    source_binding_json = Column(Text, nullable=False)
    source_binding_hash = Column(String(64), nullable=False)
    prompt_id = Column(String(36), ForeignKey("hoimsystem_ai_prompt_version.prompt_id"), nullable=True)
    prompt_version = Column(Integer, nullable=False)
    prompt_snapshot_json = Column(original_json(), nullable=False)
    prompt_snapshot_hash = Column(String(64), nullable=False)
    provider_id = Column(Integer, ForeignKey("hoimsystem_ai_provider.provider_id"), nullable=False)
    provider_revision = Column(Integer, nullable=False)
    config_revision = Column(Integer, nullable=False)
    execution_snapshot_json = Column(original_json(), nullable=False)
    execution_snapshot_hash = Column(String(64), nullable=False)
    instructions_digest = Column(String(64), nullable=False)
    context_digest = Column(String(64), nullable=False)
    input_hash = Column(String(64), nullable=False)
    evidence_hash = Column(String(64), nullable=False)
    metadata_hash = Column(String(64), nullable=False)
    created_audit_event_id = Column(Integer, ForeignKey("hoimsystem_ai_audit_event.event_id"), nullable=False)
    usage_event_id = Column(Integer, ForeignKey("hoimsystem_ai_audit_event.event_id"), nullable=True)
    dispatch_event_id = Column(Integer, ForeignKey("hoimsystem_ai_audit_event.event_id", name="fk_rcr_dispatch_audit"), nullable=True)
    __table_args__ = (
        CheckConstraint(f"HEX(schema_version)=HEX('{ARTIFACT_SCHEMA}')", name="ck_rcr_artifact_schema"),
        CheckConstraint(
            "requested_by>0 AND prompt_version>=0 AND provider_revision>0 AND config_revision>0 AND created_audit_event_id>0 AND (usage_event_id IS NULL OR (usage_event_id>0 AND usage_event_id<>created_audit_event_id))",
            name="ck_rcr_artifact_positive",
        ),
        CheckConstraint(
            "dispatch_event_id IS NULL OR (dispatch_event_id>0 AND dispatch_event_id<>created_audit_event_id AND (usage_event_id IS NULL OR dispatch_event_id<>usage_event_id))",
            name="ck_rcr_artifact_dispatch",
        ),
        CheckConstraint("(prompt_id IS NULL AND prompt_version=0) OR (prompt_id IS NOT NULL AND prompt_version>0)", name="ck_rcr_artifact_prompt_origin"),
        CheckConstraint(f"source_bytes>0 AND source_bytes<={SNAPSHOT_BYTES}", name="ck_rcr_artifact_source_bytes"),
        _json_constraint("source_json", SNAPSHOT_BYTES, "ck_rcr_artifact_source_json"),
        CheckConstraint(column("source_bytes") == _bytes("source_json"), name="ck_rcr_artifact_exact_bytes"),
        _json_constraint("source_binding_json", BINDING_BYTES, "ck_rcr_artifact_binding_json"),
        _json_constraint("prompt_snapshot_json", FRAME_BYTES, "ck_rcr_artifact_prompt_json"),
        _json_constraint("execution_snapshot_json", FRAME_BYTES, "ck_rcr_artifact_execution_json"),
        *(_hash_constraint(field, "ck_rcr_artifact_" + field) for field in ANCHOR_HASHES),
        UniqueConstraint("created_audit_event_id", name="uq_rcr_created_audit"),
        UniqueConstraint("usage_event_id", name="uq_rcr_usage_audit"),
        UniqueConstraint("dispatch_event_id", name="uq_rcr_dispatch_audit"),
        Index("idx_rcr_artifact_case_actor", "case_id", "requested_by", "recorded_at"),
    )


class AIResearchCohortRunResult(Base):
    __tablename__ = "hoimsystem_ai_research_cohort_run_result"
    run_id = Column(String(36), ForeignKey("hoimsystem_ai_research_cohort_run_artifact.run_id"), primary_key=True)
    case_id = Column(String(36), ForeignKey("hoimsystem_ai_research_cohort_case.case_id"), nullable=False)
    scope_id = Column(String(36), ForeignKey("hoimsystem_ai_research_study_scope.scope_id"), nullable=False)
    schema_version = Column(String(48), nullable=False)
    lease_token = Column(String(36), nullable=False)
    accepted_at = Column(utc6(), nullable=False)
    result_json = Column(original_json(), nullable=False)
    result_bytes = Column(Integer, nullable=False)
    content_hash = Column(String(64), nullable=False)
    source_binding_hash = Column(String(64), nullable=False)
    instructions_digest = Column(String(64), nullable=False)
    accept_audit_event_id = Column(Integer, ForeignKey("hoimsystem_ai_audit_event.event_id"), nullable=False)
    __table_args__ = (
        CheckConstraint(f"HEX(schema_version)=HEX('{RESULT_SCHEMA}')", name="ck_rcr_result_schema"),
        CheckConstraint(f"result_bytes>0 AND result_bytes<={SNAPSHOT_BYTES} AND accept_audit_event_id>0", name="ck_rcr_result_positive"),
        _json_constraint("result_json", SNAPSHOT_BYTES, "ck_rcr_result_body"),
        CheckConstraint(column("result_bytes") == _bytes("result_json"), name="ck_rcr_result_exact_bytes"),
        *(_hash_constraint(field, "ck_rcr_result_" + field) for field in ("content_hash", "source_binding_hash", "instructions_digest")),
        UniqueConstraint("accept_audit_event_id", name="uq_rcr_accept_audit"),
        Index("idx_rcr_result_case", "case_id", "accepted_at"),
    )


RESEARCH_COHORT_RUN_MODELS = (AIResearchCohortRunArtifact, AIResearchCohortRunResult)
