"""Strict minimized adult KDIGO 2012 inputs; no hospital imports or chart copy."""

import hashlib
import json
import re
import uuid
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SHA256 = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
CriterionKey = Literal["creatinine_48h", "creatinine_ratio_7d", "creatinine_absolute_stage3", "urine_6h", "urine_12h", "urine_24h", "anuria_12h", "acute_rrt"]
CRITERION_KEYS = ("creatinine_48h", "creatinine_ratio_7d", "creatinine_absolute_stage3", "urine_6h", "urine_12h", "urine_24h", "anuria_12h", "acute_rrt")
CoverageIssue = Literal["unselected_active_interval", "overlap", "gap", "partial_collection", "unknown_volume", "not_patient_total"]
COVERAGE_ISSUES = ("unselected_active_interval", "overlap", "gap", "partial_collection", "unknown_volume", "not_patient_total")
RULE_REFERENCES = [
    "https://kdigo.org/guidelines/acute-kidney-injury/",
    "https://kdigo.org/wp-content/uploads/2016/10/KDIGO-2012-AKI-Guideline-English.pdf",
    "https://kdigo.org/ufaq/how-can-i-implement-kdigo-guidelines-in-my-practice/",
    "https://kdigo.org/ufaq/who-should-i-contact-for-permissions-and-copyright-requests/",
]
ATTRIBUTION = (
    "Kidney Disease: Improving Global Outcomes (KDIGO) Acute Kidney Injury Work Group. KDIGO Clinical Practice Guideline for Acute Kidney Injury. "
    "Kidney International Supplements. 2012;2:1-138. Independent software implementation of supplied-data criteria; not certified or endorsed by KDIGO. No official chart reproduced."
)
INPUT_POLICY = {
    "population": "declared_adult_at_least_18_no_pediatric_egfr",
    "creatinine": "explicit_index_48h_comparison_and_baseline_same_unit_same_reviewed_identity_no_automatic_selection",
    "units": ["mg/dL", "umol/L"],
    "conversion": "none",
    "baseline": "explicit_actual_source_observed_within_7d_or_older_source_with_clinician_presumed_7d_rise_attestation",
    "urine": "whole_original_interval_average_v1",
    "urine_selection": "all_intersecting_active_members_checked_hidden_omissions_or_overlap_block_axis_locatable_missing_rows_split_complete_subchains",
    "urine_subperiods": "consecutive_whole_original_intervals_only_no_clipping_proration_hourly_imputation_or_rounding",
    "weight": "explicit_measured_kg_before_period_with_whole_period_applicability_attestation_no_default_ideal_or_latest_selection",
    "anuria": "known_zero_complete_chain_at_least_12h_does_not_require_weight",
    "rrt": "explicit_clinician_confirmed_new_acute_aki_initiation_not_maintenance_or_order_inference",
    "rrt_event_period_policy": "initiation_in_selected_window_start_through_evaluation_older_event_unknown_requires_current_episode_review_not_a_clinical_episode_duration_limit",
    "max_urine_intervals": 64,
    "missing": "unknown_not_zero_no_aki_exclusion_no_automatic_clinical_action",
}
RECIPE = {
    "rule_id": "kdigo_aki_2012",
    "version": "kdigo_aki_adult_decimal_v1",
    "criterion_order": list(CRITERION_KEYS),
    "input_policy": INPUT_POLICY,
    "creatinine_48h": {"max_hours": 48, "increase_at_least": {"mg/dL": "0.3", "umol/L": "26.5"}},
    "creatinine_ratio": {"max_observed_hours": 168, "stage_thresholds": [["1.5", 1], ["2.0", 2], ["3.0", 3]], "comparison": "exact_unrounded_cross_multiplication"},
    "absolute_stage3": {"at_least": {"mg/dL": "4.0", "umol/L": "353.6"}, "requires_positive_creatinine_acute_change": True, "si_policy": "table2_353.6_prose354_is_rounded_no_hidden_conversion"},
    "urine": [
        {"key": "urine_6h", "below_ml_kg_h": "0.5", "at_least_hours": 6, "stage": 1},
        {"key": "urine_12h", "below_ml_kg_h": "0.5", "at_least_hours": 12, "stage": 2},
        {"key": "urine_24h", "below_ml_kg_h": "0.3", "at_least_hours": 24, "stage": 3},
    ],
    "anuria": {"volume_ml": "0", "at_least_hours": 12, "stage": 3},
    "rrt": {"acute_initiated_for_aki": 3, "maintenance": "outside_scope", "event_period_policy": "selected_window_start_inclusive_through_evaluation_older_event_unknown"},
    "arithmetic": "exact_fractions_of_decimal_inputs_and_integer_utc_microseconds_no_rounded_ratios",
    "criterion_negative": "not_met_in_selected_data_never_global_aki_exclusion",
    "minimum_stage": "highest_supported_positive_criterion_1_or_2_lower_bound_3_reaches_scale_ceiling_not_episode_completeness",
    "time_scope": "selected_assessment_data_not_entire_aki_episode_maximum_48h7d_are_diagnosis_not_episode_staging_limits",
    "urine_policy_limit": "collection_interval_average_not_proof_of_each_hour_persistent_oliguria",
    "urine_partial_policy": "preserve_positive_complete_subchain_with_coverage_issues_never_cross_gaps_or_unmeasured_rows_negative_with_gaps_remains_unknown",
    "prompt_handling": "provenance_only",
    "probabilities": "not_provided",
    "clinical_validation": "not_provided",
}


