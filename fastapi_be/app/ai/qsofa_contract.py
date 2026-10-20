"""Typed original bedside evidence for an independent adult qSOFA count.

This is a current retrospective clinical review, not a historical prediction or
a stand-alone sepsis screen. No hospital settings, database or patient records.
"""

import hashlib
import json
import re
import uuid
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SHA256 = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
CriterionKey = Literal["respiratory_rate", "systolic_bp", "mentation"]
PointKey = Literal["respiratory_rate", "systolic_bp"]
CRITERION_KEYS = ("respiratory_rate", "systolic_bp", "mentation")
MEASUREMENT_UNITS = {"respiratory_rate": "/min", "systolic_bp": "mm[Hg]"}
RULE_REFERENCES = [
    "https://jamanetwork.com/journals/jama/fullarticle/2492881",
    "https://jamanetwork.com/journals/jama/fullarticle/2492875",
    "https://www.sccm.org/survivingsepsiscampaign/guidelines-and-resources/surviving-sepsis-campaign-adult-guidelines",
    "https://www.glasgowcomascale.org/faq/",
]
ATTRIBUTION = (
    "Singer et al. JAMA 2016;315:801-810. doi:10.1001/jama.2016.0287; Seymour et al. JAMA 2016;315:762-774. "
    "doi:10.1001/jama.2016.0288. Independent qSOFA arithmetic implementation; not endorsed or certified by the authors, JAMA, SCCM or ESICM."
)
RECIPE = {
    "rule_id": "qsofa_sepsis3_2016",
    "version": "qsofa_original_decimal_same_exam_v1",
    "criterion_order": list(CRITERION_KEYS),
    "criteria": {
        "respiratory_rate": {"comparison": ">=", "threshold": "22", "unit": "/min", "met_score": 1, "not_met_score": 0},
        "systolic_bp": {"comparison": "<=", "threshold": "100", "unit": "mm[Hg]", "met_score": 1, "not_met_score": 0},
        "mentation": {"comparison": "<", "threshold": 15, "basis": "complete_measured_eye_verbal_motor_sum", "met_score": 1, "not_met_score": 0},
    },
    "population": {"minimum_age_years": 18, "care_setting": "non_icu", "infection_status": ["suspected", "documented"], "unknown": "no_scores"},
    "review": {"mode": "current_retrospective_review", "historical_prediction": False, "applies_to": "selected_point_observed_at", "recorded_at": "current_server_review_time"},
    "input_precision": {"numeric_values": "exact_original_decimal_strings", "rounding": "never", "unit_conversion": "never", "zero_is_not_missing": True},
    "source_policy": {
        "respiratory_and_pressure": "one_explicit_original_point_only",
        "gcs": "explicit_original_anchor_and_clinician_same_exam_confirmation",
        "gcs_clocks": "preserve_distinct_real_clocks_inside_window_and_available_by_as_of",
        "automatic_nearest_or_time_fusion": "never",
        "gcs_incomplete_or_nt_or_limited": "unknown_mentation_no_imputation_or_avpu_conversion",
        "same_anchor_gcs_conflict": "unknown_mentation",
        "point_conflicts": "block_only_dependent_criterion",
    },
    "partial_policy": {
        "total": "only_three_scored_in_confirmed_scope",
        "observed_subtotal": "sum_actual_scores_if_at_least_one_scored_else_null",
        "threshold": "at_least_two_if_known_subtotal_at_least_two_even_if_incomplete",
        "below_two": "only_complete_data_no_exclusion_or_reassurance",
        "unknown_scope": "all_scores_subtotal_and_total_null",
    },
    "usage": "bedside_evidence_count_not_sole_sepsis_screen_diagnosis_exclusion_probability_or_auto_treatment",
    "current_guidance": "SSC_2026_prefers_NEWS_NEWS2_MEWS_or_SIRS_over_qSOFA_as_single_sepsis_screen",
    "prompt_handling": "provenance_only",
    "clinical_validation": "not_provided",
}


