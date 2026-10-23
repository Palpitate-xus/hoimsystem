"""Additive immutable finite-family Scenario governance, not model validation."""

from sqlalchemy import CheckConstraint, Column, ForeignKey, Index, String, Text

from app.ai.infection_cluster_models import Governed, governance_checks
from app.database import Base


class AIInfectionScenario(Governed, Base):
    __tablename__ = "hoimsystem_ai_infection_scenario"
    __table_args__ = tuple(item for item in governance_checks("scenario") if item.name != "ck_inf_scenario_review_flags") + (
        CheckConstraint("schema_version='infection_comparison_scenario_v1'", name="ck_inf_scenario_schema"),
        CheckConstraint(
            "parameters_review IN ('unknown','confirmed','not_confirmed') AND privacy_review IN ('unknown','confirmed','not_confirmed') AND faithfulness_review IN ('unknown','confirmed','not_confirmed') AND ((reviewed_by IS NULL AND parameters_review='unknown' AND privacy_review='unknown' AND faithfulness_review='unknown' AND reviewer_epoch_hash IS NULL) OR (reviewed_by IS NOT NULL AND parameters_review<>'unknown' AND privacy_review<>'unknown' AND faithfulness_review<>'unknown' AND length(reviewer_epoch_hash)=64)) AND (status<>'published' OR (parameters_review='confirmed' AND privacy_review='confirmed' AND faithfulness_review='confirmed')) AND (status<>'rejected' OR parameters_review='not_confirmed' OR privacy_review='not_confirmed' OR faithfulness_review='not_confirmed')",
            name="ck_inf_scenario_parameters",
        ),
        CheckConstraint(
            "length(source_private_hash)=64 AND length(source_public_hash)=64 AND length(source_witness_hash)=64 AND length(directory_hash)=64 AND length(author_epoch_hash)=64 AND length(plan_hash)=64 AND length(recipe_hash)=64 AND length(implementation_hash)=64 AND length(department_ids_json)<=4096",
            name="ck_inf_scenario_anchors",
        ),
        Index("idx_inf_scenario_snapshot", "snapshot_id", "recorded_at", "scenario_id"),
    )
    scenario_id = Column(String(36), primary_key=True)
    schema_version = Column(String(48), nullable=False)
    snapshot_id = Column(String(36), ForeignKey("hoimsystem_ai_infection_snapshot.snapshot_id"), nullable=False)
    source_id = Column(String(95), nullable=False)
    source_private_hash = Column(String(64), nullable=False)
    source_public_hash = Column(String(64), nullable=False)
    source_witness_hash = Column(String(64), nullable=False)
    department_ids_json = Column(Text, nullable=False)
    directory_hash = Column(String(64), nullable=False)
    author_epoch_hash = Column(String(64), nullable=False)
    reviewer_epoch_hash = Column(String(64), nullable=True)
    plan_hash = Column(String(64), nullable=False)
    recipe_hash = Column(String(64), nullable=False)
    implementation_hash = Column(String(64), nullable=False)
    parameters_review = Column(String(20), nullable=False)
