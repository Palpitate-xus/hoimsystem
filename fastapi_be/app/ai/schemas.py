"""Strict request and result contracts for AI management and execution."""

import datetime
import re
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.ai.aki_contract import AkiAnalysis
from app.ai.forecast_contract import ForecastAnalysis
from app.ai.news2_contract import News2Analysis
from app.ai.qsofa_contract import QsofaAnalysis
from app.ai.references import SOURCE_REFERENCE_KEYS
from app.ai.roster_contract import RosterAnalysis
from app.ai.sofa_contract import SofaAnalysis, SofaChangeAnalysis


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
        if value.lower().startswith("hoim://document-evidence/"):
            raise ValueError("原文证据来源须由已审核摘录发布，不能手工填写来源地址")
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


class ECGAssetAction(AudioAssetAction):
    """Versioned raw-waveform withdrawal and explicit super-admin purge reason."""


class ImageAssetAction(AudioAssetAction):
    """Versioned private image withdrawal and super-admin purge reason."""


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

    @model_validator(mode="before")
    @classmethod
    def native_charge_scope(cls, value):
        if isinstance(value, dict) and isinstance(value.get("source_refs"), dict) and "charge_case_id" in value["source_refs"]:
            if type(value.get("patient_id")) is not int or value["patient_id"] < 1:
                raise ValueError("完整账目来源须使用真实正整数患者ID，不接受布尔、字符串或浮点转换")
        if isinstance(value, dict) and isinstance(value.get("source_refs"), dict) and "research_cohort_case_id" in value["source_refs"]:
            raise ValueError("科研来源使用独立有限Case，不使用患者临床上下文替代研究授权")
        if isinstance(value, dict) and isinstance(value.get("source_refs"), dict) and "operations_case_id" in value["source_refs"]:
            raise ValueError("运维审核资料使用专用有限Case，不接受患者临床上下文替代范围")
        return value

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

    @model_validator(mode="before")
    @classmethod
    def native_charge_scope(cls, value):
        if isinstance(value, dict) and isinstance(value.get("feature_key"), str) and value["feature_key"].strip() == "operations_support":
            if value.get("patient_id") is not None or value.get("encounter_ref") is not None:
                raise ValueError("运维任务只使用明确受审资料集，不接受患者或就诊范围")
            if "preview" in value and type(value["preview"]) is not bool:
                raise ValueError("运维预览标记须为明确布尔值")
        if isinstance(value, dict) and isinstance(value.get("feature_key"), str) and value["feature_key"].strip() == "research_cohort":
            if value.get("patient_id") is not None or value.get("encounter_ref") is not None:
                raise ValueError("科研任务只使用明确研究Case，不接受患者或就诊替代范围")
            if "preview" in value and type(value["preview"]) is not bool:
                raise ValueError("科研任务预览标记须为明确布尔值")
        if isinstance(value, dict) and isinstance(value.get("feature_key"), str) and value["feature_key"].strip() == "feedback_analysis":
            if value.get("patient_id") is not None or value.get("encounter_ref") is not None:
                raise ValueError("完整评价任务不接受患者或就诊范围")
            if "preview" in value and type(value["preview"]) is not bool:
                raise ValueError("完整评价任务的预览状态须为布尔值")
        if isinstance(value, dict) and value.get("feature_key") == "charge_reconciliation":
            if type(value.get("patient_id")) is not int or value["patient_id"] < 1:
                raise ValueError("完整账目任务须使用真实正整数患者ID，不接受布尔、字符串或浮点转换")
            if "preview" in value and type(value["preview"]) is not bool:
                raise ValueError("完整账目任务的预览状态须为布尔值")
        return value

    @field_validator("preview", mode="before")
    @classmethod
    def exact_drug_label_preview_flag(cls, value, info):
        if info.data.get("feature_key") == "drug_label_extraction" and type(value) is not bool:
            raise ValueError("说明书任务预览标记须为明确布尔值")
        return value

    @model_validator(mode="after")
    def dedicated_roster_reference(self):
        if "operations_case_id" in self.input and self.feature_key != "operations_support":
            raise ValueError("运维受审资料集只用于运维知识任务")
        if self.feature_key == "operations_support":
            from app.ai.operations_support_task_contract import OperationsTaskSelection

            OperationsTaskSelection.model_validate(self.input, strict=True)
        if "research_cohort_case_id" in self.input and self.feature_key != "research_cohort":
            raise ValueError("完整研究Case仅用于固定研究队列原记录核对")
        if self.feature_key == "research_cohort":
            from fastapi import HTTPException

            from app.ai.research_cohort_runtime import selection

            try:
                selection(self.input)
            except HTTPException as exc:
                if exc.status_code != 422:
                    raise
                raise ValueError(exc.detail) from exc
        if "drug_label_source_binding_id" in self.input and self.feature_key != "drug_label_extraction":
            raise ValueError("完整说明书来源仅用于说明书逐字字段复核")
        if self.feature_key == "drug_label_extraction":
            from app.ai.drug_label_context_contract import selection

            selection(self.input)
            if self.patient_id is not None or self.encounter_ref is not None:
                raise ValueError("说明书任务不接受患者或就诊范围")
        if "document_change_scope_id" in self.input and self.feature_key != "guideline_change_review":
            raise ValueError("双原文有限范围仅用于版本逐字问题核对")
        if "document_original_id" in self.input and self.feature_key != "guideline_ingestion":
            raise ValueError("原文摘录引用仅用于指南原文提取")
        if self.feature_key == "guideline_change_review":
            from app.ai.document_change_view_contract import DocumentChangeRequest

            DocumentChangeRequest.model_validate(self.input)
            if self.patient_id is not None or self.encounter_ref is not None:
                raise ValueError("版本核对不接受患者或就诊引用")
        if "roster_plan_id" in self.input and self.feature_key != "roster_optimization":
            raise ValueError("受审排班计划仅用于排班与号源优化")
        if "bed_series_id" in self.input and self.feature_key != "bed_forecast":
            raise ValueError("受审床位序列仅用于病区实占及流转事件预测")
        if "surgery_scenario_id" in self.input and self.feature_key != "surgery_scheduling":
            raise ValueError("受审手术场景仅用于明确病例与共享阶段资源排程")
        if "supply_series_id" in self.input and self.feature_key != "supply_forecast":
            raise ValueError("受审物资原量序列仅用于单品种申请、实际发出与确认消耗预测")
        if "inventory_scenario_id" in self.input and self.feature_key != "inventory_optimization":
            raise ValueError("受审完整库存场景仅用于明确有限采购候选比较")
        if "coding_case_id" in self.input and self.feature_key != "drg_evidence_review":
            raise ValueError("完整编码证据快照仅用于单次住院病案编码证据核对")
        if "charge_case_id" in self.input and self.feature_key != "charge_reconciliation":
            raise ValueError("完整账目原件仅用于同次实际住院的收费记录核对")
        if "satisfaction_case_id" in self.input and self.feature_key != "feedback_analysis":
            raise ValueError("受审完整评价原件仅用于满意度与评价证据分析")
        return self


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


