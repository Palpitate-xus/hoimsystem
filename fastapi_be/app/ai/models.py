"""AI configuration, evidence, execution and governance persistence."""

import datetime
import uuid

from sqlalchemy import CheckConstraint, Column, Date, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects import mysql

from app.database import Base


def utcnow() -> datetime.datetime:
    """Use naive UTC consistently with the existing application tables."""
    return datetime.datetime.now(datetime.UTC).replace(tzinfo=None)


def new_id() -> str:
    """Create an opaque identifier without patient information."""
    return str(uuid.uuid4())


class AIProvider(Base):
    """Administrator-managed model endpoints; credential ciphertext is never returned."""

    __tablename__ = "hoimsystem_ai_provider"

    provider_id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(80), nullable=False, unique=True)
    kind = Column(String(24), nullable=False, default="chat")
    api_base = Column(String(1000), nullable=False)
    model = Column(String(160), nullable=False)
    api_key_encrypted = Column(Text, nullable=False, default="")
    api_key_env = Column(String(100), nullable=False, default="")
    enabled = Column(Integer, nullable=False, default=0)
    allows_patient_data = Column(Integer, nullable=False, default=0)
    timeout_seconds = Column(Integer, nullable=False, default=30)
    max_output_tokens = Column(Integer, nullable=False, default=2000)
    temperature = Column(Numeric(4, 3), nullable=False, default=0.2)
    supported_features_json = Column(Text, nullable=False, default="[]")
    validation_report = Column(Text, nullable=False, default="")
    validated_at = Column(DateTime, nullable=True)
    revision = Column(Integer, nullable=False, default=1)
    created_by = Column(Integer, ForeignKey("hoimsystem_users.user_id"), nullable=False)
    create_time = Column(DateTime, nullable=False, default=utcnow)
    update_time = Column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)


class AIFeatureConfig(Base):
    """Independent activation and authorization settings for each catalog capability."""

    __tablename__ = "hoimsystem_ai_feature_config"

    feature_key = Column(String(64), primary_key=True)
    enabled = Column(Integer, nullable=False, default=0)
    provider_id = Column(Integer, ForeignKey("hoimsystem_ai_provider.provider_id"), nullable=True)
    allowed_roles_json = Column(Text, nullable=False, default="[]")
    validation_status = Column(String(24), nullable=False, default="unreviewed")
    validation_note = Column(Text, nullable=False, default="")
    validated_by = Column(Integer, ForeignKey("hoimsystem_users.user_id"), nullable=True)
    validated_at = Column(DateTime, nullable=True)
    active_prompt_id = Column(String(36), ForeignKey("hoimsystem_ai_prompt_version.prompt_id"), nullable=True)
    daily_limit = Column(Integer, nullable=False, default=100)
    revision = Column(Integer, nullable=False, default=1)
    updated_by = Column(Integer, ForeignKey("hoimsystem_users.user_id"), nullable=False)
    update_time = Column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)


class AIPromptVersion(Base):
    """Immutable prompt revisions; activation is a pointer on the feature configuration."""

    __tablename__ = "hoimsystem_ai_prompt_version"
    __table_args__ = (UniqueConstraint("feature_key", "version", name="uq_ai_prompt_feature_version"),)

    prompt_id = Column(String(36), primary_key=True, default=new_id)
    feature_key = Column(String(64), nullable=False, index=True)
    version = Column(Integer, nullable=False)
    task_prompt = Column(Text, nullable=False)
    change_note = Column(String(1000), nullable=False)
    created_by = Column(Integer, ForeignKey("hoimsystem_users.user_id"), nullable=False)
    create_time = Column(DateTime, nullable=False, default=utcnow)


