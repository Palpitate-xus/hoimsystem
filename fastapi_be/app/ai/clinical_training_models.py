"""Additive immutable lesson/review storage; no publication or learner authority."""

from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, ForeignKeyConstraint, Index, Integer, LargeBinary, String, Text, UniqueConstraint, and_, cast, func
from sqlalchemy.dialects import mysql

from app.database import Base


def utc6():
    return DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql").with_variant(mysql.DATETIME(fsp=6), "mariadb")


def medium_text():
    return Text().with_variant(mysql.MEDIUMTEXT(), "mysql").with_variant(mysql.MEDIUMTEXT(), "mariadb")


def byte_bounds(column, maximum, name):
    size = func.length(cast(column, LargeBinary))
    return CheckConstraint(and_(size >= 1, size <= maximum), name=name)


class AITrainingWriteGate(Base):
    __tablename__ = "hoimsystem_ai_training_write_gate"
    gate_id = Column(Integer, primary_key=True, autoincrement=False)
    revision = Column(Integer, nullable=False)
    __table_args__ = (CheckConstraint("gate_id=1 AND revision=1", name="ck_training_gate_identity"),)


class AITrainingLesson(Base):
    __tablename__ = "hoimsystem_ai_training_lesson"
    lesson_id = Column(String(36), primary_key=True)
    schema_version = Column(String(64), nullable=False)
    title = Column(String(300), nullable=False)
    version_label = Column(String(300), nullable=False)
    private_json = Column(medium_text(), nullable=False)
    public_json = Column(medium_text(), nullable=False)
    references_json = Column(medium_text(), nullable=False)
    reference_ids_json = Column(medium_text(), nullable=False)
    reference_ids_hash = Column(String(64), nullable=False)
    reference_ids_bytes = Column(Integer, nullable=False)
    reference_state_hash = Column(String(64), nullable=False)
    private_hash = Column(String(64), nullable=False)
    public_hash = Column(String(64), nullable=False)
    references_hash = Column(String(64), nullable=False)
    private_bytes = Column(Integer, nullable=False)
    public_bytes = Column(Integer, nullable=False)
    references_bytes = Column(Integer, nullable=False)
    created_by = Column(Integer, ForeignKey("hoimsystem_users.user_id"), nullable=False)
    author_role = Column(String(32), nullable=False)
    author_epoch = Column(utc6(), nullable=True)
    created_at = Column(utc6(), nullable=False)
    creation_event_id = Column(Integer, ForeignKey("hoimsystem_ai_audit_event.event_id"), nullable=False, unique=True)
    status = Column(String(16), nullable=False)
    revision = Column(Integer, nullable=False)
    revoked_by = Column(Integer, ForeignKey("hoimsystem_users.user_id"), nullable=True)
    revoked_at = Column(utc6(), nullable=True)
    revoke_reason = Column(String(1000), nullable=False)
    revocation_event_id = Column(Integer, ForeignKey("hoimsystem_ai_audit_event.event_id"), nullable=True, unique=True)
    __table_args__ = (
        UniqueConstraint("lesson_id", "private_hash", "public_hash", "references_hash", name="uq_training_lesson_binding"),
        CheckConstraint("schema_version='clinical_training_private_lesson_v1' AND author_role='super_admin'", name="ck_training_lesson_origin"),
        CheckConstraint("length(private_hash)=64 AND length(public_hash)=64 AND length(references_hash)=64", name="ck_training_lesson_hashes"),
        CheckConstraint("length(reference_ids_hash)=64 AND length(reference_state_hash)=64 AND reference_ids_bytes BETWEEN 1 AND 131072", name="ck_training_reference_headers"),
        byte_bounds(reference_ids_json, 131072, "ck_training_reference_ids_size"),
        CheckConstraint(func.length(cast(reference_ids_json, LargeBinary)) == reference_ids_bytes, name="ck_training_reference_ids_exact"),
        CheckConstraint("private_bytes BETWEEN 1 AND 8388608 AND public_bytes BETWEEN 1 AND 8388608 AND references_bytes BETWEEN 1 AND 8388608", name="ck_training_lesson_sizes"),
        byte_bounds(private_json, 8388608, "ck_training_private_bytes"),
        byte_bounds(public_json, 8388608, "ck_training_public_bytes"),
        byte_bounds(references_json, 8388608, "ck_training_references_bytes"),
        CheckConstraint(func.length(cast(private_json, LargeBinary)) == private_bytes, name="ck_training_private_exact_size"),
        CheckConstraint(func.length(cast(public_json, LargeBinary)) == public_bytes, name="ck_training_public_exact_size"),
        CheckConstraint(func.length(cast(references_json, LargeBinary)) == references_bytes, name="ck_training_references_exact_size"),
        CheckConstraint("(status='active' AND revision=1 AND revoked_by IS NULL AND revoked_at IS NULL AND revoke_reason='' AND revocation_event_id IS NULL) OR (status='revoked' AND revision=2 AND revoked_by IS NOT NULL AND revoked_at IS NOT NULL AND revoke_reason<>'' AND revocation_event_id IS NOT NULL AND revoked_at>=created_at)", name="ck_training_lesson_state"),
        CheckConstraint("revocation_event_id IS NULL OR revocation_event_id<>creation_event_id", name="ck_training_lesson_distinct_events"),
        Index("idx_training_lesson_directory", "status", "created_at", "lesson_id"),
    )


