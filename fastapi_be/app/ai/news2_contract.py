"""Strict, identifier-minimized inputs for an independent NEWS2 implementation.

Rules: Royal College of Physicians, NEWS2 (2017), Charts 1 and 2, with the
2020 additional implementation guidance. This module reproduces no chart.
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
ComponentKey = Literal["respiratory_rate", "spo2", "systolic_bp", "pulse_rate", "temperature", "supplemental_oxygen", "consciousness"]
COMPONENT_KEYS = ("respiratory_rate", "spo2", "systolic_bp", "pulse_rate", "temperature", "supplemental_oxygen", "consciousness")
MEASUREMENT_UNITS = {"respiratory_rate": "/min", "spo2": "%", "systolic_bp": "mm[Hg]", "pulse_rate": "/min", "temperature": "Cel"}
RULE_REFERENCES = [
    "https://www.rcp.ac.uk/resources/national-early-warning-score-news-2/",
    "https://www.rcp.ac.uk/media/alxev00t/news2-chart-1_the-news-scoring-system_0_0.pdf",
    "https://www.rcp.ac.uk/media/2acdezkd/news2-chart-2_news-thresholds-and-triggers_0.pdf",
    "https://www.rcp.ac.uk/media/umzn4ntq/news2_additional-guidance-002-_0.pdf",
]
ATTRIBUTION = (
    "Royal College of Physicians. National Early Warning Score (NEWS) 2: Standardising the assessment of acute-illness severity in the NHS. "
    "Updated report of a working party. London: RCP, 2017. Independent software implementation; not certified or endorsed by the RCP."
)
RECIPE = {
    "rule_id": "news2_2017",
    "version": "news2_decimal_v1",
    "component_order": list(COMPONENT_KEYS),
    "bands": {
        "respiratory_rate": [[None, "8", 3], ["9", "11", 1], ["12", "20", 0], ["21", "24", 2], ["25", None, 3]],
        "spo2_scale1": [[None, "91", 3], ["92", "93", 2], ["94", "95", 1], ["96", None, 0]],
        "spo2_scale2_low": [[None, "83", 3], ["84", "85", 2], ["86", "87", 1], ["88", "92", 0]],
        "spo2_scale2_air_high": [["93", None, 0]],
        "spo2_scale2_oxygen_high": [["93", "94", 1], ["95", "96", 2], ["97", None, 3]],
        "systolic_bp": [[None, "90", 3], ["91", "100", 2], ["101", "110", 1], ["111", "219", 0], ["220", None, 3]],
        "pulse_rate": [[None, "40", 3], ["41", "50", 1], ["51", "90", 0], ["91", "110", 1], ["111", "130", 2], ["131", None, 3]],
        "temperature": [[None, "35.0", 3], ["35.1", "36.0", 1], ["36.1", "38.0", 0], ["38.1", "39.0", 1], ["39.1", None, 2]],
    },
    "oxygen": {"yes": 2, "no": 0, "unknown": None},
    "consciousness": {"ACVPU": {"alert": 0, "new_confusion": 3, "voice": 3, "pain": 3, "unresponsive": 3}, "AVPU": {"alert": None, "voice": 3, "pain": 3, "unresponsive": 3}},
    "input_precision": {"integer_value": ["respiratory_rate", "spo2", "systolic_bp", "pulse_rate"], "exact_tenth": ["temperature"], "rounding": "never"},
    "population": {"minimum_age_years": 16, "pregnant": "outside_scope", "pregnancy_unknown": "insufficient_data"},
    "scale2_requires": ["blood_gas_confirmed_hypercapnic_respiratory_failure", "documented_competent_clinical_decision", "target_88_92"],
    "same_time_relevant_conflicts": "block_aggregate",
    "scale2_high_spo2_oxygen_conflict": "block_dependent_spo2_component",
    "missing_components": "null_complete_total_keep_observed_components_and_red_flags",
    "partial_policy": {"declared_population_only": True, "observed_subtotal": "sum_scored_components_only", "zero_partial_minimum_classification": None, "not_an_official_complete_total": True},
    "unknown_population": "all_component_scores_and_subtotals_null",
    "classification_priority": ["high_at_least_7", "medium_5_6", "single_red_1_4", "zero_0", "low_1_4_without_red"],
    "prompt_handling": "provenance_only",
    "probabilities": "not_provided",
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
        raise ValueError("测量值须为有限普通十进制字符串，不自动转换、舍入或使用科学计数")
    return value


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class News2Measurement(StrictModel):
    value: str | None
    unit: str = Field(strict=True, min_length=1, max_length=16)
    absent_reason: Literal["unknown", "not_performed", "measurement_error"] | None

    @field_validator("value", mode="before")
    @classmethod
    def decimal_value(cls, value):
        return decimal_text(value) if value is not None else None

    @model_validator(mode="after")
    def explicit_presence(self):
        if (self.value is None) == (self.absent_reason is None):
            raise ValueError("原数值与未测原因须且只能提供一项")
        return self


class News2Consciousness(StrictModel):
    system: Literal["AVPU", "ACVPU"]
    code: Literal["alert", "new_confusion", "voice", "pain", "unresponsive"]

    @model_validator(mode="after")
    def explicit_code(self):
        if self.system == "AVPU" and self.code == "new_confusion":
            raise ValueError("新发混乱须明确使用ACVPU")
        return self


class News2Scale2Review(StrictModel):
    hypercapnic_respiratory_failure_confirmed: bool = Field(strict=True)
    clinical_decision_confirmed: bool = Field(strict=True)
    target_range: Literal["88-92"]
    blood_gas_reference_hash: SHA256
    clinical_decision_reference_hash: SHA256


class News2Source(StrictModel):
    assessment_id: str
    source_id: str
    content_hash: SHA256
    source_governance_hash: SHA256
    window_id: str
    window_source_id: str
    window_content_hash: SHA256
    as_of: str
    point_id: str
    point_source_id: str
    observed_at: str
    recorded_at: str
    rule_profile_id: str
    rule_profile_source_id: str
    rule_profile_content_hash: SHA256
    rule_profile_governance_hash: SHA256
    rule_id: Literal["news2_2017"]
    recipe_digest: SHA256
    age_at_observation_years: int = Field(strict=True, ge=0, le=130)
    pregnancy_status: Literal["not_pregnant", "pregnant", "unknown", "not_applicable"]
    spo2_scale: int = Field(strict=True, ge=1, le=2)
    scale2_review: News2Scale2Review | None
    measurements: dict[str, News2Measurement] = Field(max_length=5)
    supplemental_oxygen: Literal["yes", "no", "unknown"]
    consciousness: News2Consciousness | None
    conflict_codes: list[ComponentKey] = Field(max_length=7)

    _ids = field_validator("assessment_id", "window_id", "point_id", "rule_profile_id")(canonical_uuid)
    _clocks = field_validator("as_of", "observed_at", "recorded_at")(explicit_utc)

    @model_validator(mode="after")
    def fixed_binding(self):
        bindings = (
            (self.source_id, "news2_assessment", self.assessment_id, self.content_hash),
            (self.window_source_id, "observation_window", self.window_id, self.window_content_hash),
            (self.rule_profile_source_id, "risk_rule_profile", self.rule_profile_id, self.rule_profile_content_hash),
        )
        if any(source != f"{prefix}:{identifier}:{digest[:12]}" for source, prefix, identifier, digest in bindings):
            raise ValueError("NEWS2来源或规则身份绑定不一致")
        if re.fullmatch(re.escape("inpatient_observation:" + self.point_id + ":") + r"[a-f0-9]{12}", self.point_source_id) is None:
            raise ValueError("NEWS2原点测引用不一致")
        if self.recipe_digest != recipe_digest():
            raise ValueError("NEWS2固定规则版本不一致")
        if not datetime.fromisoformat(self.observed_at) <= datetime.fromisoformat(self.recorded_at) <= datetime.fromisoformat(self.as_of):
            raise ValueError("原点测发生/登记时刻须不晚于冻结截止")
        if len(set(self.conflict_codes)) != len(self.conflict_codes):
            raise ValueError("相关冲突字段不可重复")
        if set(self.measurements) - MEASUREMENT_UNITS.keys():
            raise ValueError("NEWS2不接受未定义指标或用heart_rate替代pulse_rate")
        for key, item in self.measurements.items():
            if item.unit != MEASUREMENT_UNITS[key]:
                raise ValueError("NEWS2原单位不一致，不自动换算")
            if item.value is not None:
                value = Decimal(item.value)
                if (key != "temperature" and value < 0) or (key == "spo2" and value > 100):
                    raise ValueError("NEWS2原数值超出源数据工程范围")
        if self.spo2_scale == 1 and self.scale2_review is not None:
            raise ValueError("Scale1不能夹带Scale2核实资料")
        return self


class News2Component(StrictModel):
    key: ComponentKey
    raw_value: str | None
    unit: str | None
    observed_at: str
    source_id: str
    score: int | None = Field(strict=True, ge=0, le=3)
    status: Literal["scored", "missing", "conflict", "outside_precision", "requires_review", "outside_scope"]
    reason: str = Field(min_length=1, max_length=160)


class News2Runtime(StrictModel):
    engine: Literal["stdlib-news2-rules"]
    rule_id: Literal["news2_2017"]
    recipe_digest: SHA256
    implementation: dict[str, SHA256] = Field(min_length=4, max_length=4)
    python_version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    engine_versions: dict[str, str] = Field(min_length=2, max_length=2)
    runtime_digest: SHA256
    model_version: str = Field(pattern=r"^news2:[a-f0-9]{64}$")
    prompt_handling: Literal["provenance_only"]
    clinical_validation: Literal["not_provided"]
    population_applicability: Literal["not_independently_verified"]
    independent_implementation: Literal[True]


class News2Analysis(StrictModel):
    schema_version: Literal["1"]
    source_binding: News2Source
    rule_id: Literal["news2_2017"]
    calculation_status: Literal["computed", "insufficient_data", "outside_scope"]
    scope_status: Literal["within_declared_scope", "unknown", "outside_scope"]
    components: list[News2Component] = Field(min_length=7, max_length=7)
    total_score: int | None = Field(strict=True, ge=0, le=20)
    observed_subtotal: int | None = Field(strict=True, ge=0, le=20)
    scored_component_count: int = Field(strict=True, ge=0, le=7)
    minimum_classification: Literal["zero", "low", "single_red", "medium", "high"] | None
    score_is_lower_bound: bool = Field(strict=True)
    red_flag_components: list[ComponentKey] = Field(max_length=6)
    classification: Literal["zero", "low", "single_red", "medium", "high"] | None
    missing_data: list[str]
    warnings: list[str]
    local_runtime: News2Runtime
    instructions_digest: SHA256
    attribution: str
    rule_references: list[str] = Field(min_length=4, max_length=4)
    independent_implementation: Literal[True]
    clinical_validation: Literal["not_provided"]