class AIKnowledgeDocument(Base):
    """Versioned evidence with explicit review, publication and validity boundaries."""

    __tablename__ = "hoimsystem_ai_knowledge_document"
    __table_args__ = (
        UniqueConstraint("title", "version", name="uq_ai_knowledge_title_version"),
        Index("idx_ai_knowledge_status_category", "status", "category"),
        Index("idx_ai_knowledge_source", "source_kind", "source_reference_id"),
    )

    document_id = Column(String(36), primary_key=True, default=new_id)
    title = Column(String(200), nullable=False)
    version = Column(String(80), nullable=False)
    source_uri = Column(String(2000), nullable=False)
    source_kind = Column(String(40), nullable=True)
    source_reference_id = Column(Integer, nullable=True)
    source_snapshot_hash = Column(String(64), nullable=True)
    category = Column(String(40), nullable=False, default="clinical")
    content = Column(Text, nullable=False)
    content_hash = Column(String(64), nullable=False)
    feature_keys_json = Column(Text, nullable=False, default="[]")
    department_id = Column(Integer, ForeignKey("hoimsystem_department.department_id"), nullable=True)
    status = Column(String(24), nullable=False, default="draft")
    effective_from = Column(DateTime, nullable=True)
    effective_to = Column(DateTime, nullable=True)
    reviewed_by = Column(Integer, ForeignKey("hoimsystem_users.user_id"), nullable=True)
    reviewed_at = Column(DateTime, nullable=True)
    created_by = Column(Integer, ForeignKey("hoimsystem_users.user_id"), nullable=False)
    create_time = Column(DateTime, nullable=False, default=utcnow)


class AIReviewExcerpt(Base):
    """Immutable reviewed text versions, tied to a verifiable original review snapshot."""

    __tablename__ = "hoimsystem_ai_review_excerpt"
    __table_args__ = (
        UniqueConstraint("review_id", "version", name="uq_ai_review_excerpt_version"),
        Index("idx_ai_review_excerpt_status_dept", "status", "department_id"),
    )

    excerpt_id = Column(String(36), primary_key=True, default=new_id)
    review_id = Column(Integer, ForeignKey("hoimsystem_review.review_id"), nullable=False)
    version = Column(Integer, nullable=False)
    source_hash = Column(String(64), nullable=False)
    department_id = Column(Integer, ForeignKey("hoimsystem_department.department_id"), nullable=False)
    redacted_text = Column(Text, nullable=False)
    text_hash = Column(String(64), nullable=False)
    change_note = Column(String(1000), nullable=False)
    status = Column(String(24), nullable=False, default="draft")
    revision = Column(Integer, nullable=False, default=1)
    privacy_checked = Column(Integer, nullable=False, default=0)
    faithfulness_checked = Column(Integer, nullable=False, default=0)
    review_note = Column(String(1000), nullable=False, default="")
    created_by = Column(Integer, ForeignKey("hoimsystem_users.user_id"), nullable=False)
    create_time = Column(DateTime, nullable=False, default=utcnow)
    reviewed_by = Column(Integer, ForeignKey("hoimsystem_users.user_id"), nullable=True)
    reviewed_at = Column(DateTime, nullable=True)
    retired_by = Column(Integer, ForeignKey("hoimsystem_users.user_id"), nullable=True)
    retired_at = Column(DateTime, nullable=True)


class AIAudioAsset(Base):
    """Immutable private audio with explicit patient scope and revocable use authorization."""

    __tablename__ = "hoimsystem_ai_audio_asset"
    __table_args__ = (
        Index("idx_ai_audio_patient_owner", "patient_id", "created_by", "create_time"),
        Index("idx_ai_audio_status", "status"),
    )

    asset_id = Column(String(36), primary_key=True, default=new_id)
    patient_id = Column(Integer, ForeignKey("hoimsystem_patient.patient_id"), nullable=False)
    encounter_ref = Column(String(64), nullable=True)
    media_type = Column(String(80), nullable=False)
    extension = Column(String(12), nullable=False)
    content_hash = Column(String(64), nullable=False)
    byte_size = Column(Integer, nullable=False)
    duration_ms = Column(Integer, nullable=False)
    sample_rate = Column(Integer, nullable=False)
    channels = Column(Integer, nullable=False)
    codec = Column(String(80), nullable=False)
    recorded_at = Column(DateTime, nullable=True)
    authorization_note = Column(String(1000), nullable=False)
    authorized_at = Column(DateTime, nullable=False)
    created_by = Column(Integer, ForeignKey("hoimsystem_users.user_id"), nullable=False)
    create_time = Column(DateTime, nullable=False, default=utcnow)
    status = Column(String(24), nullable=False, default="ready")
    revision = Column(Integer, nullable=False, default=1)
    withdrawn_by = Column(Integer, ForeignKey("hoimsystem_users.user_id"), nullable=True)
    withdrawn_at = Column(DateTime, nullable=True)
    withdrawal_note = Column(String(1000), nullable=False, default="")
    purged_by = Column(Integer, ForeignKey("hoimsystem_users.user_id"), nullable=True)
    purged_at = Column(DateTime, nullable=True)
    purge_note = Column(String(1000), nullable=False, default="")