class LocalECGRuntime(StrictRequest):
    """The fixed research classifier's actual runtime; no clinical validation inference."""

    engine: Literal["ssl-ecg-cnn"]
    engine_versions: dict[str, str] = Field(min_length=3, max_length=3)
    model_repository: Literal["Tumo505/SSL-ECG-Classification-model-card"]
    model_revision: Literal["6ec2ee1a1badd9508f9c1219fb07de38f3f6936b"]
    model_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    runtime_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    preprocessing_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    required_leads: list[str] = Field(min_length=12, max_length=12)
    sample_rate_hz: int = Field(ge=100, le=100, strict=True)
    samples_per_lead: int = Field(ge=1000, le=1000, strict=True)
    labels: list[str] = Field(min_length=5, max_length=5)
    missing_sample_policy: Literal["reject"]
    prompt_handling: Literal["signal_only"]
    clinical_validation: Literal["not_provided"]
    population_applicability: Literal["not_verified"]

    @model_validator(mode="after")
    def reviewed_runtime_only(self):
        from app.ai.ecg_model import LABELS, LEADS

        if (
            self.required_leads != LEADS
            or self.labels != LABELS
            or set(self.engine_versions) != {"torch", "numpy", "safetensors"}
            or self.engine_versions.get("torch") != "2.14.1+cpu"
            or self.engine_versions.get("safetensors") != "0.8.0"
            or any(not re.fullmatch(r"[0-9A-Za-z.+_-]{1,40}", version) for version in self.engine_versions.values())
        ):
            raise ValueError("本地研究模型的原导联、标签或运行依赖不一致")
        return self


