"""Strict request and result contracts for AI management and execution."""

import datetime
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.ai.references import SOURCE_REFERENCE_KEYS


class StrictRequest(BaseModel):
    """Reject unrecognized fields instead of silently accepting unsafe overrides."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ReviewExcerptWrite(StrictRequest):
    """Create a new immutable text version against a freshly inspected source."""

    review_id: int = Field(ge=1, strict=True)
    expected_source_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    redacted_text: str = Field(min_length=3, max_length=1000)
    change_note: str = Field(min_length=3, max_length=1000)


class ReviewExcerptReview(StrictRequest):
    expected_revision: int = Field(ge=1, strict=True)
    status: Literal["published", "rejected", "retired"]
    privacy_checked: bool = False
    faithfulness_checked: bool = False
    review_note: str = Field(min_length=3, max_length=1000)


class ProviderWrite(StrictRequest):
    """A provider secret is write-only; updates require the current revision."""

    name: str = Field(min_length=1, max_length=80)
    kind: Literal["chat", "responses", "specialist"] = "chat"
    api_base: str = Field(min_length=1, max_length=1000)
    model: str = Field(min_length=1, max_length=160)
    api_key: str | None = Field(default=None, max_length=4000)
    api_key_env: str = Field(default="", max_length=100, pattern=r"^[A-Za-z_][A-Za-z0-9_]*$|^$")
    clear_api_key: bool = False
    enabled: bool = False
    allows_patient_data: bool = False
    timeout_seconds: int = Field(default=30, ge=3, le=120)
    max_output_tokens: int = Field(default=2000, ge=256, le=16000)
    temperature: float = Field(default=0.2, ge=0, le=1, allow_inf_nan=False)
    supported_features: list[str] = Field(default_factory=list, max_length=80)
    validation_report: str = Field(default="", max_length=5000)
    expected_revision: int = Field(default=0, ge=0)

    @field_validator("api_key_env")
    @classmethod
    def designated_credential_variable(cls, value: str) -> str:
        """Model configuration must not exfiltrate unrelated deployment secrets."""
        if value and value != "OPENAI_API_KEY" and not re.fullmatch(r"AI_(?:MODEL|PROVIDER_[A-Z0-9_]+)_API_KEY", value):
            raise ValueError("仅允许引用 AI_MODEL_API_KEY、AI_PROVIDER_<名称>_API_KEY 或 OPENAI_API_KEY")
        return value


class ProviderCheck(StrictRequest):
    expected_revision: int = Field(ge=1, strict=True)


class FeatureWrite(StrictRequest):
    """Update activation without conflating configuration with clinical validation."""

    expected_revision: int = Field(ge=0)
    enabled: bool | None = None
    provider_id: int | None = Field(default=None, ge=1)
    allowed_roles: list[str] | None = Field(default=None, min_length=1, max_length=11)
    validation_status: Literal["unreviewed", "pilot", "validated", "suspended"] | None = None
    validation_note: str | None = Field(default=None, max_length=5000)
    daily_limit: int | None = Field(default=None, ge=1, le=10000)


class PromptWrite(StrictRequest):
    """Create a new immutable revision, optionally activating it."""

    expected_revision: int = Field(ge=0)
    task_prompt: str = Field(min_length=30, max_length=20000)
    change_note: str = Field(min_length=3, max_length=1000)
    activate: bool = False


class PromptActivate(StrictRequest):
    """A null prompt selects the packaged baseline version zero."""

    expected_revision: int = Field(ge=0)
    prompt_id: str | None = Field(default=None, max_length=36)


class KnowledgeWrite(StrictRequest):
    """A knowledge version is immutable after creation; publication is separate."""

    title: str = Field(min_length=2, max_length=200)
    version: str = Field(min_length=1, max_length=80)
    source_uri: str = Field(min_length=3, max_length=2000)
    category: Literal["clinical", "drug", "hospital", "operations", "training"] = "clinical"
    content: str = Field(min_length=20, max_length=200000)
    feature_keys: list[str] = Field(min_length=1, max_length=80)
    department_id: int | None = Field(default=None, ge=1)
    effective_from: datetime.datetime | None = None
    effective_to: datetime.datetime | None = None

    @field_validator("source_uri")
    @classmethod
    def reserve_bound_pathway_sources(cls, value: str) -> str:
        if value.lower().startswith("hoim://clinical-pathway/"):
            raise ValueError("院内路径来源须通过路径快照导入，不能手工填写来源地址")
        return value

    @field_validator("effective_from", "effective_to")
    @classmethod
    def normalize_utc(cls, value: datetime.datetime | None) -> datetime.datetime | None:
        """Normalize explicit offsets before database comparisons."""
        if value and value.tzinfo:
            return value.astimezone(datetime.UTC).replace(tzinfo=None)
        return value


class KnowledgeReview(StrictRequest):
    """Publishing requires the exact content hash seen by the reviewer."""

    content_hash: str = Field(min_length=64, max_length=64)
    status: Literal["published", "retired"]


class PathwayKnowledgeImport(StrictRequest):
    expected_source_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    feature_keys: list[str] = Field(default_factory=lambda: ["treatment_pathway", "response_review"], min_length=1, max_length=80)
    department_id: int | None = Field(default=None, ge=1, strict=True)
    effective_from: datetime.datetime | None = None
    effective_to: datetime.datetime | None = None

    @field_validator("effective_from", "effective_to")
    @classmethod
    def normalize_utc(cls, value: datetime.datetime | None):
        if value and value.tzinfo:
            return value.astimezone(datetime.UTC).replace(tzinfo=None)
        return value


class AudioAssetAction(StrictRequest):
    expected_revision: int = Field(ge=1, strict=True)
    reason: str = Field(min_length=5, max_length=1000)


class PatientGrantWrite(StrictRequest):
    """Grant narrowly scoped and expiring patient access."""

    user_id: int = Field(ge=1)
    patient_id: int = Field(ge=1)
    category: str = Field(min_length=1, max_length=40)
    reason: str = Field(min_length=5, max_length=500)
    expires_at: datetime.datetime

    @field_validator("expires_at")
    @classmethod
    def normalize_utc(cls, value: datetime.datetime) -> datetime.datetime:
        """Normalize offsets for expiring access checks."""
        return value.astimezone(datetime.UTC).replace(tzinfo=None) if value.tzinfo else value


class ClinicalContextRequest(StrictRequest):
    """Inspect bounded server-owned references without creating an inference request."""

    feature_key: str = Field(min_length=1, max_length=64)
    patient_id: int = Field(ge=1)
    encounter_ref: str | None = Field(default=None, max_length=64)
    source_refs: dict[str, str] = Field(default_factory=dict, max_length=12)

    @field_validator("source_refs")
    @classmethod
    def supported_references(cls, value: dict) -> dict:
        if set(value) - SOURCE_REFERENCE_KEYS or any(not item.strip() or len(item) > 50 for item in value.values()):
            raise ValueError("资料引用类型或标识无效")
        return value


class OperationalContextRequest(StrictRequest):
    """Inspect scope and facts without credentials, provider configuration or an inference task."""

    feature_key: str = Field(min_length=1, max_length=64)
    input: dict[str, Any] = Field(default_factory=dict)


class RunRequest(StrictRequest):
    """Business input cannot choose providers, system instructions or evidence IDs."""

    feature_key: str = Field(min_length=1, max_length=64)
    patient_id: int | None = Field(default=None, ge=1)
    encounter_ref: str | None = Field(default=None, max_length=64)
    input: dict[str, Any] = Field(default_factory=dict)
    preview: bool = False


class ResultSection(StrictRequest):
    """Render plain text and server-resolved citation IDs, never model HTML."""

    title: str = Field(min_length=1, max_length=120)
    content: str = Field(max_length=12000)
    source_ids: list[str] = Field(default_factory=list, max_length=30)


class GenerationResult(StrictRequest):
    """Bound and validate model output before persistence or presentation."""

    summary: str = Field(min_length=1, max_length=4000)
    sections: list[ResultSection] = Field(max_length=30)
    warnings: list[str] = Field(default_factory=list, max_length=50)
    missing_data: list[str] = Field(default_factory=list, max_length=100)

    @field_validator("warnings", "missing_data")
    @classmethod
    def bound_items(cls, value: list[str]) -> list[str]:
        """Prevent unbounded text hidden inside a short list."""
        if any(len(item) > 2000 for item in value):
            raise ValueError("列表项过长")
        return value


class AudioSegment(StrictRequest):
    start_ms: int = Field(ge=0, strict=True)
    end_ms: int = Field(ge=1, strict=True)
    speaker: str = Field(pattern=r"^(unknown|speaker_[1-9][0-9]{0,2})$")
    speaker_role: Literal["unknown"] = "unknown"
    text: str = Field(min_length=1, max_length=2000)
    uncertain: bool = Field(strict=True)
    uncertainty_note: str = Field(default="", max_length=500)
    source_id: str = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def interval_and_uncertainty(self):
        if self.end_ms <= self.start_ms or (self.uncertain and not self.uncertainty_note):
            raise ValueError("转写区间及不确定片段的说明不完整")
        return self


class AudioProcessing(StrictRequest):
    """Recognizer-reported input coverage and immutable runtime identity, not word accuracy."""

    engine: Literal["faster-whisper"]
    engine_version: str = Field(min_length=1, max_length=40)
    model_revision: str = Field(pattern=r"^[a-f0-9]{40}$")
    model_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    runtime_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    decoding_options_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    instructions_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    decoded_duration_ms: int = Field(gt=0, strict=True)
    processed_duration_ms: int = Field(gt=0, strict=True)
    submitted_samples: int = Field(gt=0, strict=True)
    sample_rate: int = Field(ge=16000, le=16000, strict=True)
    iterator_exhausted: bool = Field(strict=True)
    vad_filter: bool = Field(strict=True)
    translation: bool = Field(strict=True)
    diarization: bool = Field(strict=True)
    prompt_handling: Literal["acoustic_only"]
    timestamp_policy: Literal["estimated_bounded_to_source"]

    @model_validator(mode="after")
    def whole_input_processed(self):
        actual_ms = (self.submitted_samples * 1000 + self.sample_rate - 1) // self.sample_rate
        if not self.iterator_exhausted or self.translation or self.diarization or self.processed_duration_ms != self.decoded_duration_ms or actual_ms != self.decoded_duration_ms:
            raise ValueError("本地转写处理范围不完整或声明与输入样本不一致")
        return self


class AudioTranscript(StrictRequest):
    asset_id: str = Field(min_length=36, max_length=36)
    content_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    time_basis: Literal["relative_decoded_audio"]
    speech_detected: bool = Field(strict=True)
    language: str = Field(min_length=1, max_length=40)
    segments: list[AudioSegment] = Field(max_length=1000)
    processing: AudioProcessing | None = None

    @model_validator(mode="after")
    def speech_and_segments(self):
        if bool(self.segments) != self.speech_detected:
            raise ValueError("是否检出语音与原分段结果不一致")
        return self


class AudioGenerationResult(GenerationResult):
    transcription: AudioTranscript


class FeedbackWrite(StrictRequest):
    """Record clinician/user review without issuing business mutations."""

    outcome: Literal["accepted", "rejected", "modified"]
    comment: str = Field(default="", max_length=2000)