class AIECGAsset(Base):
    """Immutable patient-chart waveform pair with revocable model use and raw-file audit."""

    __tablename__ = "hoimsystem_ai_ecg_asset"
    __table_args__ = (Index("idx_ai_ecg_patient_time", "patient_id", "create_time"), Index("idx_ai_ecg_owner_status", "created_by", "status"))

    asset_id = Column(String(36), primary_key=True, default=new_id)
    patient_id = Column(Integer, ForeignKey("hoimsystem_patient.patient_id"), nullable=False)
    encounter_ref = Column(String(64), nullable=True)
    content_hash = Column(String(64), nullable=False)
    header_hash = Column(String(64), nullable=False)
    signal_hash = Column(String(64), nullable=False)
    byte_size = Column(Integer, nullable=False)
    header_byte_size = Column(Integer, nullable=False)
    signal_byte_size = Column(Integer, nullable=False)
    metadata_json = Column(Text, nullable=False)
    recorded_at = Column(DateTime, nullable=True)
    authorization_note = Column(String(1000), nullable=False)
    authorized_at = Column(DateTime, nullable=False)
    created_by = Column(Integer, ForeignKey("hoimsystem_users.user_id"), nullable=False)
    create_time = Column(DateTime, nullable=False, default=utcnow)
    status = Column(String(24), nullable=False, default="ready")
    revision = Column(Integer, nullable=False, default=1)
    withdrawn_by = Column(Integer, ForeignKey("hoimsystem_users.user_id"), nullable=True)
    withdrawn_at = Column(DateTime, nullable=True)
    withdrawal_note = Column(String(1000), nullable=False, default="")
    purged_by = Column(Integer, ForeignKey("hoimsystem_users.user_id"), nullable=True)
    purged_at = Column(DateTime, nullable=True)
    purge_note = Column(String(1000), nullable=False, default="")


class AIRun(Base):
    """A traceable AI task; access to both input and result requires patient authorization."""

    __tablename__ = "hoimsystem_ai_run"
    __table_args__ = (
        Index("idx_ai_run_requester_time", "requested_by", "create_time"),
        Index("idx_ai_run_feature_time", "feature_key", "create_time"),
    )

    run_id = Column(String(36), primary_key=True, default=new_id)
    feature_key = Column(String(64), nullable=False)
    provider_id = Column(Integer, ForeignKey("hoimsystem_ai_provider.provider_id"), nullable=True)
    provider_revision = Column(Integer, nullable=True)
    prompt_version = Column(Integer, nullable=False, default=0)
    prompt_hash = Column(String(64), nullable=False)
    context_digest = Column(String(64), nullable=False)
    patient_id = Column(Integer, ForeignKey("hoimsystem_patient.patient_id"), nullable=True)
    encounter_ref = Column(String(64), nullable=True)
    requested_by = Column(Integer, ForeignKey("hoimsystem_users.user_id"), nullable=False)
    status = Column(String(24), nullable=False, default="queued")
    preview = Column(Integer, nullable=False, default=0)
    input_json = Column(Text, nullable=False, default="{}")
    result_json = Column(Text, nullable=False, default="{}")
    evidence_json = Column(Text, nullable=False, default="[]")
    context_metadata_json = Column(Text, nullable=False, default="{}")
    error_code = Column(String(80), nullable=True)
    error_message = Column(String(500), nullable=True)
    input_tokens = Column(Integer, nullable=False, default=0)
    output_tokens = Column(Integer, nullable=False, default=0)
    latency_ms = Column(Integer, nullable=True)
    start_time = Column(DateTime, nullable=True)
    lease_token = Column(String(36), nullable=True)
    create_time = Column(DateTime, nullable=False, default=utcnow)
    finish_time = Column(DateTime, nullable=True)


