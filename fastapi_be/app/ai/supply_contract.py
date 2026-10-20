"""Closed public recorded-quantity forecasting contract; no hospital or data access."""

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

RULE_ID = "supply_recorded_quantity_v1"
MAX_BYTES = 8 * 1024 * 1024
MAX_MEMBERS = 4096
MAX_INTEGER_BITS = 200000
MAX_INTEGER_DIGITS = 60207
MAX_WORK_UNITS = 2000000000
TARGETS = ("recorded_request_quantity", "gross_fulfilled_issue_quantity", "confirmed_consumed_quantity")
MODELS = ("croston", "sba", "tsb", "prefix_mean", "last28_mean", "seasonal_naive7")
Target = Literal["recorded_request_quantity", "gross_fulfilled_issue_quantity", "confirmed_consumed_quantity"]
Model = Literal["croston", "sba", "tsb", "prefix_mean", "last28_mean", "seasonal_naive7"]
Review = Literal["confirmed", "not_confirmed", "unknown"]
Reason = Literal[
    "missing_selected_original",
    "unresolved_conflict",
    "unknown_quantity",
    "not_recorded_quantity",
    "coverage_incomplete",
    "coverage_unknown",
    "unit_not_confirmed",
    "unit_mismatch",
    "scope_not_confirmed",
    "definition_not_confirmed",
    "method_not_confirmed",
    "mixed_methods",
]
SHA256 = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
Count = Annotated[int, Field(strict=True, ge=0, le=2147483647)]
DecimalText = Annotated[str, Field(pattern=r"^(0|[1-9][0-9]{0,17})(\.[0-9]{1,6})?$")]


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
        raise ValueError("Canonical actual UTC6 clock required")
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
        raise ValueError("Invalid IANA timezone or Gregorian midnight") from exc


def day_bounds(day, timezone):
    try:
        day = date.fromisoformat(day) if isinstance(day, str) else day
        return local_midnight(day, timezone), local_midnight(day + timedelta(days=1), timezone)
    except OverflowError as exc:
        raise ValueError("Business date exceeds Gregorian range") from exc


def integer_text(value):
    """Bounded base-1e9 conversion without changing process-global int string limits."""
    if type(value) is not int or value.bit_length() > MAX_INTEGER_BITS:
        raise ValueError("Exact integer exceeds deterministic bit budget")
    if value == 0:
        return "0"
    negative, value = value < 0, abs(value)
    chunks = []
    while value:
        value, remainder = divmod(value, 1000000000)
        chunks.append(remainder)
    return ("-" if negative else "") + str(chunks[-1]) + "".join(f"{chunk:09d}" for chunk in reversed(chunks[:-1]))


def integer_value(value):
    if not isinstance(value, str) or len(value) > MAX_INTEGER_DIGITS + 1 or not re.fullmatch(r"0|-?[1-9][0-9]*", value):
        raise ValueError("Canonical bounded decimal integer required")
    negative = value.startswith("-")
    digits = value[1:] if negative else value
    result = 0
    for offset in range(0, len(digits), 9):
        part = digits[offset : offset + 9]
        result = result * 10 ** len(part) + int(part)
        if result.bit_length() > MAX_INTEGER_BITS:
            raise ValueError("Exact integer exceeds deterministic bit budget")
    return -result if negative else result


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    @model_validator(mode="before")
    @classmethod
    def literal_types(cls, value):
        if isinstance(value, dict):
            for name, field in cls.model_fields.items():
                choices = get_args(field.annotation) if get_origin(field.annotation) is Literal else ()
                if name in value and choices and all(type(item) is bool for item in choices) and type(value[name]) is not bool:
                    raise ValueError("Actual JSON boolean required")
                if name in value and choices and all(type(item) is int for item in choices) and type(value[name]) is not int:
                    raise ValueError("Actual JSON integer required")
        return value