class ECGProcessing(StrictRequest):
    instructions_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    input_sample_count: int = Field(ge=1, strict=True)
    input_sample_rate_hz: str = Field(min_length=1, max_length=40)
    input_leads: list[str] = Field(min_length=1, max_length=16)
    used_leads: list[str] = Field(min_length=1, max_length=16)
    processed_original_sample_count: int = Field(ge=1, strict=True)
    complete_input: bool = Field(strict=True)
    missing_sample_handling: Literal["none_present", "masked"]
    preprocessing_notes: list[str] = Field(max_length=20)
    local_runtime: LocalECGRuntime | None = None

    @model_validator(mode="after")
    def bounded_complete_input(self):
        if (
            not self.complete_input
            or self.processed_original_sample_count != self.input_sample_count
            or len(set(self.input_leads)) != len(self.input_leads)
            or len(set(self.used_leads)) != len(self.used_leads)
        ):
            raise ValueError("原始输入处理不完整或导联声明重复")
        if not set(self.used_leads) <= set(self.input_leads) or any(len(item) > 1000 for item in self.preprocessing_notes):
            raise ValueError("使用导联或预处理说明无效")
        return self


class ECGFinding(StrictRequest):
    category: Literal["signal_quality", "rhythm", "conduction", "morphology", "other"]
    label: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=4000)
    leads: list[str] = Field(min_length=1, max_length=16)
    location: Literal["recording", "sample_interval"]
    start_sample: int | None = Field(default=None, ge=0, strict=True)
    end_sample_exclusive: int | None = Field(default=None, ge=1, strict=True)
    score: float | None = Field(default=None, allow_inf_nan=False, strict=True)
    score_kind: Literal["model_score"] = "model_score"
    source_id: str = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def explicit_location(self):
        if len(set(self.leads)) != len(self.leads):
            raise ValueError("候选导联不能重复")
        if self.location == "recording":
            if self.start_sample is not None or self.end_sample_exclusive is not None:
                raise ValueError("全记录候选不能伪造精确采样定位")
        elif self.start_sample is None or self.end_sample_exclusive is None or self.end_sample_exclusive <= self.start_sample:
            raise ValueError("采样定位须提供明确的开始与结束样本")
        return self


class ECGAnalysis(StrictRequest):
    asset_id: str = Field(min_length=36, max_length=36)
    content_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    signal_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    time_basis: Literal["relative_samples"]
    processing: ECGProcessing
    findings: list[ECGFinding] = Field(max_length=100)


class ECGGenerationResult(GenerationResult):
    ecg_analysis: ECGAnalysis


class ImageRegion(StrictRequest):
    """Half-open rectangle in the unrotated original row/column pixel matrix."""

    x: int = Field(ge=0, strict=True)
    y: int = Field(ge=0, strict=True)
    width: int = Field(ge=1, strict=True)
    height: int = Field(ge=1, strict=True)


class LocalImagingRuntime(StrictRequest):
    engine: Literal["torchxrayvision-densenet121"]
    engine_versions: dict[str, str] = Field(min_length=3, max_length=3)
    model_repository: Literal["torchxrayvision/densenet121-res224-all"]
    model_revision: Literal["588eadcc6a744da71f8dce768bc974ec629443f5"]
    model_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    runtime_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    preprocessing_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    profile: Literal["xrv_stored_range_v1"]
    preprocessing: dict
    labels: list[str] = Field(min_length=18, max_length=18)
    prompt_handling: Literal["pixels_only"]
    clinical_validation: Literal["not_provided"]
    population_applicability: Literal["not_verified"]

    @model_validator(mode="after")
    def reviewed_runtime_only(self):
        import hashlib

        from app.ai.imaging_model import LABELS, canonical_json
        from app.ai.imaging_preprocessing import PREPROCESSING

        if self.labels != LABELS or self.engine_versions != {"torch": "2.14.1+cpu", "numpy": "2.4.4", "safetensors": "0.8.0"}:
            raise ValueError("胸片研究模型标签顺序或固定CPU依赖不一致")
        if canonical_json(self.preprocessing) != canonical_json(PREPROCESSING) or self.preprocessing_digest != hashlib.sha256(canonical_json(PREPROCESSING).encode()).hexdigest():
            raise ValueError("胸片研究模型预处理与已审查固定profile不一致")
        return self