def canonical_json(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def recipe_digest() -> str:
    return hashlib.sha256(canonical_json(RECIPE).encode()).hexdigest()


def canonical_uuid(value: str) -> str:
    if not isinstance(value, str) or str(uuid.UUID(value)) != value:
        raise ValueError("标识须为规范小写UUID")
    return value


def explicit_utc(value: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)", value) is None:
        raise ValueError("时刻须为带秒、最多6位小数秒的显式UTC ISO时间")
    if datetime.fromisoformat(value).utcoffset() != timedelta(0):
        raise ValueError("时刻须为UTC")
    return value


def decimal_text(value):
    if not isinstance(value, str) or re.fullmatch(r"-?(?:0|[1-9]\d{0,15})(?:\.\d{1,8})?", value) is None or not Decimal(value).is_finite():
        raise ValueError("原值须为有限普通十进制字符串，不转换、舍入或使用科学计数")
    return value


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class QsofaMeasurement(StrictModel):
    value: str | None
    unit: str = Field(strict=True, min_length=1, max_length=16)
    absent_reason: Literal["unknown", "not_performed", "measurement_error"] | None

    @field_validator("value", mode="before")
    @classmethod
    def original_decimal(cls, value):
        return decimal_text(value) if value is not None else None

    @model_validator(mode="after")
    def explicit_presence(self):
        if (self.value is None) == (self.absent_reason is None):
            raise ValueError("原数值与未测原因须且只能提供一项")
        return self


class QsofaGcsComponent(StrictModel):
    score: int | None = Field(strict=True, ge=1, le=6)
    absent_reason: Literal["not_testable", "not_recorded"] | None

    @model_validator(mode="after")
    def explicit_presence(self):
        if (self.score is None) == (self.absent_reason is None):
            raise ValueError("GCS原分项与NT/未登记原因须且只能提供一项")
        return self


class QsofaGcsComponents(StrictModel):
    eye: QsofaGcsComponent
    verbal: QsofaGcsComponent
    motor: QsofaGcsComponent

    @model_validator(mode="after")
    def exact_component_ranges(self):
        if (self.eye.score is not None and self.eye.score > 4) or (self.verbal.score is not None and self.verbal.score > 5):
            raise ValueError("GCS眼/言语/运动分项须分别在1..4/1..5/1..6内")
        return self


class QsofaGcs(StrictModel):
    gcs_observation_id: str
    source_id: str
    content_hash: SHA256
    governance_hash: SHA256
    schema_version: Literal["inpatient_gcs_v1"]
    observed_at: str
    recorded_at: str
    components: QsofaGcsComponents
    anchor_point_id: str
    anchor_point_source_id: str
    anchor_point_content_hash: SHA256
    same_exam_confirmed: Literal[True]
    same_exam_evidence_hash: SHA256
    conflict: bool = Field(strict=True)

    _ids = field_validator("gcs_observation_id", "anchor_point_id")(canonical_uuid)
    _clocks = field_validator("observed_at", "recorded_at")(explicit_utc)

    @field_validator("same_exam_confirmed", mode="before")
    @classmethod
    def actual_confirmation(cls, value):
        if value is not True:
            raise ValueError("必须显式确认原资料属于同次检查")
        return value

    @model_validator(mode="after")
    def source_binding(self):
        if self.source_id != f"gcs_observation:{self.gcs_observation_id}:{self.content_hash[:12]}":
            raise ValueError("GCS原来源与完整内容哈希绑定不一致")
        if self.anchor_point_source_id != f"inpatient_observation:{self.anchor_point_id}:{self.anchor_point_content_hash[:12]}":
            raise ValueError("GCS同次原点测绑定不一致")
        if datetime.fromisoformat(self.observed_at) > datetime.fromisoformat(self.recorded_at):
            raise ValueError("GCS实际发生时刻不能晚于原登记时刻")
        return self


class QsofaSource(StrictModel):
    assessment_id: str
    source_id: str
    content_hash: SHA256
    source_governance_hash: SHA256
    window_id: str
    window_source_id: str
    window_content_hash: SHA256
    start_at: str
    end_at: str
    as_of: str
    point_id: str
    point_source_id: str
    point_content_hash: SHA256
    point_governance_hash: SHA256
    observed_at: str
    recorded_at: str
    rule_profile_id: str
    rule_profile_source_id: str
    rule_profile_content_hash: SHA256
    rule_profile_governance_hash: SHA256
    rule_id: Literal["qsofa_sepsis3_2016"]
    recipe_digest: SHA256
    evaluation_at: str
    clinical_statements_recorded_at: str
    clinical_scope_applies_to: str
    review_mode: Literal["current_retrospective_review"]
    historical_prediction: Literal[False]
    age_at_observation_years: int | None = Field(strict=True, ge=0, le=130)
    care_setting: Literal["non_icu", "icu", "unknown"]
    infection_status: Literal["suspected", "documented", "not_suspected", "unknown"]
    scope_evidence_hash: SHA256
    measurements: dict[str, QsofaMeasurement] = Field(max_length=2)
    point_conflicts: list[PointKey] = Field(max_length=2)
    gcs: QsofaGcs | None
    gcs_interpretability: Literal["confirmed", "limited", "unknown"]
    gcs_review_evidence_hash: SHA256 | None

    _ids = field_validator("assessment_id", "window_id", "point_id", "rule_profile_id")(canonical_uuid)
    _clocks = field_validator("start_at", "end_at", "as_of", "observed_at", "recorded_at", "evaluation_at", "clinical_statements_recorded_at", "clinical_scope_applies_to")(explicit_utc)

    @field_validator("historical_prediction", mode="before")
    @classmethod
    def no_historical_prediction(cls, value):
        if value is not False:
            raise ValueError("当前回顾性临床核实不能冒称历史预测")
        return value

    @model_validator(mode="after")
    def fixed_binding(self):
        bindings = (
            (self.source_id, "qsofa_assessment", self.assessment_id, self.content_hash),
            (self.window_source_id, "observation_window", self.window_id, self.window_content_hash),
            (self.point_source_id, "inpatient_observation", self.point_id, self.point_content_hash),
            (self.rule_profile_source_id, "risk_rule_profile", self.rule_profile_id, self.rule_profile_content_hash),
        )
        if any(source != f"{prefix}:{identifier}:{digest[:12]}" for source, prefix, identifier, digest in bindings):
            raise ValueError("qSOFA原资料或规则来源绑定不一致")
        if self.recipe_digest != recipe_digest():
            raise ValueError("qSOFA固定实施规则版本不一致")
        clock = datetime.fromisoformat
        if not clock(self.start_at) <= clock(self.observed_at) <= clock(self.end_at) <= clock(self.as_of) <= clock(self.evaluation_at):
            raise ValueError("原点测须在原窗口内且不晚于截止，当前核实不能回填为历史预测")
        if not clock(self.observed_at) <= clock(self.recorded_at) <= clock(self.as_of):
            raise ValueError("原点测实际发生/登记时刻须不晚于原截止")
        if self.clinical_statements_recorded_at != self.evaluation_at or self.clinical_scope_applies_to != self.observed_at:
            raise ValueError("当前临床声明须绑定当前核实时刻与所选原点测实际时刻")
        if len(set(self.point_conflicts)) != len(self.point_conflicts):
            raise ValueError("相关原点测冲突不可重复")
        if set(self.measurements) - MEASUREMENT_UNITS.keys():
            raise ValueError("qSOFA只接受所选原点测的呼吸频率与收缩压")
        for key, item in self.measurements.items():
            if item.unit != MEASUREMENT_UNITS[key] or (item.value is not None and Decimal(item.value) < 0):
                raise ValueError("qSOFA须保持非负原值与精确原单位，不自动换算")
        if self.gcs is None:
            if self.gcs_interpretability != "unknown" or self.gcs_review_evidence_hash is not None:
                raise ValueError("未选择GCS时不得确认其可判读或夹带核实依据")
        else:
            gcs = self.gcs
            if self.gcs_review_evidence_hash is None:
                raise ValueError("选定GCS须保留显式临床判读核实依据哈希")
            if (gcs.anchor_point_id, gcs.anchor_point_source_id, gcs.anchor_point_content_hash) != (self.point_id, self.point_source_id, self.point_content_hash):
                raise ValueError("选定GCS必须显式锚定同一原点测与完整哈希")
            if not clock(self.start_at) <= clock(gcs.observed_at) <= clock(self.end_at) or clock(gcs.recorded_at) > clock(self.as_of):
                raise ValueError("GCS原实际时刻须在窗口内，原登记不能晚于截止")
        return self


class QsofaCriterion(StrictModel):
    key: CriterionKey
    raw_value: str | None
    unit: str | None
    observed_at: str | None
    source_ids: list[str] = Field(min_length=1, max_length=2)
    score: int | None = Field(strict=True, ge=0, le=1)
    status: Literal["scored", "missing", "conflict", "requires_review", "outside_scope"]
    reason: str = Field(min_length=1, max_length=160)


class QsofaRuntime(StrictModel):
    engine: Literal["stdlib-qsofa-rules"]
    rule_id: Literal["qsofa_sepsis3_2016"]
    recipe_digest: SHA256
    implementation: dict[str, SHA256] = Field(min_length=4, max_length=4)
    python_version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    engine_versions: dict[str, str] = Field(min_length=2, max_length=2)
    runtime_digest: SHA256
    model_version: str = Field(pattern=r"^qsofa:[a-f0-9]{64}$")
    prompt_handling: Literal["provenance_only"]
    clinical_validation: Literal["not_provided"]
    population_applicability: Literal["not_independently_verified"]
    independent_implementation: Literal[True]


class QsofaAnalysis(StrictModel):
    schema_version: Literal["1"]
    source_binding: QsofaSource
    rule_id: Literal["qsofa_sepsis3_2016"]
    calculation_status: Literal["computed", "insufficient_data", "outside_scope"]
    scope_status: Literal["confirmed", "unknown", "outside_scope"]
    criteria: list[QsofaCriterion] = Field(min_length=3, max_length=3)
    total_score: int | None = Field(strict=True, ge=0, le=3)
    observed_subtotal: int | None = Field(strict=True, ge=0, le=3)
    scored_count: int = Field(strict=True, ge=0, le=3)
    score_is_lower_bound: bool = Field(strict=True)
    threshold_status: Literal["at_least_two", "below_two_in_complete_data", "unknown"]
    diagnosis_provided: Literal[False]
    probability_provided: Literal[False]
    missing_data: list[str]
    warnings: list[str]
    local_runtime: QsofaRuntime
    instructions_digest: SHA256
    attribution: str
    rule_references: list[str] = Field(min_length=4, max_length=4)
    independent_implementation: Literal[True]
    clinical_validation: Literal["not_provided"]

    @field_validator("diagnosis_provided", "probability_provided", mode="before")
    @classmethod
    def no_diagnosis_or_probability(cls, value):
        if value is not False:
            raise ValueError("固定核对器不提供诊断或概率")
        return value