class ExactFraction(StrictModel):
    numerator: str = Field(min_length=1, max_length=MAX_INTEGER_DIGITS + 1)
    denominator: str = Field(min_length=1, max_length=MAX_INTEGER_DIGITS)

    @model_validator(mode="after")
    def reduced(self):
        numerator, denominator = integer_value(self.numerator), integer_value(self.denominator)
        if denominator <= 0 or math.gcd(abs(numerator), denominator) != 1:
            raise ValueError("Reduced fraction with positive denominator required")
        return self

    def fraction(self):
        return Fraction(integer_value(self.numerator), integer_value(self.denominator))


def rational(value):
    value = Fraction(value)
    return {"numerator": integer_text(value.numerator), "denominator": integer_text(value.denominator)}


class SmoothingParameter(ExactFraction):
    numerator: str = Field(pattern=r"^[1-9][0-9]{0,3}$")
    denominator: str = Field(pattern=r"^[1-9][0-9]{0,3}$")

    @model_validator(mode="after")
    def reviewed_domain(self):
        if not 0 < self.fraction() <= 1 or int(self.denominator) > 1000:
            raise ValueError("Explicit smoothing parameter must be in (0,1], denominator <=1000")
        return self


class Parameters(StrictModel):
    alpha_size: SmoothingParameter
    alpha_interval: SmoothingParameter
    beta_occurrence: SmoothingParameter


class Quantity(StrictModel):
    value: DecimalText | None
    absent_reason: Literal["unknown", "not_recorded"] | None

    @model_validator(mode="after")
    def absence(self):
        if (self.value is None) != (self.absent_reason is not None):
            raise ValueError("Known zero and explicit unknown must remain distinct")
        return self


class MemberRef(StrictModel):
    source_record_id: UUID
    source_id: str = Field(max_length=110)
    kind: Literal["daily_quantity"]
    content_hash: SHA256
    governance_hash: SHA256

    @model_validator(mode="after")
    def technical_identity(self):
        if self.source_id != f"supply_day:{self.source_record_id}:{self.content_hash[:12]}":
            raise ValueError("Original identity and content hash differ")
        return self


class ManifestEntry(MemberRef):
    status: Literal["draft", "published", "rejected", "revoked"]
    eligible: bool
    selection: Literal["confirmed", "excluded", "unknown"]
    selection_basis_hash: SHA256


class DailyObservation(StrictModel):
    ref: MemberRef
    target: Target
    date: DateText
    day_start_at: UtcText
    day_end_at: UtcText
    quantity: Quantity
    unit_token: SHA256 | None
    original_unit_hash: SHA256
    unit_review: Review
    coverage: Literal["attested_complete", "incomplete", "unknown"]
    coverage_basis_hash: SHA256
    method: Literal["direct_tally", "external_register"]
    original_scope_hash: SHA256
    external_record_key_hash: SHA256 | None
    stock_constraint: Literal["none_observed", "partial", "full", "unknown"]
    stock_constraint_basis_hash: SHA256
    observed_at: UtcText
    recorded_at: UtcText
    published_at: UtcText

    @model_validator(mode="after")
    def clocks(self):
        if not self.day_start_at < self.day_end_at <= self.observed_at <= self.recorded_at <= self.published_at:
            raise ValueError("Closed day, actual observation, recording and publication clocks differ")
        return self


class Selection(StrictModel):
    target: Target
    source_id: str | None = Field(max_length=110)
    absent_reason: Literal["missing_selected_original", "unresolved_conflict"] | None

    @model_validator(mode="after")
    def explicit(self):
        if (self.source_id is None) != (self.absent_reason is not None):
            raise ValueError("Explicit selection or missing reason required")
        return self


class HistoryDay(StrictModel):
    date: DateText
    day_start_at: UtcText
    day_end_at: UtcText
    selections: list[Selection] = Field(min_length=3, max_length=3)

    @model_validator(mode="after")
    def targets(self):
        if [item.target for item in self.selections] != list(TARGETS):
            raise ValueError("Three independent targets in fixed order required")
        return self


class TargetCoverage(StrictModel):
    target: Target
    same_scope_confirmed: Review
    same_definition_confirmed: Review
    same_method_confirmed: Review
    basis_hash: SHA256