class AITrainingReview(Base):
    __tablename__ = "hoimsystem_ai_training_review"
    review_id = Column(String(36), primary_key=True)
    lesson_id = Column(String(36), nullable=False)
    lesson_private_hash = Column(String(64), nullable=False)
    lesson_public_hash = Column(String(64), nullable=False)
    lesson_references_hash = Column(String(64), nullable=False)
    review_json = Column(Text, nullable=False)
    review_hash = Column(String(64), nullable=False)
    reviewed_by = Column(Integer, ForeignKey("hoimsystem_users.user_id"), nullable=False)
    reviewer_role = Column(String(32), nullable=False)
    reviewer_epoch = Column(utc6(), nullable=True)
    reviewed_at = Column(utc6(), nullable=False)
    review_decision = Column(String(16), nullable=False)
    synthetic_material_checked = Column(Integer, nullable=False)
    answer_key_checked = Column(Integer, nullable=False)
    reference_applicability_checked = Column(Integer, nullable=False)
    model_processing_allowed = Column(Integer, nullable=False)
    creation_event_id = Column(Integer, ForeignKey("hoimsystem_ai_audit_event.event_id"), nullable=False, unique=True)
    status = Column(String(16), nullable=False)
    revision = Column(Integer, nullable=False)
    revoked_by = Column(Integer, ForeignKey("hoimsystem_users.user_id"), nullable=True)
    revoked_at = Column(utc6(), nullable=True)
    revoke_reason = Column(String(1000), nullable=False)
    revocation_event_id = Column(Integer, ForeignKey("hoimsystem_ai_audit_event.event_id"), nullable=True, unique=True)
    __table_args__ = (
        ForeignKeyConstraint(["lesson_id", "lesson_private_hash", "lesson_public_hash", "lesson_references_hash"], ["hoimsystem_ai_training_lesson.lesson_id", "hoimsystem_ai_training_lesson.private_hash", "hoimsystem_ai_training_lesson.public_hash", "hoimsystem_ai_training_lesson.references_hash"], name="fk_training_review_exact_lesson"),
        CheckConstraint("reviewer_role='super_admin' AND length(review_hash)=64", name="ck_training_review_origin"),
        CheckConstraint("review_decision IN ('published','rejected') AND (status=review_decision OR status='revoked')", name="ck_training_review_decision"),
        CheckConstraint("synthetic_material_checked IN (0,1) AND answer_key_checked IN (0,1) AND reference_applicability_checked IN (0,1) AND model_processing_allowed IN (0,1)", name="ck_training_review_flags"),
        CheckConstraint("status<>'published' OR (synthetic_material_checked=1 AND answer_key_checked=1 AND reference_applicability_checked=1)", name="ck_training_review_publication"),
        CheckConstraint("status<>'rejected' OR model_processing_allowed=0", name="ck_training_rejected_no_model"),
        byte_bounds(review_json, 65535, "ck_training_review_bytes"),
        CheckConstraint("(status IN ('published','rejected') AND revision=1 AND revoked_by IS NULL AND revoked_at IS NULL AND revoke_reason='' AND revocation_event_id IS NULL) OR (status='revoked' AND revision=2 AND revoked_by IS NOT NULL AND revoked_at IS NOT NULL AND revoke_reason<>'' AND revocation_event_id IS NOT NULL AND revoked_at>=reviewed_at)", name="ck_training_review_state"),
        CheckConstraint("revocation_event_id IS NULL OR revocation_event_id<>creation_event_id", name="ck_training_review_distinct_events"),
        Index("idx_training_review_directory", "status", "reviewed_at", "review_id"),
    )


TRAINING_SOURCE_MODELS = (AITrainingWriteGate, AITrainingLesson, AITrainingReview)