def canonical_json(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def recipe_digest() -> str:
    return hashlib.sha256(canonical_json(RECIPE).encode()).hexdigest()


def canonical_uuid(value):
    if not isinstance(value, str) or str(uuid.UUID(value)) != value:
        raise ValueError("标识须为规范小写UUID")
    return value


def explicit_utc(value):
    if not isinstance(value, str) or re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)", value) is None:
        raise ValueError("时刻须带秒、最多6位小数秒且为显式UTC")
    if datetime.fromisoformat(value).utcoffset() != timedelta(0):
        raise ValueError("时刻须为UTC")
    return value


def decimal_text(value):
    if not isinstance(value, str) or re.fullmatch(r"-?(?:0|[1-9]\d{0,15})(?:\.\d{1,8})?", value) is None or not Decimal(value).is_finite():
        raise ValueError("数值须为有限普通十进制字符串，不转换、舍入或接受指数表示")
    return value


def source_binding(value, prefix, identifier, digest):
    if value != f"{prefix}:{identifier}:{digest[:12]}":
        raise ValueError("原来源身份与内容摘要不匹配")


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AkiCreatinine(StrictModel):
    lab_source_id: str
    source_id: str
    content_hash: SHA256
    governance_hash: SHA256
    collected_at_utc: str
    registered_at: str
    available_at: str
    mapping_id: str
    mapping_content_hash: SHA256
    mapping_governance_hash: SHA256
    identity_hash: SHA256
    value: str | None
    unit: str | None = Field(strict=True, max_length=120)
    conflict: bool = Field(strict=True)

    _ids = field_validator("lab_source_id", "mapping_id")(canonical_uuid)
    _clocks = field_validator("collected_at_utc", "registered_at", "available_at")(explicit_utc)

    @field_validator("value", mode="before")
    @classmethod
    def exact_value(cls, value):
        return decimal_text(value) if value is not None else None

    @model_validator(mode="after")
    def binding(self):
        source_binding(self.source_id, "inpatient_lab", self.lab_source_id, self.content_hash)
        if not datetime.fromisoformat(self.collected_at_utc) <= datetime.fromisoformat(self.registered_at) <= datetime.fromisoformat(self.available_at):
            raise ValueError("原肌酐采样、登记与受控可用时刻顺序无效")
        return self


class AkiWeight(StrictModel):
    point_id: str
    source_id: str
    content_hash: SHA256
    governance_hash: SHA256
    observed_at: str
    recorded_at: str
    value: str | None
    unit: Literal["kg"]
    absent_reason: Literal["unknown", "not_performed", "measurement_error"] | None
    conflict: bool = Field(strict=True)

    _id = field_validator("point_id")(canonical_uuid)
    _clocks = field_validator("observed_at", "recorded_at")(explicit_utc)

    @field_validator("value", mode="before")
    @classmethod
    def exact_value(cls, value):
        return decimal_text(value) if value is not None else None

    @model_validator(mode="after")
    def binding(self):
        source_binding(self.source_id, "inpatient_observation", self.point_id, self.content_hash)
        if (self.value is None) == (self.absent_reason is None) or (self.value is not None and Decimal(self.value) < 0):
            raise ValueError("体重原值/未测原因须二选一且原值非负")
        if datetime.fromisoformat(self.observed_at) > datetime.fromisoformat(self.recorded_at):
            raise ValueError("体重测量不能晚于登记")
        return self