INPUT_POLICY = {
    "privacy": "opaque_item_scope_unit_tokens_typed_quantities_clocks_and_hashes_only_no_patients_prescriptions_operators_notes_names_or_raw_unit_text",
    "scope": "single_actual_sku_single_explicit_scope_single_reviewed_unit_no_implicit_conversion_or_unit_guessing",
    "targets": "recorded_requests_gross_realized_issues_and_confirmed_consumption_independent_not_latent_unconstrained_demand",
    "originals": "all_confirmed_published_eligible_nullable_whole_originals_preserved_complete_candidate_manifest_no_automatic_winner",
    "zero": "only_complete_reviewed_observed_zero_is_zero_missing_null_conflict_and_unverified_units_never_imputed",
    "stock_constraint": "independent_original_annotation_does_not_erase_measured_realized_flow_never_inferred_from_current_stock_no_latent_demand_or_obsolescence_claim",
    "returns": "gross_issue_excludes_returns_adjustments_receipts_transfers_no_absolute_value_or_netting_into_nonnegative_target",
    "calendar": "contiguous_closed_IANA_business_days_unique_actual_midnights_UTC6_no_naive_clock_inference_reject_calendar_overflow",
    "clocks": "day_end_le_observed_le_recorded_le_published_le_asof_le_captured_current_retrospective_review_not_historical_availability_guarantee",
    "freshness": "last_history_day_equals_frozen_asof_local_date_minus_one_forecast_whole_day_no_partial_today_information",
    "numbers": "original_nonnegative_decimal_text_18_integer_digits_and_at_most_6_fraction_digits_preserved_no_float_extra_precision_rejected_not_rounded",
    "parameters": "three_explicit_reduced_rationals_in_(0,1]_denominator_le_1000_no_implicit_daily_medical_recommendation_no_tuning",
    "arithmetic": "exact_stdlib_Fraction_bounded_operand_bits_work_and_incremental_UTF8_no_silent_rounding_or_truncation",
    "limits": {"max_utf8_bytes": MAX_BYTES, "max_members": MAX_MEMBERS, "max_integer_bits": MAX_INTEGER_BITS, "max_work_units": MAX_WORK_UNITS},
    "validation": "engineering_only_no_clinical_or_operational_validation",
}
RECIPE = {
    "rule_id": RULE_ID,
    "version": "1",
    "target_order": list(TARGETS),
    "model_order": list(MODELS),
    "history_days": {"min": 112, "max": 366},
    "horizon_days": [7, 14],
    "grain": "closed_business_day",
    "initialization": {
        "policy": "first_positive_elapsed_v1",
        "z": "first_positive_value",
        "q": "first_positive_one_based_day",
        "p": "1/first_positive_one_based_day",
        "minimum_positive_observations": 2,
        "nature": "local_software_policy",
    },
    "updates": {
        "croston": "on_positive_only_z_plus_alpha_size_times_y_minus_z_q_plus_alpha_interval_times_actual_calendar_interval_minus_q",
        "sba": "(1-alpha_interval/2)*z/q",
        "tsb": "each_observed_day_p_plus_beta_occurrence_times_indicator_minus_p_size_only_positive",
        "future": "fixed_origin_repeat_final_rate_do_not_simulate_unobserved_future_zeros",
    },
    "baselines": {"prefix_mean": "all_training_prefix", "last28_mean": "last_28_observed_contiguous_days", "seasonal_naive7": "repeat_last_observed_7_day_week_no_future_actuals"},
    "backtest": {
        "origins": 28,
        "step_days": 1,
        "training_lengths": "N-H-27_through_N-H_inclusive",
        "basis": "current_snapshot_retrospective",
        "overlapping_pairs": "28*H",
        "distinct_target_dates": "H+27",
        "partial": "retain_ineligible_origins_no_direct_comparison_unless_all_28_eligible",
    },
    "metrics": {
        "error": "forecast_minus_actual",
        "daily": ["mae", "mse", "me", "wape", "mase_lag1"],
        "groups": ["all_eligible_pairs", "each_lead", "each_origin_horizon_sum"],
        "mase_scale": "origin_training_prefix_mean_absolute_first_difference",
        "zero_actual_sum": "wape_null",
        "any_zero_training_scale": "mase_null_no_pair_dropping",
    },
    "selection": "none_all_six_models_reported_no_best_model_claim",
    "uncertainty": "not_provided",
    "forecast_clamp": False,
    "prompt_handling": "provenance_only",
    "operational_validation": "not_provided",
    "input_policy": INPUT_POLICY,
}


