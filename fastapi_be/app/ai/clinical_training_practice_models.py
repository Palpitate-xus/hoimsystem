"""Immutable actual practice submissions; no model-run or competency authority."""

from sqlalchemy import CheckConstraint, Column, ForeignKey, ForeignKeyConstraint, Index, Integer, LargeBinary, String, cast, func

from app.ai.clinical_training_models import byte_bounds, medium_text, utc6
from app.database import Base


class AITrainingSubmission(Base):
    __tablename__ = "hoimsystem_ai_training_submission"
    submission_id = Column(String(36), primary_key=True)
    schema_version = Column(String(64), nullable=False)
    review_id = Column(String(36), nullable=False)
    lesson_id = Column(String(36), nullable=False)
    review_hash = Column(String(64), nullable=False)
    lesson_private_hash = Column(String(64), nullable=False)
    lesson_public_hash = Column(String(64), nullable=False)
    lesson_references_hash = Column(String(64), nullable=False)
    actor_id = Column(Integer, ForeignKey("hoimsystem_users.user_id"), nullable=False)
    actor_role = Column(String(32), nullable=False)
    actor_epoch = Column(utc6(), nullable=True)
    submitted_at = Column(utc6(), nullable=False)
    submission_json = Column(medium_text(), nullable=False)
    submission_hash = Column(String(64), nullable=False)
    submission_bytes = Column(Integer, nullable=False)
    feedback_json = Column(medium_text(), nullable=False)
    feedback_hash = Column(String(64), nullable=False)
    feedback_bytes = Column(Integer, nullable=False)
    scoring_method = Column(String(64), nullable=False)
    question_count = Column(Integer, nullable=False)
    matching_count = Column(Integer, nullable=False)
    differing_count = Column(Integer, nullable=False)
    unanswered_count = Column(Integer, nullable=False)
    creation_event_id = Column(Integer, ForeignKey("hoimsystem_ai_audit_event.event_id"), nullable=False, unique=True)
    __table_args__ = (
        ForeignKeyConstraint(["review_id", "lesson_id", "review_hash", "lesson_private_hash", "lesson_public_hash", "lesson_references_hash"], ["hoimsystem_ai_training_review.review_id", "hoimsystem_ai_training_review.lesson_id", "hoimsystem_ai_training_review.review_hash", "hoimsystem_ai_training_review.lesson_private_hash", "hoimsystem_ai_training_review.lesson_public_hash", "hoimsystem_ai_training_review.lesson_references_hash"], name="fk_training_submission_exact_review"),
        CheckConstraint("schema_version='clinical_training_submission_record_v1' AND scoring_method='all_selected_options_exact_set_match_v1'", name="ck_training_submission_schema_recipe"),
        CheckConstraint("actor_role IN ('super_admin','admin','director','doctor','nurse','pharmacist')", name="ck_training_submission_actor"),
        CheckConstraint("length(review_hash)=64 AND length(lesson_private_hash)=64 AND length(lesson_public_hash)=64 AND length(lesson_references_hash)=64 AND length(submission_hash)=64 AND length(feedback_hash)=64", name="ck_training_submission_hashes"),
        CheckConstraint("submission_bytes BETWEEN 1 AND 131072 AND feedback_bytes BETWEEN 1 AND 8388608", name="ck_training_submission_sizes"),
        byte_bounds(submission_json, 131072, "ck_training_submission_bytes"),
        byte_bounds(feedback_json, 8388608, "ck_training_feedback_bytes"),
        CheckConstraint(func.length(cast(submission_json, LargeBinary)) == submission_bytes, name="ck_training_submission_exact_size"),
        CheckConstraint(func.length(cast(feedback_json, LargeBinary)) == feedback_bytes, name="ck_training_feedback_exact_size"),
        CheckConstraint("question_count BETWEEN 1 AND 64 AND matching_count BETWEEN 0 AND 64 AND differing_count BETWEEN 0 AND 64 AND unanswered_count BETWEEN 0 AND 64 AND matching_count+differing_count+unanswered_count=question_count", name="ck_training_submission_counts"),
        Index("idx_training_submission_owner_time", "actor_id", "submitted_at", "submission_id"),
    )


TRAINING_PRACTICE_MODELS = (AITrainingSubmission,)