class LocalImagePreprocessing(StrictRequest):
    normalization_maxval: int = Field(ge=255, le=65535, strict=True)
    input_pixel_count: int = Field(ge=1, le=16777216, strict=True)
    cropped_pixel_count: int = Field(ge=1, le=16777216, strict=True)
    discarded_pixel_count: int = Field(ge=0, le=16777216, strict=True)
    padding_pixels_in_input: int = Field(ge=0, le=16777216, strict=True)
    padding_pixels_in_crop: int = Field(ge=0, le=16777216, strict=True)
    valid_pixels_in_crop: int = Field(ge=1, le=16777216, strict=True)
    prepared_shape: list[Annotated[int, Field(strict=True)]] = Field(min_length=4, max_length=4)
    prepared_min: float = Field(ge=-1024.01, le=1024.01, allow_inf_nan=False, strict=True)
    prepared_max: float = Field(ge=-1024.01, le=1024.01, allow_inf_nan=False, strict=True)

    @model_validator(mode="after")
    def actual_counts(self):
        if self.prepared_shape != [1, 1, 224, 224] or self.prepared_min > self.prepared_max:
            raise ValueError("胸片模型输入形状或实际范围无效")
        if self.cropped_pixel_count + self.discarded_pixel_count != self.input_pixel_count or self.valid_pixels_in_crop + self.padding_pixels_in_crop != self.cropped_pixel_count:
            raise ValueError("实际裁剪、舍弃及填充像素数量不一致")
        if self.padding_pixels_in_crop > self.padding_pixels_in_input or self.padding_pixels_in_input > self.input_pixel_count:
            raise ValueError("填充像素数量不符合原输入范围")
        return self


class ImageProcessing(StrictRequest):
    instructions_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    input_rows: int = Field(ge=1, strict=True)
    input_columns: int = Field(ge=1, strict=True)
    input_frames: int = Field(ge=1, le=1, strict=True)
    processed_frames: list[Annotated[int, Field(strict=True)]] = Field(min_length=1, max_length=1)
    analysis_region: ImageRegion
    preprocessing_notes: list[str] = Field(min_length=1, max_length=20)
    local_runtime: LocalImagingRuntime | None = None
    local_preprocessing: LocalImagePreprocessing | None = None

    @model_validator(mode="after")
    def original_region(self):
        r = self.analysis_region
        if self.processed_frames != [0] or r.x + r.width > self.input_columns or r.y + r.height > self.input_rows or any(len(item) > 1000 for item in self.preprocessing_notes):
            raise ValueError("影像实际处理范围超出原像素或缺少明确预处理说明")
        return self


class ImageFinding(StrictRequest):
    label: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=4000)
    location: Literal["image", "bounding_box"]
    region: ImageRegion | None = None
    score: float | None = Field(default=None, allow_inf_nan=False, strict=True)
    score_kind: Literal["model_score"] = "model_score"
    source_id: str = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def explicit_location(self):
        if (self.location == "bounding_box") != (self.region is not None):
            raise ValueError("仅真实定位模型可提供原像素矩形，图像级分类不伪造定位")
        return self


class ImageAnalysis(StrictRequest):
    asset_id: str = Field(min_length=36, max_length=36)
    content_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    original_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    pixel_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    coordinate_space: Literal["source_pixels"]
    processing: ImageProcessing
    findings: list[ImageFinding] = Field(max_length=100)


class ImageGenerationResult(GenerationResult):
    image_analysis: ImageAnalysis


class ForecastGenerationResult(GenerationResult):
    forecast_analysis: ForecastAnalysis


class News2GenerationResult(GenerationResult):
    news2_analysis: News2Analysis


class AkiGenerationResult(GenerationResult):
    aki_analysis: AkiAnalysis


class QsofaGenerationResult(GenerationResult):
    qsofa_analysis: QsofaAnalysis


class SofaGenerationResult(GenerationResult):
    sofa_analysis: SofaAnalysis


class SofaChangeGenerationResult(GenerationResult):
    sofa_change_analysis: SofaChangeAnalysis


class RosterGenerationResult(GenerationResult):
    roster_analysis: RosterAnalysis


class FeedbackWrite(StrictRequest):
    """Record clinician/user review without issuing business mutations."""

    outcome: Literal["accepted", "rejected", "modified"]
    comment: str = Field(default="", max_length=2000)