def recipe_digest():
    return hash_content(RECIPE)


def input_policy_digest():
    return hash_content(INPUT_POLICY)


class SupplySource(StrictModel):
    schema_version: Literal["supply_source_v1"]
    series_id: UUID
    source_id: str = Field(max_length=110)
    content_hash: SHA256
    governance_hash: SHA256
    profile_id: UUID
    profile_content_hash: SHA256
    profile_governance_hash: SHA256
    rule_id: Literal["supply_recorded_quantity_v1"]
    recipe_digest: SHA256
    input_policy_digest: SHA256
    scope: Literal["single_sku_single_scope_single_unit"]
    item_kind: Literal["pharmaceutical", "consumable"]
    item_token: SHA256
    scope_token: SHA256
    unit_token: SHA256
    timezone: str = Field(min_length=1, max_length=80)
    date_from: DateText
    date_to: DateText
    as_of: UtcText
    captured_at: UtcText
    historical_collection_digest: SHA256
    current_membership_digest: SHA256
    member_manifest_hash: SHA256
    parameters: Parameters
    target_coverage: list[TargetCoverage] = Field(min_length=3, max_length=3)
    days: list[HistoryDay] = Field(min_length=112, max_length=366)
    member_manifest: list[ManifestEntry] = Field(max_length=MAX_MEMBERS)
    observations: list[DailyObservation] = Field(max_length=1098)

    @model_validator(mode="after")
    def closed_source(self):
        if self.source_id != f"supply_series:{self.series_id}:{self.content_hash[:12]}" or self.recipe_digest != recipe_digest() or self.input_policy_digest != input_policy_digest():
            raise ValueError("Frozen series or fixed recipe/input policy differs")
        try:
            expected_last = datetime.fromisoformat(self.as_of.replace("Z", "+00:00")).astimezone(ZoneInfo(self.timezone)).date() - timedelta(days=1)
            last = date.fromisoformat(self.date_to)
            for lead in range(1, 15):
                day_bounds(last + timedelta(days=lead), self.timezone)
        except (ZoneInfoNotFoundError, OverflowError) as exc:
            raise ValueError("Invalid IANA timezone or Gregorian history/horizon") from exc
        if self.date_to != expected_last.isoformat() or self.captured_at < self.as_of:
            raise ValueError("Frozen history must end at the actual last closed day")
        if self.days[0].date != self.date_from or self.days[-1].date != self.date_to or [row.target for row in self.target_coverage] != list(TARGETS):
            raise ValueError("Complete date and independent target domains required")
        if self.member_manifest_hash != hash_content([row.model_dump() for row in self.member_manifest]):
            raise ValueError("Complete public candidate manifest hash differs")
        manifest = {row.source_id: row for row in self.member_manifest}
        if len(manifest) != len(self.member_manifest) or len({row.source_record_id for row in self.member_manifest}) != len(manifest):
            raise ValueError("Duplicate original identity")
        originals = {row.ref.source_id: row for row in self.observations}
        if len(originals) != len(self.observations):
            raise ValueError("Duplicate substantive original")
        for original in self.observations:
            entry = manifest.get(original.ref.source_id)
            if (
                entry is None
                or {key: getattr(entry, key) for key in MemberRef.model_fields} != original.ref.model_dump()
                or entry.status != "published"
                or not entry.eligible
                or entry.selection != "confirmed"
                or original.published_at > self.as_of
            ):
                raise ValueError("Selected nullable original differs from full current published manifest")
        if {row.source_id for row in self.member_manifest if row.status == "published" and row.eligible and row.selection == "confirmed"} != originals.keys():
            raise ValueError("Confirmed eligible whole original omitted")
        used = set()
        start = date.fromisoformat(self.date_from)
        for offset, day in enumerate(self.days):
            expected = start + timedelta(days=offset)
            if day.date != expected.isoformat() or (day.day_start_at, day.day_end_at) != day_bounds(expected, self.timezone) or day.day_end_at > self.as_of:
                raise ValueError("History must contain actual contiguous closed business days")
            for selected in day.selections:
                if selected.source_id is None:
                    continue
                original = originals.get(selected.source_id)
                if (
                    original is None
                    or original.target != selected.target
                    or original.date != day.date
                    or (original.day_start_at, original.day_end_at) != (day.day_start_at, day.day_end_at)
                    or selected.source_id in used
                ):
                    raise ValueError("Original whole target/day identity differs")
                used.add(selected.source_id)
        if used != originals.keys():
            raise ValueError("Unreferenced substantive daily original")
        if len(canonical_json(self.model_dump()).encode()) > MAX_BYTES:
            raise ValueError("Whole public source exceeds UTF8 cap; no truncation")
        return self


