"""Exact typed evidence for six-axis SOFA-1 local native observed policy.

All facts remain original; current retrospective review is hashed separately.
Values explicitly None/False/'0' MUST survive JSON encode/decode and UI display.
"""

from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Annotated, Literal, get_args, get_origin

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator


def canonical_json(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def hash_content(value) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _utc(value):
    parsed = datetime.fromisoformat(value)
    if parsed.year < 1000 or parsed.utcoffset() != timedelta(0) or parsed.isoformat(timespec="microseconds").replace("+00:00", "Z") != value:
        raise ValueError("时刻须为可保存的真实规范UTC6")
    return value


def _decimal(value):
    if not Decimal(value).is_finite() or Decimal(value) < 0:
        raise ValueError("原量须为非负有限普通十进制字符串")
    return value


RULE_ID = "sofa1_native_observed_v1"
HTTP_SCHEMA_VERSION = "9"
MODEL_PREFIX = "sofa1:"
PORT = 8818
SHA256 = Annotated[str, Field(strict=True, pattern=r"^[a-f0-9]{64}$")]
UUIDText = Annotated[str, Field(strict=True, pattern=r"^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$")]
UTCText = Annotated[str, Field(strict=True, pattern=r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$"), AfterValidator(_utc)]
DecimalText = Annotated[str, Field(strict=True, pattern=r"^(?:0|[1-9]\d{0,15})(?:\.\d{1,8})?$"), AfterValidator(_decimal)]
TechnicalId = Annotated[str, Field(strict=True, min_length=1, max_length=200)]
SourceNamespace = Annotated[str, Field(strict=True, min_length=1, max_length=80)]
Axis = Literal["respiratory", "coagulation", "liver", "cardiovascular", "cns", "renal"]
DrugKey = Literal["dopamine", "dobutamine", "epinephrine", "norepinephrine", "other"]
Score = Annotated[int, Field(strict=True, ge=0, le=4)]
TotalScore = Annotated[int, Field(strict=True, ge=0, le=24)]
AbsentReason = Literal["unknown", "not_performed", "measurement_error"]
YesNoUnknown = Literal["yes", "no", "unknown"]
ReasonCode = Literal[
    "missing_measurement",
    "missing_branch",
    "missing_pair",
    "missing_fio2",
    "missing_support",
    "unsupported_unit",
    "unknown_quantity",
    "unsupported_value",
    "review_unknown",
    "review_excluded",
    "unresolved_conflict",
    "inventory_incomplete",
    "inventory_unknown",
    "protocol_incomplete",
    "protocol_unknown",
    "outside_period",
    "outside_scope",
    "scope_unknown",
    "gcs_confounding_not_excluded",
    "gcs_not_testable",
    "gcs_incomplete",
    "gcs_not_interpretable",
    "gcs_anchor_invalid",
    "pair_not_confirmed",
    "support_qualification_unknown",
    "continuous_iv_not_confirmed",
    "continuity_not_confirmed",
    "weight_missing",
    "weight_nonpositive",
    "weight_not_applicable",
    "mass_basis_not_confirmed",
    "rate_scope_unknown",
    "stream_relation_unresolved",
    "overlapping_same_stream",
    "unrepresented_drug_exposure",
    "duration_not_satisfied",
    "zero_rate_no_positive_exposure",
    "urine_gap",
    "urine_overlap",
    "urine_crosses_period",
    "urine_collection_incomplete",
    "urine_patient_total_unknown",
    "no_eligible_measurement",
    "normal_imputation_forbidden",
]


class StrictModel(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    @model_validator(mode="before")
    @classmethod
    def no_literal_boolean_coercion(cls, data):
        if isinstance(data, dict):
            for name, field in cls.model_fields.items():
                args = get_args(field.annotation)
                if get_origin(field.annotation) is Literal and any(isinstance(value, bool) for value in args) and name in data and type(data[name]) is not bool:
                    raise ValueError("固定布尔声明须为真实JSON布尔值")
        return data


class Quantity(StrictModel):
    @model_validator(mode="after")
    def exclusive_presence(self):
        if (self.value is None) == (self.absent_reason is None):
            raise ValueError("原量与未测原因须且只能一项")
        return self

    value: DecimalText | None
    unit: Annotated[str, Field(strict=True, min_length=1, max_length=32)]
    absent_reason: AbsentReason | None
    # Product validator: exactly one of value / absent_reason; never normalize original lexical value.


class Binding(StrictModel):
    source_id: TechnicalId
    content_hash: SHA256
    governance_hash: SHA256


class OriginalBinding(Binding):
    recorded_at: UTCText

    @model_validator(mode="after")
    def technical_binding(self):
        identities = {
            "SofaLab": ("inpatient_lab", "lab_source_id"),
            "SofaMap": ("map_observation", "support_source_id"),
            "SofaGcs": ("gcs_observation", "gcs_observation_id"),
            "SofaUrine": ("urine_interval", "interval_id"),
            "SofaFio2": ("inpatient_observation", "observation_id"),
            "SofaWeight": ("inpatient_observation", "observation_id"),
            "SofaRespiratorySupport": ("respiratory_support", "support_source_id"),
            "SofaPair": ("arterial_pair", "support_source_id"),
            "SofaVasoInterval": ("vasoactive_interval", "support_source_id"),
        }
        if type(self).__name__ in identities:
            prefix, field = identities[type(self).__name__]
            if self.source_id != f"{prefix}:{getattr(self, field)}:{self.content_hash[:12]}":
                raise ValueError("原技术source_id与完整原件hash不一致")
        return self


class MemberReview(StrictModel):
    @model_validator(mode="after")
    def excluded_reason(self):
        if (self.status == "excluded") != (self.exclusion_reason is not None):
            raise ValueError("仅排除成员须有明确排除原因")
        return self

    status: Literal["confirmed", "excluded", "unknown"]
    basis_hash: SHA256
    exclusion_reason: (
        Literal[
            "not_patient_measurement",
            "wrong_sample_or_analyte",
            "duplicate_record",
            "measurement_error",
            "not_applicable",
            "conflicting_alternative",
            "other_clinician_reason",
        ]
        | None
    )
    # excluded -> explicit reason. Other statuses -> reason None.
    # Excluded facts remain present; they do not create a physiologic unknown candidate.
    # Exclusion cannot manufacture a missing required measurement or whole-day coverage.


class Coverage(StrictModel):
    source_inventory: Literal["complete", "incomplete", "unknown"]
    clinical_protocol: Literal["adequate", "incomplete", "unknown"]
    basis_hash: SHA256


class SixAxisCoverage(StrictModel):
    respiratory: Coverage
    coagulation: Coverage
    liver: Coverage
    cardiovascular: Coverage
    cns: Coverage
    renal: Coverage


class Population(StrictModel):
    age_at_period_years: Annotated[int, Field(strict=True, ge=0, le=130)] | None
    adult: YesNoUnknown
    care_setting: Literal["icu", "other", "unknown"]
    applicability_confirmed: bool
    basis_hash: SHA256


class ConflictGroup(StrictModel):
    @model_validator(mode="after")
    def full_partition(self):
        members, accepted, excluded = self.member_source_ids, self.accepted_source_ids, self.excluded_source_ids
        if not members or any(len(values) != len(set(values)) for values in (members, accepted, excluded)):
            raise ValueError("冲突成员须完整且不重复")
        if self.status == "resolved":
            if set(accepted) & set(excluded) or set(accepted) | set(excluded) != set(members):
                raise ValueError("已裁决冲突须完整分割接受与排除成员")
        elif accepted or excluded:
            raise ValueError("未决冲突不能指定已接受或已排除成员")
        return self

    group_id: TechnicalId
    axis: Axis
    group_digest: SHA256
    member_source_ids: list[TechnicalId]
    status: Literal["resolved", "unresolved"]
    accepted_source_ids: list[TechnicalId]
    excluded_source_ids: list[TechnicalId]
    basis_hash: SHA256
    # Explicit immutable member set, no timestamp-only inferred conflict.
    # resolved -> disjoint accepted/excluded partition equals all members, actual reviews agree.
    # unresolved -> accepted/excluded empty, dependent members cannot create exact score.


SignedDecimalText = Annotated[str, Field(strict=True, pattern=r"^-?(?:0|[1-9]\d{0,15})(?:\.\d{1,8})?$")]


class SofaLabQuantity(StrictModel):
    value: SignedDecimalText | None
    unit: Annotated[str, Field(strict=True, min_length=1, max_length=64)]
    absent_reason: AbsentReason | None
    value_kind: Literal["numeric", "qualitative"]

    @model_validator(mode="after")
    def exclusive_presence(self):
        if (self.value is None) == (self.absent_reason is None) or (self.value_kind == "qualitative" and self.value is not None):
            raise ValueError("检验原量/定性类型/未测原因不一致")
        return self


class SofaLab(OriginalBinding):
    @model_validator(mode="after")
    def original_clocks(self):
        if self.registered_at != self.available_at or self.recorded_at != self.registered_at or self.collected_at_utc > self.registered_at:
            raise ValueError("检验原采样/登记/可用时刻链不一致")
        return self

    lab_source_id: UUIDText
    collected_at_utc: UTCText
    registered_at: UTCText
    available_at: UTCText
    mapping_id: UUIDText
    mapping_content_hash: SHA256
    mapping_governance_hash: SHA256
    identity_hash: SHA256
    analyte: Literal["platelet_count", "total_bilirubin", "creatinine", "arterial_oxygen_partial_pressure"]
    quantity: SofaLabQuantity
    review: MemberReview
    # registered_at == available_at == recorded_at; collected <= registered <= as_of.


class SofaMap(OriginalBinding):
    support_source_id: UUIDText
    observed_at: UTCText
    quantity: Quantity
    measurement_method: Literal["invasive_arterial", "oscillometric_device", "unknown"]
    review: MemberReview


class GcsComponent(StrictModel):
    @model_validator(mode="after")
    def exclusive_presence(self):
        if (self.score is None) == (self.absent_reason is None):
            raise ValueError("GCS原分项与未测原因须且只能一项")
        return self

    score: Annotated[int, Field(strict=True, ge=1, le=6)] | None
    absent_reason: Literal["not_testable", "not_recorded"] | None


class GcsComponents(StrictModel):
    @model_validator(mode="after")
    def actual_ranges(self):
        if (self.eye.score is not None and self.eye.score > 4) or (self.verbal.score is not None and self.verbal.score > 5):
            raise ValueError("原GCS眼/言语/运动须分别为1..4/1..5/1..6")
        return self

    eye: GcsComponent
    verbal: GcsComponent
    motor: GcsComponent
    # component-specific eye <=4, verbal<=5; each score/reason exactly one.


class SofaGcs(OriginalBinding):
    @model_validator(mode="after")
    def original_exam(self):
        if self.anchor is not None and (not self.anchor.source_id.startswith("inpatient_observation:") or not self.anchor.source_id.endswith(":" + self.anchor.content_hash[:12])):
            raise ValueError("原GCS已有锚须绑定真实点测技术来源")
        if self.observed_at > self.recorded_at or (self.anchor is None and not self.anchor_current):
            raise ValueError("原GCS时刻或既有锚定声明无效")
        return self

    gcs_observation_id: UUIDText
    observed_at: UTCText
    components: GcsComponents
    interpretable: Literal["confirmed", "limited", "unknown"]
    sedation_confounding_status: Literal["excluded", "present", "unknown"]
    other_confounding_status: Literal["excluded", "present", "unknown"]
    confounding_basis_hash: SHA256
    anchor: OriginalBinding | None
    anchor_current: bool
    review: MemberReview
    # Actual original full EVM only. If anchor exists, full current binding mandatory.
    # No anchor -> anchor None + anchor_current True (no manufactured dependency).


class SofaUrine(OriginalBinding):
    @model_validator(mode="after")
    def original_interval(self):
        if self.start_at >= self.end_at or self.end_at > self.recorded_at:
            raise ValueError("尿量须真实有界原区段")
        if (self.volume_ml is None) == (self.absent_reason is None):
            raise ValueError("尿量原量与未测原因须且只能一项")
        return self

    interval_id: UUIDText
    start_at: UTCText
    end_at: UTCText
    volume_ml: DecimalText | None
    absent_reason: AbsentReason | None
    collection_completeness: Literal["complete", "partial", "unknown"]
    patient_total: bool | None
    review: MemberReview


class SofaFio2(OriginalBinding):
    observation_id: UUIDText
    observed_at: UTCText
    quantity: Quantity


class SofaRespiratorySupport(OriginalBinding):
    @model_validator(mode="after")
    def verified_interval(self):
        if self.start_at >= self.verified_until_at or self.verified_until_at > self.recorded_at or (self.ended_at is not None and self.ended_at != self.verified_until_at):
            raise ValueError("持续来源须真实核实有界区段，结束时刻不能另猜")
        return self

    support_source_id: UUIDText
    start_at: UTCText
    verified_until_at: UTCText
    ended_at: UTCText | None
    delivery_mode: Literal[
        "none",
        "invasive_mechanical",
        "noninvasive_positive_pressure",
        "high_flow_nasal",
        "low_flow_oxygen",
        "other",
        "unknown",
    ]
    continuity_confirmed: bool
    review: MemberReview


class SofaPair(OriginalBinding):
    support_source_id: UUIDText


class SofaRespiratoryObservation(StrictModel):
    candidate_id: TechnicalId
    pao2: SofaLab
    pair: SofaPair | None
    fio2: SofaFio2 | None
    support: SofaRespiratorySupport | None
    arterial_sample_confirmed: bool
    same_sampling_state_confirmed: bool
    fio2_applicability_confirmed: bool
    qualifying_respiratory_support: YesNoUnknown
    support_qualification_basis_hash: SHA256
    review: MemberReview
    # Unpaired original PaO2 retained with null pair/fio2/support.
    # PaO2 mm[Hg] thresholds 400/300/200/100; native kPa 53.3/40/26.7/13.3.
    # NO kPa conversion or equivalence claim. Qualifying support comes from Doctor review;
    # no automatic classification from mode. All actual clocks preserved, not forced equal.


class SofaWeight(OriginalBinding):
    observation_id: UUIDText
    observed_at: UTCText
    quantity: Quantity
    review: MemberReview


class SofaDrugMapping(Binding):
    @model_validator(mode="after")
    def technical_binding(self):
        if self.source_id != f"vasoactive_drug_mapping:{self.mapping_id}:{self.content_hash[:12]}":
            raise ValueError("实际药物映射技术绑定不一致")
        return self

    mapping_id: UUIDText
    drug_key: DrugKey
    active_moiety_basis: Literal["base", "salt", "unknown"]


class WeightNormalizedDose(StrictModel):
    mode: Literal["weight_normalized"]
    rate: Quantity


class AbsoluteDose(StrictModel):
    mode: Literal["absolute"]
    rate: Quantity


class PumpDose(StrictModel):
    mode: Literal["pump"]
    concentration: Quantity
    pump_rate: Quantity


DoseInput = Annotated[WeightNormalizedDose | AbsoluteDose | PumpDose, Field(discriminator="mode")]


class SofaVasoInterval(OriginalBinding):
    @model_validator(mode="after")
    def verified_interval(self):
        if self.start_at >= self.verified_until_at or self.verified_until_at > self.recorded_at or (self.ended_at is not None and self.ended_at != self.verified_until_at):
            raise ValueError("持续来源须真实核实有界区段，结束时刻不能另猜")
        return self

    support_source_id: UUIDText
    start_at: UTCText
    verified_until_at: UTCText
    ended_at: UTCText | None
    stream_key: SHA256
    mapping: SofaDrugMapping
    continuity_confirmed: bool
    continuous_iv: Literal["confirmed", "not_confirmed", "unknown"]
    rate_scope: Literal["stream_rate", "agent_total", "unknown"]
    dose_input: DoseInput
    weight: SofaWeight | None
    weight_applicability_confirmed: bool
    weight_use_confirmed: bool
    mass_basis_compatible_confirmed: bool
    review: MemberReview
    # stream_key = SHA({source_namespace,external_stream_id}), no strings exposed.
    # Identity excludes private note; original false weight applicability cannot be overwritten.
    # Only original base mapping + explicit compatible review can score in fixed v1.
    # Original raw source's optional eMAR chain remains private and bound by content_hash.
    # Prefix up to 1h before start retained. No exposure after verified_until_at/as_of invented.


class SofaVasoGroup(StrictModel):
    drug_key: DrugKey
    relation: Literal["single_stream", "distinct_parallel_streams", "agent_total", "unresolved"]
    relation_confirmed: bool
    dose_basis_consistency_confirmed: bool
    basis_hash: SHA256
    intervals: list[SofaVasoInterval]
    # Exactly one group per drug; all raw intervals represented, no winner-only serialization.


class CirculationReview(StrictModel):
    drug_exposure: Literal["none", "reviewed_intervals", "unknown"]
    no_other_unrepresented_exposure_confirmed: bool
    basis_hash: SHA256
    # none requires no non-excluded positive exposure and explicitly complete actual inventory.


class MemberIssue(StrictModel):
    axis: Axis
    code: ReasonCode
    source_ids: list[TechnicalId]


class SofaSource(StrictModel):
    @model_validator(mode="after")
    def complete_source(self):
        if datetime.fromisoformat(self.end_at) - datetime.fromisoformat(self.start_at) != timedelta(days=1) or not self.end_at <= self.as_of <= self.evaluation_at:
            raise ValueError("SOFA原窗口须恰24h且结束<=原可用截止<=当前回顾时刻")
        if (
            self.source_id != f"sofa_assessment:{self.assessment_id}:{self.content_hash[:12]}"
            or self.rule_profile_source_id != f"risk_rule_profile:{self.rule_profile_id}:{self.rule_profile_content_hash[:12]}"
        ):
            raise ValueError("SOFA实际评估/规则profile技术绑定不一致")
        if self.population.adult == "yes" and (self.population.age_at_period_years is None or self.population.age_at_period_years < 18):
            raise ValueError("成人声明须有原年龄>=18支持")
        if self.population.adult == "no" and self.population.age_at_period_years is not None and self.population.age_at_period_years >= 18:
            raise ValueError("成人声明与原年龄不一致")
        if self.recipe_digest != recipe_digest() or self.policy_digest != policy_digest():
            raise ValueError("SOFA固定recipe/policy绑定不一致")
        if len(canonical_json(self.model_dump()).encode()) > MAX_DAILY_PUBLIC_BYTES:
            raise ValueError("SOFA完整公共投影超过2MiB，不能截断")
        roots = (
            self.lab_observations
            + self.respiratory_observations
            + self.respiratory_support_observations
            + self.map_observations
            + self.gcs_observations
            + self.urine_intervals
            + [i for g in self.vasoactive_groups for i in g.intervals]
        )
        if len({g.drug_key for g in self.vasoactive_groups}) != len(self.vasoactive_groups):
            raise ValueError("每药仅一个完整流组")
        if any(item.analyte == "arterial_oxygen_partial_pressure" for item in self.lab_observations):
            raise ValueError("PaO2仅通过完整respiratory候选保留")
        seen = {}
        same_type_facts = {}

        def walk(item):
            if isinstance(item, OriginalBinding):
                if item.recorded_at > self.as_of:
                    raise ValueError("原来源晚于所选可用截止")
                binding = (item.content_hash, item.governance_hash, item.recorded_at)
                if item.source_id in seen and seen[item.source_id] != binding:
                    raise ValueError("重复原来源具有不一致内容/治理/时刻")
                seen[item.source_id] = binding
                fact_key = (type(item).__name__, item.source_id)
                facts = item.model_dump()
                if fact_key in same_type_facts and same_type_facts[fact_key] != facts:
                    raise ValueError("同一类原件不能具有不同原事实或判读")
                same_type_facts[fact_key] = facts
                if hasattr(item, "observed_at") and item.observed_at > item.recorded_at:
                    raise ValueError("原观察时刻晚于原登记")
            if isinstance(item, BaseModel):
                for name in type(item).model_fields:
                    walk(getattr(item, name))
            elif isinstance(item, list):
                for child in item:
                    walk(child)

        for root in roots:
            walk(root)
        for items in (
            self.lab_observations,
            self.respiratory_support_observations,
            self.map_observations,
            self.gcs_observations,
            self.urine_intervals,
            *[group.intervals for group in self.vasoactive_groups],
        ):
            if len({item.source_id for item in items}) != len(items):
                raise ValueError("同一原件不能在根成员数组重复列入")
        if len({item.candidate_id for item in self.respiratory_observations}) != len(self.respiratory_observations) or len({group.group_id for group in self.conflict_groups}) != len(
            self.conflict_groups
        ):
            raise ValueError("呼吸候选/冲突组技术标识不可重复")
        ids = set(seen)
        root_prefixes = {"inpatient_lab", "map_observation", "gcs_observation", "urine_interval", "respiratory_support", "arterial_pair", "vasoactive_interval"}
        if sum(source_id.split(":", 1)[0] in root_prefixes for source_id in ids) > MAX_MEMBERS:
            raise ValueError("SOFA唯一原成员超过4096，不能截断")
        for issue in self.member_issues:
            if not set(issue.source_ids) <= ids:
                raise ValueError("缺项/来源问题不能指向未投影原件")
        for group in self.conflict_groups:
            if not set(group.member_source_ids) <= ids:
                raise ValueError("冲突组包含未投影的原成员")
        for group in self.vasoactive_groups:
            if any(i.mapping.drug_key != group.drug_key for i in group.intervals):
                raise ValueError("输注组药物与原映射不一致")
        return self

    schema_version: Literal["sofa1_source_v1"]
    assessment_id: UUIDText
    source_id: TechnicalId
    content_hash: SHA256
    assessment_governance_hash: SHA256
    start_at: UTCText
    end_at: UTCText
    as_of: UTCText
    evaluation_at: UTCText
    rule_profile_id: UUIDText
    rule_profile_source_id: TechnicalId
    rule_profile_content_hash: SHA256
    rule_profile_governance_hash: SHA256
    rule_id: Literal["sofa1_native_observed_v1"]
    recipe_digest: SHA256
    policy_digest: SHA256
    source_set_digest: SHA256
    population: Population
    coverage: SixAxisCoverage
    lab_observations: list[SofaLab]
    respiratory_observations: list[SofaRespiratoryObservation]
    respiratory_support_observations: list[SofaRespiratorySupport]
    map_observations: list[SofaMap]
    gcs_observations: list[SofaGcs]
    vasoactive_groups: list[SofaVasoGroup]
    urine_intervals: list[SofaUrine]
    circulation_review: CirculationReview
    conflict_groups: list[ConflictGroup]
    member_issues: list[MemberIssue]
    # Source itself NEVER contains projection_hash (no cycle).
    # source_set_digest binds full actual member/parent/governance manifest, including losers.
    # assessment_governance_hash is frozen creation active rev1, not current revoked rev2.
    # end-start exactly24h, end<=as_of<=evaluation_at; originals recorded/available<=as_of.


class SourceBinding(StrictModel):
    assessment_id: UUIDText
    source_id: TechnicalId
    content_hash: SHA256
    assessment_governance_hash: SHA256
    rule_profile_id: UUIDText
    rule_profile_source_id: TechnicalId
    rule_profile_content_hash: SHA256
    rule_profile_governance_hash: SHA256
    rule_id: Literal["sofa1_native_observed_v1"]
    recipe_digest: SHA256
    policy_digest: SHA256
    source_set_digest: SHA256
    projection_hash: SHA256
    # projection_hash = SHA256(canonical_json(whole SofaSource)). Compact binding only.


class ExactRational(StrictModel):
    @model_validator(mode="after")
    def reduced(self):
        n, d = int(self.numerator), int(self.denominator)
        if self.numerator == "-0" or math.gcd(n, d) != 1:
            raise ValueError("派生有理数须规范约分，零须0/1")
        return self

    numerator: Annotated[str, Field(strict=True, pattern=r"^-?(?:0|[1-9]\d*)$")]
    denominator: Annotated[str, Field(strict=True, pattern=r"^[1-9]\d*$")]
    unit: Literal["1", "ug/kg/min", "mm[Hg]", "kPa", "mL", "mL/24h", "us"]
    # Reduced gcd==1, canonical zero0/1, no negative zero, no arbitrary rounding.


class QuantityCalculation(StrictModel):
    kind: Literal["quantity"]
    operation: Literal["original_native_quantity", "gcs_actual_sum", "urine_full_period_sum"]
    source_ids: list[TechnicalId]
    exact: ExactRational


class PfCalculation(StrictModel):
    kind: Literal["pf_ratio"]
    source_ids: list[TechnicalId]
    native_pao2_unit: Literal["mm[Hg]", "kPa"]
    exact: ExactRational
    qualifying_respiratory_support: YesNoUnknown


class RateCalculation(StrictModel):
    kind: Literal["dose_rate"]
    source_ids: list[TechnicalId]
    mode: Literal["weight_normalized", "absolute", "pump", "parallel_sum"]
    exact: ExactRational


class DurationCalculation(StrictModel):
    kind: Literal["continuous_tier"]
    drug_key: DrugKey
    tier: Annotated[int, Field(strict=True, ge=2, le=4)]
    start_at: UTCText
    end_at: UTCText
    source_ids: list[TechnicalId]
    duration_microseconds: Annotated[int, Field(strict=True, ge=0)]
    meets_minimum: bool
    # Qualified witness end b in (period.start,period.end], positive in-period exposure.


Calculation = Annotated[QuantityCalculation | PfCalculation | RateCalculation | DurationCalculation, Field(discriminator="kind")]


class SofaCandidate(StrictModel):
    candidate_id: TechnicalId
    source_ids: list[TechnicalId]
    branch_id: Literal["pao2_fio2", "platelets", "bilirubin", "map", "vasoactive", "gcs", "creatinine", "urine"]
    status: Literal["scored", "bounded", "unknown", "excluded", "outside_scope"]
    score: Score | None
    lower_bound: Score
    upper_bound: Score
    reason_codes: list[ReasonCode]
    calculations: list[Calculation]
    # Raw facts are in SofaSource once, not echoed per candidate; all source IDs bind projection.


class SofaDomain(StrictModel):
    axis: Axis
    candidates: list[SofaCandidate]
    observed_max_score: Score | None
    lower_bound: Score
    upper_bound: Score
    exact_numeric_score: Score | None
    protocol_complete: bool
    coverage_issues: list[ReasonCode]
    deciding_source_ids: list[TechnicalId]


class SofaRuntime(StrictModel):
    engine: Literal["hoim_sofa1_native_independent"]
    model_version: Annotated[str, Field(strict=True, pattern=r"^sofa1:[a-f0-9]{64}$")]
    runtime_digest: SHA256
    recipe_digest: SHA256
    policy_digest: SHA256
    python_version: TechnicalId
    fastapi_version: TechnicalId
    pydantic_version: TechnicalId
    core_sha256: dict[Literal["sofa_contract.py", "sofa_model.py", "sofa_config.py", "sofa_server.py"], SHA256]
    independent_implementation: Literal[True]
    clinical_validation: Literal["not_provided"]


class SofaAnalysis(StrictModel):
    schema_version: Literal["1"]
    source_binding: SourceBinding
    rule_id: Literal["sofa1_native_observed_v1"]
    recipe_digest: SHA256
    policy_digest: SHA256
    calculation_status: Literal["computed", "partial", "outside_scope"]
    scope_status: Literal["within_declared_scope", "outside_scope", "unknown"]
    domains: list[SofaDomain]
    known_subtotal: TotalScore | None
    observed_scored_domain_count: Annotated[int, Field(strict=True, ge=0, le=6)]
    protocol_complete_domain_count: Annotated[int, Field(strict=True, ge=0, le=6)]
    lower_bound: TotalScore
    upper_bound: TotalScore
    exact_numeric_total: TotalScore | None
    complete_total_score: TotalScore | None
    local_runtime: SofaRuntime
    instructions_digest: SHA256
    warnings: list[TechnicalId]
    missing_data: list[TechnicalId]
    diagnosis_provided: Literal[False]
    probability_provided: Literal[False]
    treatment_provided: Literal[False]
    historical_prediction: Literal[False]
    clinical_validation: Literal["not_provided"]
    independent_implementation: Literal[True]
    attribution: str
    rule_references: list[str]
    # Mathematical validator MUST recompute full entire SofaSource and compare whole analysis.
    # unknown branches never default0; numeric collapse does not imply protocol completeness.


RECIPE = {
    "rule_id": "sofa1_native_observed_v1",
    "version": "sofa1_native_observed_local_policy_v1",
    "rule_family": "SOFA1",
    "organ_order": ["respiratory", "coagulation", "liver", "cardiovascular", "cns", "renal"],
    "population": "clinician_declared_adult_no_qsofa_non_icu_or_news2_pregnancy_exclusion_no_independent_clinical_validation",
    "period": {
        "duration_microseconds": 86400000000,
        "point_membership": "start_inclusive_end_exclusive",
        "availability": "all_original_recorded_registered_available_at_or_before_as_of",
        "review": "current_retrospective_evaluation_at_not_historical_prediction",
        "aggregation": "maximum_eligible_candidate_per_domain_never_mix_different_samples_or_gcs_components",
    },
    "respiratory": {
        "pao2_units": ["mm[Hg]", "kPa"],
        "fio2_unit": "%",
        "fio2_eligibility": "positive_at_most_100_explicit_original_pair_no_room_air_default",
        "comparison": "100_times_pao2_cross_compare_threshold_times_original_fio2_percent_no_rounded_division",
        "thresholds_mmhg": ["400", "300", "200", "100"],
        "support_policy": "local_doctor_adjudicated_per_actual_pair_yes_no_unknown_v1",
        "without_qualifying_support_maximum": 2,
        "unknown_support_low_ratio_bounds": {"100_to_below_200": [2, 3], "below_100": [2, 4]},
        "sample_review": "arterial_sample_same_sampling_state_and_fio2_applicability_all_confirmed",
        "kpa": "independent_rounded_native_thresholds_from_sepsis3_printed_table_no_conversion_or_equivalence_claim",
        "qualifying_support": "explicit_current_doctor_review_with_basis_hash_never_device_mode_inference",
        "thresholds_kpa": ["53.3", "40", "26.7", "13.3"],
    },
    "coagulation": {
        "native_units": ["10^9/L", "10^3/uL"],
        "unit_policy": "explicit_native_numeric_equivalence_only_no_fuzzy_unit_matching",
        "bands": [["150", None, True, False, 0], ["100", "150", True, False, 1], ["50", "100", True, False, 2], ["20", "50", True, False, 3], ["0", "20", True, False, 4]],
    },
    "liver": {
        "analyte": "total_bilirubin",
        "bands": {
            "mg/dL": [["0", "1.2", True, False, 0], ["1.2", "2", True, False, 1], ["2", "6", True, False, 2], ["6", "12", True, False, 3], ["12", None, True, False, 4]],
            "umol/L": [["0", "20", True, False, 0], ["20", "33", True, False, 1], ["33", "102", True, False, 2], ["102", "204", True, False, 3], ["204", None, True, False, 4]],
        },
        "native_policy": "local_mimic_mgdl_continuous_and_amsterdam_si_native_not_exact_converted_equivalence_no_claim_of_official_1996_erratum",
    },
    "cardiovascular": {
        "map": {"unit": "mm[Hg]", "below": "70", "score": 1, "missing_branch_bounds": [0, 1]},
        "positive_drug_dose_unit": "ug/kg/min",
        "dopamine": [{"above": "15", "score": 4}, {"above": "5", "at_most": "15", "score": 3}, {"above": "0", "at_most": "5", "score": 2}],
        "dobutamine": [{"above": "0", "score": 2}],
        "epinephrine": [{"above": "0.1", "score": 4}, {"above": "0", "at_most": "0.1", "score": 3}],
        "norepinephrine": [{"above": "0.1", "score": 4}, {"above": "0", "at_most": "0.1", "score": 3}],
        "zero": "never_positive_exposure_never_any_dose_score",
        "actual_route": "doctor_confirmed_continuous_iv_no_old_order_route_parsing_or_bolus_inference",
        "dose_arithmetic": "reduced_exact_fraction_of_original_decimal_inputs_direct_normalized_rate_never_divided_twice",
        "mass_basis": "original_mapping_base_only_and_explicit_compatible_clinician_review_unknown_or_salt_remains_unknown_no_implicit_factor",
        "normalization": {
            "ug/kg/min": "original_rate",
            "ug/min": "original_rate_divided_by_actual_applicable_weight_kg",
            "mg/h": "original_rate_times_1000_divided_by_60_times_actual_applicable_weight_kg",
            "pump_ug/mL": "concentration_times_pump_ml_h_divided_by_60_times_actual_applicable_weight_kg",
            "pump_mg/mL": "concentration_times_1000_times_pump_ml_h_divided_by_60_times_actual_applicable_weight_kg",
            "weight": "explicit_original_measured_kg_positive_observed_no_later_than_start_recorded_by_asof_original_applicability_true_plus_current_use_confirmed_no_default",
        },
        "stream_policy": "same_drug_explicit_distinct_parallel_stream_rates_sum_piecewise_no_duplicate_or_agent_total_double_count_unresolved_overlap_unknown_stream_key_sha_namespace_and_external_id_only_no_note",
        "cross_drug_policy": "separate_agents_no_ne_epinephrine_sum_no_equivalent_conversion",
        "duration_policy": "local_band_continuity_1h_v1_not_claimed_official_resolution_of_1996_duration_ambiguity",
        "minimum_continuous_microseconds": 3600000000,
        "duration_witness": "each_agent_and_score_predicate_contiguous_true_prefix_allowed_no_gap_or_cross_agent_join_complete_end_b_after_period_start_and_at_or_before_period_end_positive_in_period_exposure",
        "verified_extent": "actual_start_through_verified_until_only_no_forward_fill_or_future_completion",
        "short_high_dose": "preserve_original_exposure_duration_condition_not_satisfied_no_clinical_reassurance",
    },
    "cns": {
        "source": "one_actual_full_eye_verbal_motor_exam_only",
        "bands": [[15, 15, 0], [13, 14, 1], [10, 12, 2], [6, 9, 3], [3, 5, 4]],
        "policy": "measured_interpretable_only_no_nt_to_one_default_fifteen_avpu_proxy_component_fusion_or_carry_forward",
    },
    "renal": {
        "creatinine_bands": {
            "mg/dL": [["0", "1.2", True, False, 0], ["1.2", "2", True, False, 1], ["2", "3.5", True, False, 2], ["3.5", "5", True, False, 3], ["5", None, True, False, 4]],
            "umol/L": [["0", "110", True, False, 0], ["110", "171", True, False, 1], ["171", "300", True, False, 2], ["300", "440", True, True, 3], ["440", None, False, False, 4]],
        },
        "urine": {"unit": "mL/24h", "below_200": 4, "at_least_200_below_500": 3, "at_least_500_branch_contribution": 0},
        "urine_policy": "all_whole_original_intervals_exact_24h_tiling_no_overlap_gap_partial_collection_unknown_volume_or_non_patient_total_no_clip_proration_short_period_extrapolation_or_weight_normalization",
        "combine": "max_creatinine_and_urine_branch_bounds_neither_missing_branch_normal_imputed",
        "rrt": "not_a_sofa1_automatic_four_rule",
        "native_policy": "local_mimic_mgdl_and_amsterdam_si_cr440_inclusive_score3_not_exact_converted_equivalence",
    },
    "partial_policy": {
        "unknown_domain_bounds": [0, 4],
        "known_subtotal": "sum_nonnull_exact_observed_candidate_domain_maxima_not_complete_total",
        "domain_lower_bound": "retain_all_unambiguous_positive_witnesses_including_bounded_candidates",
        "domain_upper_bound": "account_for_all_unresolved_candidates_required_modalities_and_incomplete_inventory_or_protocol",
        "exact_numeric": "bounds_collapse_even_at_ceiling_does_not_assert_coverage_complete",
        "complete_total": "all_six_protocol_complete_and_within_declared_scope_and_no_unresolved_rules_or_conflicts",
        "normal_imputation": False,
    },
    "scoring_status": "local_explicit_sofa1_implementation_not_sofa2_or_manual_components",
    "diagnosis": "not_provided",
    "probability": "not_provided",
    "treatment": "not_provided",
    "clinical_validation": "not_provided",
    "prompt_handling": "provenance_only",
    "input_policy": {
        "source_policy": {
            "all_members": "complete_actual_asof_root_and_parent_manifest_no_winner_only",
            "revoked": "retained_review_excluded_no_normal_imputation",
            "current_use": "active_creation_governance_match_complete_current_source_set_and_all_parent_governance_recheck",
            "public": "typed_facts_and_review_hashes_no_free_text_patient_admission_author_or_external_stream_identity",
        },
        "input_precision": {
            "numbers": "exact_original_nonnegative_decimal_strings",
            "maximum_integer_digits": 16,
            "maximum_fraction_digits": 8,
            "rounding": "never",
            "zero_is_missing": False,
            "quantity_conversion": "only_explicit_fraction_dose_formulas_other_native_branches_never_converted",
        },
        "review": {
            "mode": "current_retrospective",
            "status": ["confirmed", "excluded", "unknown"],
            "original_flags": "preserve_no_current_review_overwrite",
            "basis": "private_statement_hash_public_only",
            "historical_prediction": False,
        },
        "population": {"adult": "yes_and_explicit_applicability_confirmation", "care_setting": ["icu", "other"], "clinical_validation": "not_provided"},
        "coverage": {
            "source_inventory": ["complete", "incomplete", "unknown"],
            "clinical_protocol": ["adequate", "incomplete", "unknown"],
            "protocol_complete": "actual_required_measurements_plus_all_members_and_resolved_conditions_never_checkbox_only",
        },
        "partial_policy": {
            "unknown_domain_bounds": [0, 4],
            "known_subtotal": "sum_nonnull_exact_observed_candidate_domain_maxima_not_complete_total",
            "domain_lower_bound": "retain_all_unambiguous_positive_witnesses_including_bounded_candidates",
            "domain_upper_bound": "account_for_all_unresolved_candidates_required_modalities_and_incomplete_inventory_or_protocol",
            "exact_numeric": "bounds_collapse_even_at_ceiling_does_not_assert_coverage_complete",
            "complete_total": "all_six_protocol_complete_and_within_declared_scope_and_no_unresolved_rules_or_conflicts",
            "normal_imputation": False,
        },
        "capacities": {
            "manifest_members": 4096,
            "private_bytes": 8388608,
            "daily_public_bytes": 2097152,
            "change_public_bytes": 6291456,
            "request_bytes": 8388608,
            "response_bytes": 8388608,
            "result_bytes": 8388608,
        },
    },
}
INPUT_POLICY = RECIPE["input_policy"]
INPUT_POLICY["gcs_confounding"] = (
    "complete_measured_EVM_interpretable_confirmed_and_current_doctor_sedation_and_other_confounding_effects_both_explicitly_excluded_no_drug_presence_inference_or_virtual_pre_sedation_score"
)
INPUT_POLICY["change"] = {
    "baseline_modes": ["observed", "conditional_zero", "unknown"],
    "observed": "same_rule_recipe_policy_independent_current_authorized_day_ends_before_current_day_and_known_infection_onset",
    "conditional_zero": "both_explicit_current_doctor_assumptions_required_else_zero_to_twentyfour_not_zero",
    "unknown": "zero_to_twentyfour_never_normal_imputed",
    "delta": "current_lower_minus_baseline_upper_current_upper_minus_baseline_lower_keep_negative_never_subtract_subtotals",
    "infection": "actual_governed_original_may_be_available_after_current_asof_explicit_late_flag_current_retrospective_only",
    "attribution": "explicit_doctor_current_review_never_automatically_inferred_from_delta_or_day_windows",
}
AXES = tuple(RECIPE["organ_order"])
MAX_MEMBERS = 4096
MAX_DAILY_PUBLIC_BYTES = 2 * 1024 * 1024
MAX_CHANGE_PUBLIC_BYTES = 6 * 1024 * 1024
MAX_REQUEST_BYTES = MAX_RESPONSE_BYTES = 8 * 1024 * 1024

RULE_REFERENCES = [
    "https://www.esicm.org/wp-content/uploads/2018/03/esicmworking5-2.pdf",
    "https://jamanetwork.com/journals/jama/fullarticle/2492881",
    "https://github.com/MIT-LCP/mimic-code/tree/303d26c623dcc9c49cc0f204468d4acc2f063797",
    "https://github.com/AmsterdamUMC/AmsterdamUMCdb/tree/5422b94dbaba6c1d9b7c301f059c425ca1fc13ce",
]
ATTRIBUTION = "Vincent et al. Intensive Care Med 1996;22:707-710; Singer et al. JAMA 2016;315:801-810. Independent local SOFA-1 native observed implementation; continuous/native boundaries and tier-duration policy are explicit local choices, not an official correction, SOFA-2, endorsement or clinical validation."


def recipe_digest():
    return hash_content(RECIPE)


def policy_digest():
    return hash_content(INPUT_POLICY)


class SofaObservedBaseline(StrictModel):
    mode: Literal["observed"]
    source: SofaSource


class SofaConditionalZeroBaseline(StrictModel):
    mode: Literal["conditional_zero"]
    no_known_preexisting_organ_dysfunction: bool
    preinfection_baseline_assumption_confirmed: bool
    basis_hash: SHA256


class SofaUnknownBaseline(StrictModel):
    mode: Literal["unknown"]
    basis_hash: SHA256


SofaBaseline = Annotated[SofaObservedBaseline | SofaConditionalZeroBaseline | SofaUnknownBaseline, Field(discriminator="mode")]


class SofaInfection(OriginalBinding):
    schema_version: Literal["infection_episode_v1"]
    support_source_id: UUIDText
    infection_status: Literal["suspected", "documented", "not_suspected", "unknown"]
    clinical_scope_start_at: UTCText
    clinical_scope_end_at: UTCText | None
    first_suspected_at: UTCText | None
    onset_at: UTCText | None
    onset_time_basis: Literal["explicit_clinician_verified_utc", "unknown"]
    current_presence: YesNoUnknown
    current_presence_basis_hash: SHA256
    onset_review: Literal["known", "unknown"]
    onset_review_basis_hash: SHA256
    late_original_available_after_current_as_of: bool

    @model_validator(mode="after")
    def original_episode(self):
        if self.source_id != f"infection_episode:{self.support_source_id}:{self.content_hash[:12]}":
            raise ValueError("感染原声明技术绑定不一致")
        if (self.onset_at is not None) != (self.onset_time_basis == "explicit_clinician_verified_utc"):
            raise ValueError("原感染onset未知不能由新判读补出时刻")
        if self.onset_review == "known" and self.onset_at is None:
            raise ValueError("当前判读不能伪造原未知onset")
        if self.clinical_scope_end_at is not None and self.clinical_scope_end_at <= self.clinical_scope_start_at:
            raise ValueError("原感染明确范围终点须晚于起点")
        clocks = [self.clinical_scope_start_at, self.clinical_scope_end_at, self.first_suspected_at, self.onset_at]
        if any(value is not None and value > self.recorded_at for value in clocks):
            raise ValueError("原感染核实范围/疑似/onset晚于其系统登记")
        return self


class SofaChangeReview(StrictModel):
    acute_change: Literal["confirmed", "not_confirmed", "unknown"]
    acute_change_basis_hash: SHA256
    attribution: Literal["infection_related", "not_related", "uncertain"]
    attribution_basis_hash: SHA256
    temporal_relation: Literal["before", "overlapping", "after", "unknown"]
    temporal_relation_basis_hash: SHA256


class SofaChangeSource(StrictModel):
    schema_version: Literal["sofa1_change_source_v1"]
    change_assessment_id: UUIDText
    source_id: TechnicalId
    content_hash: SHA256
    assessment_governance_hash: SHA256
    evaluation_at: UTCText
    current: SofaSource
    baseline: SofaBaseline
    infection: SofaInfection
    review: SofaChangeReview
    review_mode: Literal["current_retrospective_review"]
    historical_prediction: Literal[False]

    @model_validator(mode="after")
    def complete_change(self):
        if self.source_id != f"sofa_change_assessment:{self.change_assessment_id}:{self.content_hash[:12]}":
            raise ValueError("SOFA变化评估技术绑定不一致")
        if self.current.evaluation_at > self.evaluation_at or self.infection.recorded_at > self.evaluation_at:
            raise ValueError("两期当前可用原评估/感染源不能晚于变化评估登记")
        if self.infection.late_original_available_after_current_as_of != (self.infection.recorded_at > self.current.as_of):
            raise ValueError("感染原声明在历史截止后可用的标记不一致")
        if self.baseline.mode == "observed":
            baseline = self.baseline.source
            if baseline.assessment_id == self.current.assessment_id or baseline.end_at > self.current.start_at or baseline.as_of > self.current.as_of or baseline.evaluation_at > self.evaluation_at:
                raise ValueError("原基线须为独立当前可用且早于当前窗口的真实24h")
            if (baseline.rule_id, baseline.recipe_digest, baseline.policy_digest) != (self.current.rule_id, self.current.recipe_digest, self.current.policy_digest):
                raise ValueError("两期必须同一固定SOFA-1规则及原单位政策")
            if self.infection.onset_at is not None and baseline.end_at > self.infection.onset_at:
                raise ValueError("已知原感染onset时，基线整日终点须不晚于该onset")
        if len(canonical_json(self.model_dump()).encode()) > MAX_CHANGE_PUBLIC_BYTES:
            raise ValueError("完整SOFA变化公共投影超过6MiB，不截断")
        return self


class SofaChangeBinding(StrictModel):
    change_assessment_id: UUIDText
    source_id: TechnicalId
    content_hash: SHA256
    assessment_governance_hash: SHA256
    projection_hash: SHA256
    current_assessment_id: UUIDText
    current_content_hash: SHA256
    current_projection_hash: SHA256
    baseline_mode: Literal["observed", "conditional_zero", "unknown"]
    baseline_assessment_id: UUIDText | None
    baseline_content_hash: SHA256 | None
    baseline_projection_hash: SHA256 | None
    infection_source_id: TechnicalId
    infection_content_hash: SHA256
    infection_governance_hash: SHA256
    rule_id: Literal["sofa1_native_observed_v1"]
    recipe_digest: SHA256
    policy_digest: SHA256


class SofaObservedBaselineAnalysis(StrictModel):
    mode: Literal["observed"]
    analysis: SofaAnalysis


class SofaConditionalZeroBaselineAnalysis(StrictModel):
    mode: Literal["conditional_zero"]
    assumptions_confirmed: bool
    lower_bound: TotalScore
    upper_bound: TotalScore
    assumed_total_score: Literal[0] | None
    basis_hash: SHA256


class SofaUnknownBaselineAnalysis(StrictModel):
    mode: Literal["unknown"]
    lower_bound: Literal[0]
    upper_bound: Literal[24]
    basis_hash: SHA256


SofaBaselineAnalysis = Annotated[SofaObservedBaselineAnalysis | SofaConditionalZeroBaselineAnalysis | SofaUnknownBaselineAnalysis, Field(discriminator="mode")]
DeltaScore = Annotated[int, Field(strict=True, ge=-24, le=24)]


class SofaChangeAnalysis(StrictModel):
    schema_version: Literal["1"]
    source_binding: SofaChangeBinding
    rule_id: Literal["sofa1_native_observed_v1"]
    recipe_digest: SHA256
    policy_digest: SHA256
    current_analysis: SofaAnalysis
    baseline_analysis: SofaBaselineAnalysis
    scope_status: Literal["within_declared_scope", "outside_scope", "unknown"]
    calculation_status: Literal["computed", "partial", "outside_scope"]
    delta_lower_bound: DeltaScore
    delta_upper_bound: DeltaScore
    exact_numeric_delta: DeltaScore | None
    complete_delta: DeltaScore | None
    delta_threshold_status: Literal["at_least_two", "below_two", "indeterminate"]
    acute_change: Literal["confirmed", "not_confirmed", "unknown"]
    attribution: Literal["infection_related", "not_related", "uncertain"]
    temporal_relation: Literal["before", "overlapping", "after", "unknown"]
    local_runtime: SofaRuntime
    instructions_digest: SHA256
    warnings: list[TechnicalId]
    missing_data: list[TechnicalId]
    diagnosis_provided: Literal[False]
    probability_provided: Literal[False]
    treatment_provided: Literal[False]
    historical_prediction: Literal[False]
    clinical_validation: Literal["not_provided"]
    independent_implementation: Literal[True]
    attribution_statement: str
    rule_references: list[str]