class AIFeedback(Base):
    """Append-only human review; acceptance is not a clinical correctness label."""

    __tablename__ = "hoimsystem_ai_feedback"

    feedback_id = Column(String(36), primary_key=True, default=new_id)
    run_id = Column(String(36), ForeignKey("hoimsystem_ai_run.run_id"), nullable=False, index=True)
    reviewer_id = Column(Integer, ForeignKey("hoimsystem_users.user_id"), nullable=False)
    outcome = Column(String(24), nullable=False)
    comment = Column(String(2000), nullable=False, default="")
    create_time = Column(DateTime, nullable=False, default=utcnow)


class AIPatientGrant(Base):
    """Explicit, expiring care access when an existing care relationship is unavailable."""

    __tablename__ = "hoimsystem_ai_patient_grant"
    __table_args__ = (Index("idx_ai_grant_user_patient", "user_id", "patient_id"),)

    grant_id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("hoimsystem_users.user_id"), nullable=False)
    patient_id = Column(Integer, ForeignKey("hoimsystem_patient.patient_id"), nullable=False)
    category = Column(String(40), nullable=False)
    reason = Column(String(500), nullable=False)
    expires_at = Column(DateTime, nullable=False)
    revoked = Column(Integer, nullable=False, default=0)
    created_by = Column(Integer, ForeignKey("hoimsystem_users.user_id"), nullable=False)
    create_time = Column(DateTime, nullable=False, default=utcnow)


class AIAuditEvent(Base):
    """Append-only configuration audit with redacted details and no credentials."""

    __tablename__ = "hoimsystem_ai_audit_event"

    event_id = Column(Integer, primary_key=True, autoincrement=True)
    actor_id = Column(Integer, ForeignKey("hoimsystem_users.user_id"), nullable=False)
    action = Column(String(80), nullable=False)
    target = Column(String(120), nullable=False)
    detail_json = Column(Text, nullable=False, default="{}")
    create_time = Column(DateTime, nullable=False, default=utcnow)


class AIImageAsset(Base):
    """Private DICOM source and derived pixels with order-bound, revocable model use."""

    __tablename__ = "hoimsystem_ai_image_asset"
    __table_args__ = (
        Index("idx_ai_image_patient_time", "patient_id", "create_time"),
        Index("idx_ai_image_owner_status", "created_by", "status"),
        Index("idx_ai_image_order", "imaging_order_id"),
    )

    asset_id = Column(String(36), primary_key=True, default=new_id)
    patient_id = Column(Integer, ForeignKey("hoimsystem_patient.patient_id"), nullable=False)
    imaging_order_id = Column(String(36), ForeignKey("hoimsystem_imaging_order.imaging_order_id"), nullable=False)
    encounter_ref = Column(String(64), nullable=True)
    content_hash = Column(String(64), nullable=False)
    original_hash = Column(String(64), nullable=False)
    pixel_hash = Column(String(64), nullable=False)
    byte_size = Column(Integer, nullable=False)
    original_byte_size = Column(Integer, nullable=False)
    pixel_byte_size = Column(Integer, nullable=False)
    metadata_json = Column(Text, nullable=False)
    recorded_at = Column(DateTime, nullable=True)
    authorization_note = Column(String(1000), nullable=False)
    authorized_at = Column(DateTime, nullable=False)
    created_by = Column(Integer, ForeignKey("hoimsystem_users.user_id"), nullable=False)
    create_time = Column(DateTime, nullable=False, default=utcnow)
    status = Column(String(24), nullable=False, default="ready")
    revision = Column(Integer, nullable=False, default=1)
    withdrawn_by = Column(Integer, ForeignKey("hoimsystem_users.user_id"), nullable=True)
    withdrawn_at = Column(DateTime, nullable=True)
    withdrawal_note = Column(String(1000), nullable=False, default="")
    purged_by = Column(Integer, ForeignKey("hoimsystem_users.user_id"), nullable=True)
    purged_at = Column(DateTime, nullable=True)
    purge_note = Column(String(1000), nullable=False, default="")


