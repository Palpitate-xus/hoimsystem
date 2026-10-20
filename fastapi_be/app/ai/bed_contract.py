"""Strict public physical-bed originals and exact statistical evidence; no DB or settings."""

import hashlib
import json
import math
import re
import uuid
from datetime import UTC, date, datetime, time, timedelta
from fractions import Fraction
from typing import Annotated, Literal, get_args, get_origin
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

RULE_ID = "bed_physical_daily_v1"
MAX_BYTES = 8 * 1024 * 1024
MAX_MEMBERS = 4096
TARGETS = ("occupied_physical_bed_census", "physical_admission_events", "physical_discharge_events", "physical_transfer_in_events", "physical_transfer_out_events")
RECIPES = ("weekday_mean_4w", "seasonal_naive_7d", "rolling_mean_7d", "rolling_mean_28d")
PREFIXES = {"census": "bed_census", "flow_day": "bed_flow_day", "capacity_interval": "bed_capacity_interval"}
Target = Literal["occupied_physical_bed_census", "physical_admission_events", "physical_discharge_events", "physical_transfer_in_events", "physical_transfer_out_events"]
Recipe = Literal["weekday_mean_4w", "seasonal_naive_7d", "rolling_mean_7d", "rolling_mean_28d"]
Kind = Literal["census", "flow_day", "capacity_interval"]
Method = Literal["direct_tally", "external_register"]
Review = Literal["confirmed", "not_confirmed", "unknown"]
Coverage = Literal["attested_complete", "incomplete", "unknown"]
BasisKind = Literal["observed_operational_capacity", "reviewed_future_scenario"]
CapacityReason = Literal[
    "missing_capacity_interval",
    "unknown_quantity",
    "not_recorded_quantity",
    "coverage_incomplete",
    "coverage_unknown",
    "staff_readiness_not_confirmed",
    "equipment_readiness_not_confirmed",
    "isolation_applicability_not_confirmed",
    "unresolved_capacity_overlap",
]
Reason = Literal[
    "missing_selected_original",
    "unresolved_conflict",
    "unknown_quantity",
    "not_recorded_quantity",
    "coverage_incomplete",
    "coverage_unknown",
    "boundary_not_confirmed",
    "scope_not_confirmed",
    "definition_not_confirmed",
    "method_not_confirmed",
    "mixed_methods",
]
SHA256 = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
Count = Annotated[int, Field(strict=True, ge=0, le=2147483647)]
BigUInt = Annotated[str, Field(pattern=r"^(0|[1-9][0-9]{0,1023})$")]
SignedInt = Annotated[str, Field(pattern=r"^(0|-?[1-9][0-9]{0,1023})$")]
PositiveInt = Annotated[str, Field(pattern=r"^[1-9][0-9]{0,1023}$")]


def canonical_json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def hash_content(value):
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def identity(value):
    if not isinstance(value, str) or str(uuid.UUID(value)) != value:
        raise ValueError("Canonical UUID required")
    return value