class AkiUrine(StrictModel):
    interval_id: str
    source_id: str
    content_hash: SHA256
    governance_hash: SHA256
    start_at: str
    end_at: str
    recorded_at: str
    volume_ml: str | None
    absent_reason: Literal["unknown", "not_performed", "measurement_error"] | None
    collection_completeness: Literal["complete", "partial", "unknown"]
    patient_total: bool | None = Field(strict=True)

    _id = field_validator("interval_id")(canonical_uuid)
    _clocks = field_validator("start_at", "end_at", "recorded_at")(explicit_utc)

    @field_validator("volume_ml", mode="before")
    @classmethod
    def exact_value(cls, value):
        return decimal_text(value) if value is not None else None

    @model_validator(mode="after")
    def binding(self):
        source_binding(self.source_id, "urine_interval", self.interval_id, self.content_hash)
        if not datetime.fromisoformat(self.start_at) < datetime.fromisoformat(self.end_at) <= datetime.fromisoformat(self.recorded_at):
            raise ValueError("尿量原区间与登记时刻顺序无效")
        if (self.volume_ml is None) == (self.absent_reason is None) or (self.volume_ml is not None and Decimal(self.volume_ml) < 0):
            raise ValueError("尿量原值/未测原因须二选一且原值非负")
        return self


class AkiCreatinineReview(StrictModel):
    serum_creatinine_confirmed: bool = Field(strict=True)
    evidence_hash: SHA256 | None

    @model_validator(mode="after")
    def evidence(self):
        if self.serum_creatinine_confirmed and self.evidence_hash is None:
            raise ValueError("血清/血浆肌酐确认须有原核实依据摘要")
        return self


class AkiBaselineReview(StrictModel):
    rise_within_7d_confirmed: bool = Field(strict=True)
    evidence_hash: SHA256


class AkiRrt(StrictModel):
    status: Literal["unknown", "not_initiated", "acute_initiated_for_aki", "maintenance"]
    started_at: str | None
    acute_aki_confirmed: bool | None = Field(strict=True)
    evidence_hash: SHA256 | None

    @field_validator("started_at")
    @classmethod
    def start_clock(cls, value):
        return explicit_utc(value) if value is not None else None


class AkiSource(StrictModel):
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
    evaluation_at: str
    rule_profile_id: str
    rule_profile_source_id: str
    rule_profile_content_hash: SHA256
    rule_profile_governance_hash: SHA256
    rule_id: Literal["kdigo_aki_2012"]
    recipe_digest: SHA256
    age_at_evaluation_years: int = Field(strict=True, ge=0, le=130)
    creatinine_review: AkiCreatinineReview
    index_creatinine: AkiCreatinine | None
    comparison_48h: AkiCreatinine | None
    baseline_creatinine: AkiCreatinine | None
    baseline_mode: Literal["unknown", "observed_within_7d", "presumed_within_7d"]
    baseline_review: AkiBaselineReview | None
    weight: AkiWeight | None
    weight_applicability_confirmed: bool = Field(strict=True)
    weight_evidence_hash: SHA256 | None
    urine_intervals: list[AkiUrine] = Field(max_length=64)
    urine_coverage_issues: list[CoverageIssue] = Field(max_length=6)
    rrt: AkiRrt

    _ids = field_validator("assessment_id", "window_id", "rule_profile_id")(canonical_uuid)
    _clocks = field_validator("start_at", "end_at", "as_of", "evaluation_at")(explicit_utc)

    @model_validator(mode="after")
    def fixed_binding(self):
        for prefix, identifier, digest, source in (
            ("aki_assessment", self.assessment_id, self.content_hash, self.source_id),
            ("observation_window", self.window_id, self.window_content_hash, self.window_source_id),
            ("risk_rule_profile", self.rule_profile_id, self.rule_profile_content_hash, self.rule_profile_source_id),
        ):
            source_binding(source, prefix, identifier, digest)
        if self.recipe_digest != recipe_digest():
            raise ValueError("AKI固定规则版本不一致")
        start, end, cutoff, evaluation = (datetime.fromisoformat(getattr(self, name)) for name in ("start_at", "end_at", "as_of", "evaluation_at"))
        if not start < end <= cutoff or not start <= evaluation <= end or end - start > timedelta(hours=168):
            raise ValueError("原窗须不超过168小时且评估时刻在原窗内")
        for role in ("index_creatinine", "comparison_48h", "baseline_creatinine"):
            item = getattr(self, role)
            if item is not None:
                collected = datetime.fromisoformat(item.collected_at_utc)
                if datetime.fromisoformat(item.available_at) > cutoff or collected > evaluation:
                    raise ValueError("所选肌酐不得晚于原截止或评估时刻")
                if role != "baseline_creatinine" and collected < start:
                    raise ValueError("当前肌酐与48小时比较值须来自原窗")
        if self.weight is not None and (datetime.fromisoformat(self.weight.recorded_at) > cutoff or datetime.fromisoformat(self.weight.observed_at) > evaluation):
            raise ValueError("体重不得晚于原截止或评估时刻")
        identifiers = [item.interval_id for item in self.urine_intervals]
        if len(set(identifiers)) != len(identifiers) or len(set(self.urine_coverage_issues)) != len(self.urine_coverage_issues):
            raise ValueError("原尿量ID和覆盖问题不可重复")
        for item in self.urine_intervals:
            if not start <= datetime.fromisoformat(item.start_at) < datetime.fromisoformat(item.end_at) <= evaluation or datetime.fromisoformat(item.recorded_at) > cutoff:
                raise ValueError("原尿量须完整落在原窗及评估时刻之前，不裁剪区间")
        if self.rrt.started_at is not None and datetime.fromisoformat(self.rrt.started_at) > evaluation:
            raise ValueError("RRT启动不得晚于评估时刻")
        return self