class SourceBinding(StrictModel):
    series_id: UUID
    source_id: str = Field(max_length=110)
    content_hash: SHA256
    governance_hash: SHA256
    profile_id: UUID
    profile_content_hash: SHA256
    profile_governance_hash: SHA256
    rule_id: Literal["supply_recorded_quantity_v1"]
    recipe_digest: SHA256
    input_policy_digest: SHA256
    member_manifest_hash: SHA256
    historical_collection_digest: SHA256
    current_membership_digest: SHA256
    projection_hash: SHA256


class State(StrictModel):
    positive_count: Count
    first_positive_day: Count | None
    last_positive_day: Count | None
    size: ExactFraction | None
    interval: ExactFraction | None
    occurrence_probability: ExactFraction | None


class Prediction(StrictModel):
    representation: Literal["constant_rate", "repeat_last_week"]
    values: list[ExactFraction] = Field(min_length=1, max_length=7)

    @model_validator(mode="after")
    def cardinality(self):
        if len(self.values) != (1 if self.representation == "constant_rate" else 7) or any(value.fraction() < 0 for value in self.values):
            raise ValueError("Exact nonnegative compact prediction cardinality differs")
        return self


class Metrics(StrictModel):
    count: Count
    unique_target_dates: Count
    error_sum: ExactFraction
    absolute_error_sum: ExactFraction
    squared_error_sum: ExactFraction
    actual_sum: ExactFraction
    me: ExactFraction
    mae: ExactFraction
    mse: ExactFraction
    wape: ExactFraction | None
    wape_undefined_reason: Literal["zero_actual_sum"] | None
    mase: ExactFraction | None
    mase_undefined_reason: Literal["zero_origin_scale"] | None
    zero_scale_count: Count


class LeadMetrics(StrictModel):
    lead_days: int = Field(strict=True, ge=1, le=14)
    metrics: Metrics | None


class Fold(StrictModel):
    origin_date: DateText
    training_days: int = Field(strict=True, ge=71, le=359)
    training_digest: SHA256
    status: Literal["complete", "insufficient_positive_observations"]
    state: State
    origin_scale: ExactFraction
    prediction: Prediction | None
    horizon_actual_sum: ExactFraction
    horizon_forecast_sum: ExactFraction | None
    horizon_error: ExactFraction | None


class ModelResult(StrictModel):
    model: Model
    status: Literal["complete", "partial_backtest", "insufficient_positive_observations", "input_unknown"]
    initialization: Literal["first_positive_elapsed_v1", "not_applicable"]
    terminal_state: State | None
    prediction: Prediction | None
    horizon_forecast_sum: ExactFraction | None
    forecast_dates: list[DateText] = Field(max_length=14)
    rolling_origins: list[Fold] = Field(max_length=28)
    eligible_origin_count: int = Field(strict=True, ge=0, le=28)
    eligible_pair_count: int = Field(strict=True, ge=0, le=392)
    distinct_target_dates: int = Field(strict=True, ge=0, le=41)
    directly_comparable: bool
    metrics: Metrics | None
    by_lead: list[LeadMetrics] = Field(max_length=14)
    cumulative_horizon_metrics: Metrics | None
    uncertainty: Literal["not_provided"]