def utc(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{6}Z", value):
        raise ValueError("Canonical explicit UTC6 clock required")
    clock = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if clock.year < 1000 or clock.isoformat(timespec="microseconds").replace("+00:00", "Z") != value:
        raise ValueError("Invalid Gregorian UTC clock")
    return value


def day_text(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d\d-\d\d", value) or date.fromisoformat(value).isoformat() != value or date.fromisoformat(value).year < 1000:
        raise ValueError("Canonical Gregorian business date required")
    return value


UUID = Annotated[str, Field(pattern=r"^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$"), AfterValidator(identity)]
UtcText = Annotated[str, Field(pattern=r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{6}Z$"), AfterValidator(utc)]
DateText = Annotated[str, Field(pattern=r"^\d{4}-\d\d-\d\d$"), AfterValidator(day_text)]


def local_midnight(day, timezone):
    """Reject nonexistent/ambiguous midnight instead of guessing a DST fold."""
    try:
        zone = ZoneInfo(timezone)
        naive = datetime.combine(day, time())
        candidates = set()
        for fold in (0, 1):
            clock = naive.replace(tzinfo=zone, fold=fold).astimezone(UTC)
            if clock.astimezone(zone).replace(tzinfo=None) == naive:
                candidates.add(clock)
        if len(candidates) != 1:
            raise ValueError("Business midnight is nonexistent or ambiguous")
        return utc(next(iter(candidates)).isoformat(timespec="microseconds").replace("+00:00", "Z"))
    except (ZoneInfoNotFoundError, OverflowError) as exc:
        raise ValueError("Invalid timezone or out-of-range business midnight") from exc


def day_bounds(day, timezone):
    try:
        day = date.fromisoformat(day) if isinstance(day, str) else day
        return local_midnight(day, timezone), local_midnight(day + timedelta(days=1), timezone)
    except OverflowError as exc:
        raise ValueError("Business boundary exceeds Gregorian range") from exc


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    @model_validator(mode="before")
    @classmethod
    def exact_literal_types(cls, value):
        if isinstance(value, dict):
            for name, field in cls.model_fields.items():
                if name in value and get_origin(field.annotation) is Literal:
                    choices = get_args(field.annotation)
                    if choices and all(type(item) is bool for item in choices) and type(value[name]) is not bool:
                        raise ValueError("Boolean literals must be actual JSON booleans")
                    if choices and all(type(item) is int for item in choices) and type(value[name]) is not int:
                        raise ValueError("Integer literals must be actual JSON integers")
        return value


class ExactFraction(StrictModel):
    numerator: SignedInt
    denominator: PositiveInt

    @model_validator(mode="after")
    def canonical(self):
        if math.gcd(abs(int(self.numerator)), int(self.denominator)) != 1:
            raise ValueError("Fraction must be reduced, zero must have denominator one")
        return self

    def fraction(self):
        return Fraction(int(self.numerator), int(self.denominator))


def rational(value):
    value = Fraction(value)
    return {"numerator": str(value.numerator), "denominator": str(value.denominator)}


class Quantity(StrictModel):
    value: Count | None
    absent_reason: Literal["unknown", "not_recorded"] | None

    @model_validator(mode="after")
    def explicit_unknown(self):
        if (self.value is None) != (self.absent_reason is not None):
            raise ValueError("Known zero and explicit absence are distinct")
        return self


class MemberRef(StrictModel):
    source_record_id: UUID
    source_id: str = Field(min_length=1, max_length=110)
    kind: Kind
    content_hash: SHA256
    governance_hash: SHA256

    @model_validator(mode="after")
    def exact_kind_identity(self):
        if self.source_id != f"{PREFIXES[self.kind]}:{self.source_record_id}:{self.content_hash[:12]}":
            raise ValueError("Source kind, identity and original digest differ")
        return self


class ManifestEntry(MemberRef):
    status: Literal["draft", "published", "rejected", "revoked"]
    eligible: bool
    selection: Literal["confirmed", "excluded", "unknown"]
    selection_basis_hash: SHA256


class OriginalObservation(StrictModel):
    ref: MemberRef
    observed_at: UtcText
    recorded_at: UtcText
    published_at: UtcText
    method: Method
    coverage: Coverage
    coverage_basis_hash: SHA256
    original_scope_hash: SHA256
    external_record_key_hash: SHA256 | None

    @model_validator(mode="after")
    def original_clocks(self):
        if not self.observed_at <= self.recorded_at <= self.published_at:
            raise ValueError("Original observation, recording and publication clocks differ")
        return self


class CensusObservation(OriginalObservation):
    business_date: DateText
    census_at: UtcText
    definition: Literal["occupied_physical_beds_at_boundary_v1"]
    boundary_state_confirmed: Review
    occupied_beds: Quantity

    @model_validator(mode="after")
    def census_kind(self):
        if self.ref.kind != "census" or self.census_at > self.observed_at:
            raise ValueError("Census identity or observed boundary clock differs")
        return self


class FlowDayObservation(OriginalObservation):
    business_date: DateText
    day_start_at: UtcText
    day_end_at: UtcText
    definition: Literal["ward_physical_day_events_v1"]
    admission_events: Quantity
    discharge_events: Quantity
    transfer_in_events: Quantity
    transfer_out_events: Quantity

    @model_validator(mode="after")
    def flow_kind(self):
        if self.ref.kind != "flow_day" or not self.day_start_at < self.day_end_at <= self.observed_at:
            raise ValueError("Physical-flow identity or closed-day clock differs")
        return self


class CapacityInterval(StrictModel):
    ref: MemberRef
    start_at: UtcText
    end_at: UtcText
    basis_kind: BasisKind
    operational_total_beds: Quantity
    coverage: Coverage
    staff_readiness: Review
    equipment_readiness: Review
    isolation_applicability: Review
    capacity_definition: Literal["total_operational_physical_beds_v1"]
    capacity_basis_hash: SHA256
    observed_at: UtcText | None
    recorded_at: UtcText
    published_at: UtcText
    original_scope_hash: SHA256

    @model_validator(mode="after")
    def capacity_kind(self):
        if self.ref.kind != "capacity_interval" or self.start_at >= self.end_at or self.recorded_at > self.published_at:
            raise ValueError("Capacity identity, interval or publication differs")
        if self.basis_kind == "observed_operational_capacity":
            if self.observed_at is None or not self.end_at <= self.observed_at <= self.recorded_at:
                raise ValueError("Historical actual capacity must be closed and observed")
        elif self.observed_at is not None:
            raise ValueError("A future scenario is not an observed future fact")
        return self


class TargetCoverage(StrictModel):
    target: Target
    definition: Literal["occupied_physical_beds_at_boundary_v1", "ward_physical_day_events_v1"]
    same_scope_confirmed: Review
    same_definition_confirmed: Review
    same_method_confirmed: Review
    basis_hash: SHA256

    @model_validator(mode="after")
    def correct_definition(self):
        expected = "occupied_physical_beds_at_boundary_v1" if self.target == TARGETS[0] else "ward_physical_day_events_v1"
        if self.definition != expected:
            raise ValueError("Target and physical definition differ")
        return self


class HistoryDay(StrictModel):
    date: DateText
    day_start_at: UtcText
    day_end_at: UtcText
    census_at: UtcText
    census_source_id: str | None = Field(max_length=110)
    census_selection_reason: Literal["confirmed", "missing", "unresolved_conflict"]
    flow_source_id: str | None = Field(max_length=110)
    flow_selection_reason: Literal["confirmed", "missing", "unresolved_conflict"]
    selection_basis_hash: SHA256

    @model_validator(mode="after")
    def selected_or_missing(self):
        if self.day_start_at >= self.day_end_at or self.census_at != self.day_end_at:
            raise ValueError("Census is the explicit end boundary of a positive business day")
        for kind in ("census", "flow"):
            if (getattr(self, kind + "_source_id") is not None) != (getattr(self, kind + "_selection_reason") == "confirmed"):
                raise ValueError("Selected whole original and selection status differ")
        return self


INPUT_POLICY = {
    "privacy": "public_opaque_scope_hashes_typed_original_quantities_and_clocks_only_no_notes_names_patient_bed_ids_or_questions",
    "identity": "private_frozen_content_hash_separate_current_governance_public_manifest_hash_complete_public_projection_hash_no_cycle",
    "originals": "selected_published_current_full_nullable_originals_preserved_manifest_all_candidates_no_automatic_winner",
    "methods": ["direct_tally", "external_register"],
    "scope": "single_real_ward_same_physical_definition_reviewed_population_stable_membership_current_status_not_historical_hash",
    "clocks": "canonical_UTC6_actual_calendar_census_or_flow_end_le_observed_le_recorded_le_published_le_asof_capture_ge_asof",
    "capacity": "historical_closed_end_le_observed_le_recorded_future_scenario_observed_null_no_immediate_slots_substitution",
    "capacity_readiness": "known_total_requires_staff_readiness_equipment_readiness_isolation_applicability_all_confirmed_unknown_original_quantity_and_quality_preserved",
    "capacity_conflict": "all_selected_accepted_overlaps_are_unresolved_even_equal_counts_no_automatic_winner",
    "calendar": "IANA_actual_unique_midnight_reject_nonexistent_ambiguous_overflow_no_86400_day_assumption",
    "history": "112_to_366_contiguous_closed_business_days_unknown_target_no_fill_no_forecast_other_complete_targets_preserved",
    "forecast_first_day": "whole_business_day_may_be_partly_elapsed_at_asof_no_partial_day_data_or_runtime_now_in_fit",
    "flow_balance": "five_independent_observed_series_no_automatic_mass_conservation_or_unmet_demand_claim",
    "freshness": "date_to_is_asof_local_date_minus_one_closed_day_frozen_origin_never_rolled_forward_platform_new_execution_rechecks_current_last_closed_day",
    "arithmetic": "strict_count_0_to_2147483647_canonical_reduced_decimal_string_fractions_big_uints_no_float",
    "limits": {"max_utf8_bytes": MAX_BYTES, "max_members": MAX_MEMBERS, "max_fraction_digits": 1024},
    "validation": "independent_engineering_only_no_operational_or_clinical_validation",
}
RECIPE = {
    "rule_id": RULE_ID,
    "version": "1",
    "target_order": list(TARGETS),
    "scope": "single_ward",
    "history_days": {"min": 112, "max": 366},
    "horizon_days": [7, 14],
    "grain": "business_day",
    "primary": RECIPES[0],
    "baselines": list(RECIPES[1:]),
    "training_min_days": 28,
    "backtest": {"origins": 28, "step_days": 1, "basis": "current_snapshot_retrospective"},
    "interval": {
        "residual_window": 28,
        "minimum_residuals": 20,
        "nominal_coverage": rational(Fraction(9, 10)),
        "order": "ceil(9*(n+1)/10)",
        "target_available": "r+h<=t",
        "lower": "max(0,point-q)",
        "upper": "point+q",
        "coverage_guarantee": "not_provided",
    },
    "metrics": ["mae", "mse", "wape", "seasonal_mase_lag7"],
    "mase_zero_scale": "any_zero_in_aggregate_makes_null",
    "arithmetic": "canonical_exact_fraction_decimal_strings",
    "missing": "per_target_no_fill_no_forecast",
    "capacity": {
        "interval": "[start,end)",
        "historical": "observed_operational_capacity",
        "future": "reviewed_future_scenario",
        "integral_unit": "bed_microseconds",
        "day_mean": "integral/actual_business_day_duration_us",
        "boundary": "start<=census_at<end",
        "zero_ratio": "null",
        "forecast_clamp": False,
    },
    "prompt_handling": "provenance_only",
    "operational_validation": "not_provided",
    "input_policy": INPUT_POLICY,
}


def recipe_digest():
    return hash_content(RECIPE)


def input_policy_digest():
    return hash_content(INPUT_POLICY)


class BedSource(StrictModel):
    schema_version: Literal["bed_source_v1"]
    series_id: UUID
    source_id: str = Field(max_length=110)
    content_hash: SHA256
    governance_hash: SHA256
    rule_id: Literal["bed_physical_daily_v1"]
    recipe_digest: SHA256
    input_policy_digest: SHA256
    scope: Literal["single_ward"]
    scope_token: SHA256
    timezone: str = Field(min_length=1, max_length=80)
    target_definitions_digest: SHA256
    date_from: DateText
    date_to: DateText
    as_of: UtcText
    captured_at: UtcText
    historical_collection_digest: SHA256
    current_membership_digest: SHA256
    future_scenario_collection_digest: SHA256
    member_manifest_hash: SHA256
    target_coverage: list[TargetCoverage] = Field(min_length=5, max_length=5)
    days: list[HistoryDay] = Field(min_length=112, max_length=366)
    member_manifest: list[ManifestEntry] = Field(max_length=MAX_MEMBERS)
    census_observations: list[CensusObservation] = Field(max_length=366)
    flow_observations: list[FlowDayObservation] = Field(max_length=366)
    capacity_intervals: list[CapacityInterval] = Field(max_length=MAX_MEMBERS)

    @model_validator(mode="after")
    def complete_source(self):
        if self.source_id != f"bed_series:{self.series_id}:{self.content_hash[:12]}" or self.recipe_digest != recipe_digest() or self.input_policy_digest != input_policy_digest():
            raise ValueError("Series identity or fixed rule policy differs")
        try:
            expected_last = datetime.fromisoformat(self.as_of.replace("Z", "+00:00")).astimezone(ZoneInfo(self.timezone)).date() - timedelta(days=1)
        except (ZoneInfoNotFoundError, OverflowError) as exc:
            raise ValueError("Invalid IANA timezone or closed-day calendar") from exc
        if self.date_to != expected_last.isoformat():
            raise ValueError("History must end at the last closed business day of its frozen as_of")
        if self.captured_at < self.as_of or self.days[0].date != self.date_from or self.days[-1].date != self.date_to:
            raise ValueError("Frozen source capture and actual date range differ")
        if [item.target for item in self.target_coverage] != list(TARGETS) or self.target_definitions_digest != hash_content(
            [{"target": item.target, "definition": item.definition} for item in self.target_coverage]
        ):
            raise ValueError("All five exact target definitions must be independently declared")
        if self.member_manifest_hash != hash_content([item.model_dump() for item in self.member_manifest]):
            raise ValueError("Complete public member manifest digest differs")
        manifest = {item.source_id: item for item in self.member_manifest}
        if len(manifest) != len(self.member_manifest) or len({item.source_record_id for item in self.member_manifest}) != len(self.member_manifest):
            raise ValueError("Duplicate original identity in the complete manifest")
        substantive = [*self.census_observations, *self.flow_observations, *self.capacity_intervals]
        if len({item.ref.source_id for item in substantive}) != len(substantive):
            raise ValueError("Duplicate substantive original")
        for original in substantive:
            entry = manifest.get(original.ref.source_id)
            if (
                entry is None
                or {key: getattr(entry, key) for key in MemberRef.model_fields} != original.ref.model_dump()
                or entry.status != "published"
                or not entry.eligible
                or entry.selection != "confirmed"
                or original.published_at > self.as_of
            ):
                raise ValueError("Selected original differs from its full published current manifest identity")
        if {item.source_id for item in self.member_manifest if item.selection == "confirmed" and item.eligible and item.status == "published"} != {item.ref.source_id for item in substantive}:
            raise ValueError("A confirmed eligible whole original was omitted from the public source")
        census = {item.ref.source_id: item for item in self.census_observations}
        flow = {item.ref.source_id: item for item in self.flow_observations}
        selected_census, selected_flow = set(), set()
        start = date.fromisoformat(self.date_from)
        for offset, day in enumerate(self.days):
            try:
                expected_day = start + timedelta(days=offset)
            except OverflowError as exc:
                raise ValueError("History date overflows Gregorian range") from exc
            if day.date != expected_day.isoformat() or (day.day_start_at, day.day_end_at) != day_bounds(expected_day, self.timezone) or day.day_end_at > self.as_of:
                raise ValueError("History must be contiguous closed actual IANA business days")
            if day.census_source_id is not None:
                original = census.get(day.census_source_id)
                if original is None or original.business_date != day.date or original.census_at != day.census_at or original.ref.source_id in selected_census:
                    raise ValueError("Census day, source or explicit boundary binding differs")
                selected_census.add(original.ref.source_id)
            if day.flow_source_id is not None:
                original = flow.get(day.flow_source_id)
                if (
                    original is None
                    or original.business_date != day.date
                    or (original.day_start_at, original.day_end_at) != (day.day_start_at, day.day_end_at)
                    or original.ref.source_id in selected_flow
                ):
                    raise ValueError("Four physical day flows must bind the same whole source and day")
                selected_flow.add(original.ref.source_id)
        if selected_census != census.keys() or selected_flow != flow.keys():
            raise ValueError("Unreferenced substantive daily original")
        # Validate the largest supported horizon calendar now; never wrap dates.
        for lead in range(1, 15):
            try:
                day_bounds(date.fromisoformat(self.date_to) + timedelta(days=lead), self.timezone)
            except OverflowError as exc:
                raise ValueError("Future horizon exceeds Gregorian range") from exc
        if len(canonical_json(self.model_dump()).encode()) > MAX_BYTES:
            raise ValueError("Complete public source exceeds UTF8 cap; no truncation allowed")
        return self


class SourceBinding(StrictModel):
    series_id: UUID
    source_id: str = Field(max_length=110)
    content_hash: SHA256
    governance_hash: SHA256
    rule_id: Literal["bed_physical_daily_v1"]
    recipe_digest: SHA256
    input_policy_digest: SHA256
    member_manifest_hash: SHA256
    historical_collection_digest: SHA256
    current_membership_digest: SHA256
    future_scenario_collection_digest: SHA256
    projection_hash: SHA256


class MissingDay(StrictModel):
    date: DateText
    source_id: str | None = Field(max_length=110)
    reasons: list[Reason] = Field(min_length=1, max_length=12)


class ForecastPoint(StrictModel):
    date: DateText
    lead_days: int = Field(strict=True, ge=1, le=14)
    census_at_or_day_end_at: UtcText
    point: ExactFraction
    lower: ExactFraction
    upper: ExactFraction
    calibration_n: int = Field(strict=True, ge=20, le=28)
    calibration_order: int = Field(strict=True, ge=1, le=28)
    calibration_radius: ExactFraction
    calibration_first_origin_date: DateText
    calibration_last_target_date: DateText


class Metric(StrictModel):
    pair_count: int = Field(strict=True, ge=1, le=392)
    unique_target_dates: int = Field(strict=True, ge=1, le=41)
    absolute_error_sum: ExactFraction
    squared_error_sum: ExactFraction
    actual_sum: BigUInt
    mae: ExactFraction
    mse: ExactFraction
    wape: ExactFraction | None
    wape_undefined_reason: Literal["zero_actual_sum"] | None
    mase: ExactFraction | None
    mase_undefined_reason: Literal["zero_origin_scale"] | None
    nonzero_scale_pairs: Count
    zero_scale_pairs: Count


class LeadMetric(StrictModel):
    lead_days: int = Field(strict=True, ge=1, le=14)
    metrics: Metric


class BacktestPair(StrictModel):
    origin_date: DateText
    training_days: int = Field(strict=True, ge=28, le=366)
    lead_days: int = Field(strict=True, ge=1, le=14)
    target_date: DateText
    actual: Count
    point: ExactFraction
    origin_scale: ExactFraction
    lower: ExactFraction | None
    upper: ExactFraction | None
    calibration_n: int | None = Field(strict=True, ge=20, le=28)
    calibration_order: int | None = Field(strict=True, ge=1, le=28)
    calibration_radius: ExactFraction | None
    calibration_last_target_date: DateText | None


class RecipeBacktest(StrictModel):
    recipe: Recipe
    metrics: Metric
    by_lead: list[LeadMetric] = Field(min_length=7, max_length=14)
    pairs: list[BacktestPair] = Field(min_length=196, max_length=392)


class IntervalMetric(StrictModel):
    covered_count: Count
    evaluated_count: int = Field(strict=True, ge=1, le=392)
    empirical_coverage: ExactFraction
    unique_target_dates: int = Field(strict=True, ge=1, le=41)
    mean_width: ExactFraction
    nominal_coverage: ExactFraction
    coverage_guarantee: Literal["not_provided"]


class LeadIntervalMetric(IntervalMetric):
    lead_days: int = Field(strict=True, ge=1, le=14)


class IntervalMetrics(IntervalMetric):
    by_lead: list[LeadIntervalMetric] = Field(min_length=7, max_length=14)


class OriginScale(StrictModel):
    origin_date: DateText
    training_days: int = Field(strict=True, ge=28, le=366)
    lag_pair_count: int = Field(strict=True, ge=21, le=359)
    absolute_difference_sum: BigUInt
    scale: ExactFraction


class MaseScale(StrictModel):
    lag_days: Literal[7]
    method: Literal["origin_prefix_mean_abs_lag7"]
    origins: list[OriginScale] = Field(min_length=28, max_length=28)


class Backtest(StrictModel):
    data_basis: Literal["current_snapshot_retrospective"]
    historical_as_of_replay: Literal[False]
    origin_count: Literal[28]
    horizon_days: Literal[7, 14]
    forecast_pair_count: Literal[196, 392]
    unique_target_dates: Literal[34, 41]
    overlapping_targets: Literal[True]
    origin_from: DateText
    origin_to: DateText
    primary: RecipeBacktest
    baselines: list[RecipeBacktest] = Field(min_length=3, max_length=3)
    interval_metrics: IntervalMetrics
    mase_scale: MaseScale


class EligibleObservation(StrictModel):
    date: DateText
    value: Count
    source_id: str = Field(max_length=110)


class TargetAnalysis(StrictModel):
    target: Target
    status: Literal["complete", "input_unknown"]
    history_days: int = Field(strict=True, ge=112, le=366)
    eligible_day_count: int = Field(strict=True, ge=0, le=366)
    target_gate_reasons: list[Reason] = Field(max_length=12)
    missing_days: list[MissingDay] = Field(max_length=366)
    method: Method | None
    observed_sum: BigUInt | None
    last_eligible_observation: EligibleObservation | None
    last_day_value: Count | None
    forecast: list[ForecastPoint] | None = Field(min_length=7, max_length=14)
    backtest: Backtest | None


class CapacitySegment(StrictModel):
    start_at: UtcText
    end_at: UtcText
    duration_us: BigUInt
    status: Literal["known", "unknown", "conflict"]
    reasons: list[CapacityReason] = Field(max_length=9)
    source_ids: list[str] = Field(max_length=MAX_MEMBERS)
    operational_total_beds: Count | None
    bed_microseconds: BigUInt | None


class CapacityDayProof(StrictModel):
    date: DateText
    day_start_at: UtcText
    day_end_at: UtcText
    day_duration_us: BigUInt
    basis_kind: BasisKind
    status: Literal["complete", "partial", "unknown"]
    segments: list[CapacitySegment] = Field(min_length=1, max_length=2 * MAX_MEMBERS + 1)
    known_duration_us: BigUInt
    unknown_duration_us: BigUInt
    conflict_duration_us: BigUInt
    known_bed_microseconds: BigUInt | None
    total_bed_microseconds: BigUInt | None
    mean_operational_beds: ExactFraction | None
    local_discharge_events_per_mean_operational_bed: ExactFraction | None
    ratio_undefined_reason: Literal["capacity_unknown", "zero_capacity_integral", "discharge_unknown"] | None


class BoundaryPressure(StrictModel):
    date: DateText
    census_at: UtcText
    status: Literal["known", "forecast_unknown", "capacity_unknown", "capacity_conflict"]
    capacity_status: Literal["known", "unknown", "conflict"]
    capacity_reasons: list[CapacityReason] = Field(max_length=9)
    capacity_source_ids: list[str] = Field(max_length=MAX_MEMBERS)
    operational_total_beds: Count | None
    point_minus_capacity: ExactFraction | None
    lower_minus_capacity: ExactFraction | None
    upper_minus_capacity: ExactFraction | None
    point_relation: Literal["below", "equal", "above"] | None
    interval_relation: Literal["entirely_below", "touches", "straddles", "entirely_above"] | None
    point_to_capacity_ratio: ExactFraction | None
    ratio_undefined_reason: Literal["zero_capacity", "forecast_unknown", "capacity_unknown", "capacity_conflict"] | None


class BedRuntime(StrictModel):
    engine: Literal["stdlib_physical_bed_forecast"]
    python_version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    engine_versions: dict[str, str] = Field(min_length=4, max_length=4)
    core_sha256: dict[str, SHA256] = Field(min_length=4, max_length=4)
    recipe_digest: SHA256
    input_policy_digest: SHA256
    timezone_database_digest: SHA256
    clinical_validation: Literal["not_provided"]
    operational_validation: Literal["not_provided"]
    prompt_handling: Literal["provenance_only"]
    coverage_guarantee: Literal["not_provided"]
    runtime_digest: SHA256
    model_version: str = Field(pattern=r"^bed:[a-f0-9]{64}$")


class BedAnalysis(StrictModel):
    schema_version: Literal["bed_analysis_v1"]
    source_binding: SourceBinding
    rule_id: Literal["bed_physical_daily_v1"]
    horizon_days: Literal[7, 14]
    history_days: int = Field(strict=True, ge=112, le=366)
    primary_census_status: Literal["complete", "input_unknown"]
    targets: list[TargetAnalysis] = Field(min_length=5, max_length=5)
    capacity_days: list[CapacityDayProof] = Field(min_length=112, max_length=366)
    future_pressure: list[BoundaryPressure] = Field(min_length=7, max_length=14)
    summary_status: Literal["all_targets_complete", "partial_targets", "no_complete_targets"]
    instructions_digest: SHA256
    local_runtime: BedRuntime