class AkiCriterionEvidence(StrictModel):
    index_value: str | None = None
    reference_value: str | None = None
    unit: str | None = None
    index_at: str | None = None
    reference_at: str | None = None
    absolute_change: str | None = None
    threshold: str | None = None
    multiplier: str | None = None
    elapsed_microseconds: int | None = Field(default=None, strict=True, ge=0)
    interval_start_at: str | None = None
    interval_end_at: str | None = None
    total_volume_ml: str | None = None
    weight_kg: str | None = None
    rate_numerator: str | None = None
    rate_denominator: str | None = None
    interval_source_ids: list[str] = Field(default_factory=list, max_length=64)
    coverage_issues: list[CoverageIssue] = Field(default_factory=list, max_length=6)


class AkiCriterion(StrictModel):
    key: CriterionKey
    status: Literal["met", "not_met_in_selected_data", "unknown", "outside_scope"]
    stage: int | None = Field(strict=True, ge=1, le=3)
    reason_code: str = Field(min_length=1, max_length=120)
    source_ids: list[str] = Field(max_length=70)
    evidence: AkiCriterionEvidence


class AkiRuntime(StrictModel):
    engine: Literal["stdlib-kdigo-aki-rules"]
    rule_id: Literal["kdigo_aki_2012"]
    recipe_digest: SHA256
    implementation: dict[str, SHA256] = Field(min_length=4, max_length=4)
    python_version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    engine_versions: dict[str, str] = Field(min_length=2, max_length=2)
    runtime_digest: SHA256
    model_version: str = Field(pattern=r"^aki:[a-f0-9]{64}$")
    prompt_handling: Literal["provenance_only"]
    clinical_validation: Literal["not_provided"]
    population_applicability: Literal["not_independently_verified"]
    independent_implementation: Literal[True]


class AkiAnalysis(StrictModel):
    schema_version: Literal["1"]
    source_binding: AkiSource
    rule_id: Literal["kdigo_aki_2012"]
    calculation_status: Literal["computed", "insufficient_data", "outside_scope"]
    scope_status: Literal["within_declared_scope", "outside_scope"]
    detection: Literal["met", "not_met_in_selected_data", "insufficient_data", "outside_scope"]
    criteria: list[AkiCriterion] = Field(min_length=8, max_length=8)
    minimum_stage: int | None = Field(strict=True, ge=1, le=3)
    stage_is_lower_bound: bool = Field(strict=True)
    aki_excluded: Literal[False]
    missing_data: list[str]
    warnings: list[str]
    local_runtime: AkiRuntime
    instructions_digest: SHA256
    attribution: str
    rule_references: list[str] = Field(min_length=4, max_length=4)
    independent_implementation: Literal[True]
    clinical_validation: Literal["not_provided"]