class MissingDay(StrictModel):
    date: DateText
    source_id: str | None = Field(max_length=110)
    reasons: list[Reason] = Field(min_length=1, max_length=12)


class LastObservation(StrictModel):
    unit_token: SHA256
    date: DateText
    source_id: str = Field(max_length=110)
    value: DecimalText


class TargetAnalysis(StrictModel):
    target: Target
    status: Literal["complete", "input_unknown"]
    target_gate_reasons: list[Reason] = Field(max_length=12)
    missing_days: list[MissingDay] = Field(max_length=366)
    eligible_day_count: int = Field(strict=True, ge=0, le=366)
    observed_sum: ExactFraction | None
    known_observed_sum: ExactFraction | None
    last_day_value: DecimalText | None
    last_eligible_observation: LastObservation | None
    positive_days: Count
    zero_days: Count
    trailing_zero_days: Count | None
    stock_constrained_days: Count
    stock_constraint_unknown_days: Count
    models: list[ModelResult] = Field(min_length=6, max_length=6)

    @model_validator(mode="after")
    def model_order(self):
        if [row.model for row in self.models] != list(MODELS):
            raise ValueError("All six fixed methods must be present")
        return self


class EngineVersions(StrictModel):
    fastapi: str = Field(pattern=r"^\d+\.\d+\.\d+[A-Za-z0-9.+_-]{0,50}$")
    pydantic: str = Field(pattern=r"^\d+\.\d+\.\d+[A-Za-z0-9.+_-]{0,50}$")
    pydantic_settings: str = Field(pattern=r"^\d+\.\d+\.\d+[A-Za-z0-9.+_-]{0,50}$")
    uvicorn: str = Field(pattern=r"^\d+\.\d+\.\d+[A-Za-z0-9.+_-]{0,50}$")


class CoreHashes(StrictModel):
    supply_contract: SHA256
    supply_model: SHA256
    supply_config: SHA256
    supply_server: SHA256


class SupplyRuntime(StrictModel):
    engine: Literal["stdlib_recorded_supply_forecast"]
    python_version: str = Field(pattern=r"^\d+\.\d+\.\d+[A-Za-z0-9.+_-]{0,50}$")
    engine_versions: EngineVersions
    core_sha256: CoreHashes
    recipe_digest: SHA256
    input_policy_digest: SHA256
    timezone_database_digest: SHA256
    clinical_validation: Literal["not_provided"]
    operational_validation: Literal["not_provided"]
    prompt_handling: Literal["provenance_only"]
    coverage_guarantee: Literal["not_provided"]
    runtime_digest: SHA256
    model_version: str = Field(pattern=r"^supply:[a-f0-9]{64}$")


class SupplyAnalysis(StrictModel):
    schema_version: Literal["supply_analysis_v1"]
    source_binding: SourceBinding
    rule_id: Literal["supply_recorded_quantity_v1"]
    recipe_digest: SHA256
    input_policy_digest: SHA256
    instructions_digest: SHA256
    local_runtime: SupplyRuntime
    horizon_days: Literal[7, 14]
    evaluation_basis: Literal["current_snapshot_retrospective"]
    historical_as_of_replay: Literal[False]
    planned_origin_count: Literal[28]
    planned_pair_count: Literal[196, 392]
    distinct_planned_target_dates: Literal[34, 41]
    targets: list[TargetAnalysis] = Field(min_length=3, max_length=3)
    selected_model: Literal[None]
    forecast_only: Literal[True]
    work_units: Count

    @model_validator(mode="after")
    def closed_domain(self):
        if [row.target for row in self.targets] != list(TARGETS) or self.planned_pair_count != 28 * self.horizon_days or self.distinct_planned_target_dates != self.horizon_days + 27:
            raise ValueError("Target and overlapping-origin denominator domains differ")
        if len(canonical_json(self.model_dump()).encode()) > MAX_BYTES:
            raise ValueError("Whole exact analysis exceeds UTF8 bound; no truncation")
        return self