class AIForecastSeries(Base):
    """Immutable attested registration window; revocation never rewrites its facts."""

    __tablename__ = "hoimsystem_ai_forecast_series"
    __table_args__ = (
        Index("idx_ai_forecast_scope_status", "scope", "department_id", "status"),
        Index("idx_ai_forecast_created", "create_time"),
    )

    series_id = Column(String(36), primary_key=True, default=new_id)
    name = Column(String(120), nullable=False)
    target = Column(String(48), nullable=False, default="registration_record_count")
    scope = Column(String(24), nullable=False)
    department_id = Column(Integer, ForeignKey("hoimsystem_department.department_id"), nullable=True)
    date_from = Column(Date, nullable=False)
    date_to = Column(Date, nullable=False)
    timezone = Column(String(100), nullable=False)
    time_basis = Column(String(40), nullable=False, default="naive_registration_time")
    source_json = Column(Text, nullable=False)
    content_hash = Column(String(64), nullable=False)
    registration_digest = Column(String(64), nullable=False)
    coverage_note = Column(String(2000), nullable=False)
    status = Column(String(24), nullable=False, default="active")
    revision = Column(Integer, nullable=False, default=1)
    created_by = Column(Integer, ForeignKey("hoimsystem_users.user_id"), nullable=False)
    create_time = Column(DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=False, default=utcnow)
    revoked_by = Column(Integer, ForeignKey("hoimsystem_users.user_id"), nullable=True)
    revoked_at = Column(DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=True)
    revoke_reason = Column(String(1000), nullable=False, default="")


class AIObservationWindow(Base):
    """Immutable UTC admission window; source changes invalidate ordinary use."""

    __tablename__ = "hoimsystem_ai_observation_window"
    __table_args__ = (
        CheckConstraint("start_at < end_at AND end_at <= as_of", name="ck_ai_observation_window_time"),
        CheckConstraint(
            "(status = 'active' AND revision = 1 AND revoked_at IS NULL AND revoked_by IS NULL AND revoke_reason = '') OR (status = 'revoked' AND revision = 2 AND revoked_at IS NOT NULL AND revoked_by IS NOT NULL AND revoke_reason <> '')",
            name="ck_ai_observation_window_governance",
        ),
        Index("idx_ai_observation_window_scope", "patient_id", "admission_id", "status"),
        Index("idx_ai_observation_window_created", "created_by", "created_at"),
    )

    window_id = Column(String(36), primary_key=True, default=new_id)
    patient_id = Column(Integer, ForeignKey("hoimsystem_patient.patient_id"), nullable=False)
    admission_id = Column(String(36), ForeignKey("hoimsystem_admission.admission_id"), nullable=False)
    created_by = Column(Integer, ForeignKey("hoimsystem_users.user_id"), nullable=False)
    created_at = Column(DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=False, default=utcnow)
    start_at = Column(DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=False)
    end_at = Column(DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=False)
    as_of = Column(DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=False)
    schema_version = Column(String(40), nullable=False, default="inpatient_window_v1")
    snapshot_json = Column(Text, nullable=False)
    content_hash = Column(String(64), nullable=False)
    status = Column(String(24), nullable=False, default="active")
    revision = Column(Integer, nullable=False, default=1)
    revoked_at = Column(DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=True)
    revoked_by = Column(Integer, ForeignKey("hoimsystem_users.user_id"), nullable=True)
    revoke_reason = Column(String(1000), nullable=False, default="")
