"""Split local Source/result storage and durable native Task classification."""

from sqlalchemy import CheckConstraint, Column, ForeignKey, Index, Integer, LargeBinary, String, cast, column, func

from app.ai.infection_cluster_models import medium_text, utc6
from app.database import Base


class AIInfectionRunArtifact(Base):
    __tablename__ = "hoimsystem_ai_infection_run_artifact"
    __table_args__ = (
        CheckConstraint("schema_version='infection_local_run_artifact_v1' AND preview IN (0,1) AND source_bytes BETWEEN 1 AND 8388608", name="ck_inf_run_identity"),
        CheckConstraint(func.length(cast(column("source_json"), LargeBinary)) == column("source_bytes"), name="ck_inf_run_source_utf8"),
        CheckConstraint(
            "length(source_hash)=64 AND length(input_hash)=64 AND length(evidence_hash)=64 AND length(metadata_hash)=64 AND length(source_binding_hash)=64 AND length(requester_epoch_hash)=64 AND length(configuration_hash)=64 AND length(scenario_content_hash)=64 AND length(scenario_governance_hash)=64 AND length(profile_content_hash)=64 AND length(profile_governance_hash)=64 AND length(recipe_hash)=64 AND length(implementation_hash)=64",
            name="ck_inf_run_hashes",
        ),
        CheckConstraint(
            "(result_json IS NULL AND result_hash IS NULL AND result_bytes IS NULL AND accept_event_id IS NULL AND accepted_lease IS NULL AND accepted_at IS NULL) OR (result_json IS NOT NULL AND length(result_hash)=64 AND result_bytes BETWEEN 1 AND 8388608 AND accept_event_id IS NOT NULL AND length(accepted_lease)=36 AND accepted_at IS NOT NULL AND usage_event_id IS NOT NULL)",
            name="ck_inf_run_result_state",
        ),
        CheckConstraint(func.length(cast(column("result_json"), LargeBinary)) == column("result_bytes"), name="ck_inf_run_result_utf8"),
        CheckConstraint(
            "(usage_event_id IS NULL OR usage_event_id<>create_event_id) AND (accept_event_id IS NULL OR (accept_event_id<>create_event_id AND accept_event_id<>usage_event_id))",
            name="ck_inf_run_specific_audits",
        ),
        Index("idx_inf_run_requester_created", "requested_by", "created_at", "run_id"),
        Index("idx_inf_run_scenario", "scenario_id", "run_id"),
    )
    run_id = Column(String(36), ForeignKey("hoimsystem_ai_run.run_id"), primary_key=True)
    scenario_id = Column(String(36), ForeignKey("hoimsystem_ai_infection_scenario.scenario_id"), nullable=False)
    snapshot_id = Column(String(36), ForeignKey("hoimsystem_ai_infection_snapshot.snapshot_id"), nullable=False)
    profile_id = Column(String(36), ForeignKey("hoimsystem_ai_infection_local_profile.profile_id"), nullable=False)
    requested_by = Column(Integer, ForeignKey("hoimsystem_users.user_id"), nullable=False)
    schema_version = Column(String(48), nullable=False)
    created_at = Column(utc6(), nullable=False)
    preview = Column(Integer, nullable=False)
    requester_epoch_hash = Column(String(64), nullable=False)
    configuration_hash = Column(String(64), nullable=False)
    source_binding_hash = Column(String(64), nullable=False)
    scenario_content_hash = Column(String(64), nullable=False)
    scenario_governance_hash = Column(String(64), nullable=False)
    profile_content_hash = Column(String(64), nullable=False)
    profile_governance_hash = Column(String(64), nullable=False)
    recipe_hash = Column(String(64), nullable=False)
    implementation_hash = Column(String(64), nullable=False)
    input_hash = Column(String(64), nullable=False)
    evidence_hash = Column(String(64), nullable=False)
    metadata_hash = Column(String(64), nullable=False)
    source_json = Column(medium_text(), nullable=False)
    source_hash = Column(String(64), nullable=False)
    source_bytes = Column(Integer, nullable=False)
    result_json = Column(medium_text(), nullable=True)
    result_hash = Column(String(64), nullable=True)
    result_bytes = Column(Integer, nullable=True)
    create_event_id = Column(Integer, ForeignKey("hoimsystem_ai_audit_event.event_id"), nullable=False)
    usage_event_id = Column(Integer, ForeignKey("hoimsystem_ai_audit_event.event_id"), nullable=True)
    accept_event_id = Column(Integer, ForeignKey("hoimsystem_ai_audit_event.event_id"), nullable=True)
    accepted_lease = Column(String(36), nullable=True)
    accepted_at = Column(utc6(), nullable=True)
