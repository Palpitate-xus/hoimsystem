"""Local versioned implementation profiles and current FeatureConfig selection."""

from sqlalchemy import CheckConstraint, Column, ForeignKey, Index, Integer, String

from app.ai.infection_cluster_models import Governed, governance_checks, utc6
from app.database import Base


class AIInfectionLocalProfile(Governed, Base):
    __tablename__ = "hoimsystem_ai_infection_local_profile"
    __table_args__ = tuple(item for item in governance_checks("local_profile") if item.name != "ck_inf_local_profile_review_flags") + (
        CheckConstraint(
            "schema_version='infection_local_profile_v1' AND length(implementation_hash)=64 AND length(directory_hash)=64 AND length(author_epoch_hash)=64", name="ck_inf_local_profile_identity"
        ),
        CheckConstraint(
            "parameters_review IN ('unknown','confirmed','not_confirmed') AND privacy_review IN ('unknown','confirmed','not_confirmed') AND faithfulness_review IN ('unknown','confirmed','not_confirmed') AND ((reviewed_by IS NULL AND parameters_review='unknown' AND privacy_review='unknown' AND faithfulness_review='unknown' AND reviewer_epoch_hash IS NULL) OR (reviewed_by IS NOT NULL AND parameters_review<>'unknown' AND privacy_review<>'unknown' AND faithfulness_review<>'unknown' AND length(reviewer_epoch_hash)=64)) AND (status<>'published' OR (parameters_review='confirmed' AND privacy_review='confirmed' AND faithfulness_review='confirmed')) AND (status<>'rejected' OR parameters_review='not_confirmed' OR privacy_review='not_confirmed' OR faithfulness_review='not_confirmed')",
            name="ck_inf_local_profile_parameters",
        ),
        Index("idx_inf_local_profile_created", "recorded_at", "profile_id"),
    )
    profile_id = Column(String(36), primary_key=True)
    schema_version = Column(String(40), nullable=False)
    implementation_hash = Column(String(64), nullable=False)
    directory_hash = Column(String(64), nullable=False)
    author_epoch_hash = Column(String(64), nullable=False)
    reviewer_epoch_hash = Column(String(64), nullable=True)
    parameters_review = Column(String(20), nullable=False)


class AIInfectionLocalSelection(Base):
    __tablename__ = "hoimsystem_ai_infection_local_selection"
    __table_args__ = (
        CheckConstraint("feature_key='infection_cluster' AND revision>=1 AND feature_revision>=1 AND length(config_hash)=64 AND length(writer_epoch_hash)=64", name="ck_inf_local_selection_identity"),
    )
    feature_key = Column(String(64), ForeignKey("hoimsystem_ai_feature_config.feature_key"), primary_key=True)
    profile_id = Column(String(36), ForeignKey("hoimsystem_ai_infection_local_profile.profile_id"), nullable=True)
    revision = Column(Integer, nullable=False)
    feature_revision = Column(Integer, nullable=False)
    config_hash = Column(String(64), nullable=False)
    writer_epoch_hash = Column(String(64), nullable=False)
    updated_by = Column(Integer, ForeignKey("hoimsystem_users.user_id"), nullable=False)
    updated_at = Column(utc6(), nullable=False)
    change_event_id = Column(Integer, ForeignKey("hoimsystem_ai_audit_event.event_id"), nullable=False)
