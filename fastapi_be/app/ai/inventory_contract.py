"""Closed single-SKU finite purchase-plan comparison; no hospital access or I/O."""

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

RULE_ID = "inventory_declared_candidate_plans_v1"
MAX_BYTES = 8 * 1024 * 1024
MAX_CANDIDATES = 256
MAX_INITIAL_LOTS = 4096
MAX_RECEIPT_LOTS = 8192
MAX_ORDERS = 8192
MAX_WORK_UNITS = 20000000
MAX_INTEGER_BITS = 4096
MAX_INTEGER_DIGITS = 1234
KINDS = ("inventory_observation", "future_quantity_scenario", "purchase_candidate_plan")
FactKind = Literal["inventory_observation", "future_quantity_scenario", "purchase_candidate_plan"]
Review = Literal["confirmed", "not_confirmed", "unknown"]
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


class Amount(StrictModel):
    value: DecimalText | None
    absent_reason: Literal["unknown", "not_recorded"] | None
    unit_token: SHA256 | None
    original_unit_hash: SHA256
    unit_review: Review

    @model_validator(mode="after")
    def absence(self):
        if (self.value is None) != (self.absent_reason is not None):
            raise ValueError("Known zero and explicit absent quantity must remain distinct")
        return self


class DateValue(StrictModel):
    value: DateText | None
    absent_reason: Literal["unknown", "not_applicable"] | None

    @model_validator(mode="after")
    def absence(self):
        if (self.value is None) != (self.absent_reason is not None):
            raise ValueError("Known date, unknown date and reviewed non-expiry differ")
        return self


class LegacyAmount(Amount):
    """Preserve finite signed legacy stock; negative originals are not usable inventory."""

    value: Annotated[str, Field(pattern=r"^(0|-?[1-9][0-9]{0,17})(\.[0-9]{1,6})?$")] | None


class ArrivalDate(DateValue):
    absent_reason: Literal["unknown"] | None


class FactRef(StrictModel):
    source_record_id: UUID
    source_id: str = Field(max_length=110)
    kind: FactKind
    content_hash: SHA256
    governance_hash: SHA256
    recorded_at: UtcText
    published_at: UtcText

    @model_validator(mode="after")
    def identity_and_clock(self):
        if self.source_id != f"inventory_fact:{self.source_record_id}:{self.content_hash[:12]}":
            raise ValueError("Original inventory identity and content differ")
        if self.recorded_at > self.published_at:
            raise ValueError("Original recording cannot follow publication")
        return self


class Constraint(StrictModel):
    mode: Literal["known", "unknown", "not_applicable"]
    amount: Amount | None

    @model_validator(mode="after")
    def tagged_amount(self):
        if (self.mode == "known") != (self.amount is not None):
            raise ValueError("A known constraint has one explicit amount; other modes have none")
        if self.amount is not None and self.amount.value is None:
            raise ValueError("Known constraint cannot contain an absent numeric value")
        return self


class InitialLot(StrictModel):
    lot_id: UUID
    quantity: Amount
    frozen_quantity: Amount
    valid_through: DateValue
    expiry_review: Review
    frozen_review: Review


class LegacyStockSnapshot(StrictModel):
    captured_at: UtcText
    collection_digest: SHA256
    catalog_quantity: LegacyAmount
    batch_quantity_sum: LegacyAmount | None
    batch_applicability: Literal["applicable", "not_applicable", "unknown"]
    reconciliation: Review
    basis_hash: SHA256

    @model_validator(mode="after")
    def batch_domain(self):
        if self.batch_applicability == "applicable" and self.batch_quantity_sum is None:
            raise ValueError("Applicable batch inventory must preserve its explicit total")
        if self.batch_applicability == "not_applicable" and self.batch_quantity_sum is not None:
            raise ValueError("No invented legacy batch total for an unbatched item")
        return self


class StockObservation(StrictModel):
    ref: FactRef
    observed_at: UtcText | None
    method: Literal["independent_count", "legacy_current_capture"]
    professional_review: Review
    scope_review: Review
    coverage: Literal["attested_complete", "incomplete", "unknown"]
    coverage_basis_hash: SHA256
    lots: list[InitialLot] = Field(max_length=MAX_INITIAL_LOTS)
    declared_total_quantity: Amount
    physical_reconciliation: Review
    reconciliation_basis_hash: SHA256
    legacy_snapshot: LegacyStockSnapshot

    @model_validator(mode="after")
    def clocks_and_identity(self):
        if self.ref.kind != "inventory_observation":
            raise ValueError("Stock observation must retain its own original kind")
        if self.method == "legacy_current_capture" and self.observed_at is not None:
            raise ValueError("Current database capture is not an actual historical physical observation")
        if self.method == "independent_count" and self.observed_at is None:
            raise ValueError("Independent stock count requires its actual observation clock")
        if self.observed_at is not None and self.observed_at > self.ref.recorded_at:
            raise ValueError("Physical stock observation cannot follow its original recording")
        if self.legacy_snapshot.captured_at > self.ref.recorded_at:
            raise ValueError("Actual legacy snapshot capture cannot follow original recording")
        if len({lot.lot_id for lot in self.lots}) != len(self.lots):
            raise ValueError("Initial physical lot identities must be unique")
        # Raw numeric conflicts remain in the public facts. The model reports
        # unknown rather than picking the catalog, batches or physical count.
        return self


class InventoryPolicy(StrictModel):
    event_order: Literal["expire_then_receive_then_fefo_draw_then_check_v1"]
    expiry_semantics: Literal["valid_through_inclusive"]
    allocation: Literal["fefo_expiry_then_lot_id"]
    stockout: Literal["all_reviewed_daily_quantities_must_be_met"]
    frozen_policy: Literal["frozen_quantity_unavailable_until_expiry"]
    policy_review: Review
    basis_hash: SHA256


class Assumptions(StrictModel):
    opening_carry_forward: Review
    no_other_inventory_changes: Review
    frozen_quantities_unchanged: Review
    basis_hash: SHA256


class ScenarioDay(StrictModel):
    date: DateText
    required_quantity: Amount
    minimum_end_usable: Constraint
    maximum_end_total: Constraint


class FutureQuantityScenario(StrictModel):
    ref: FactRef
    basis: Literal["reviewed_operational_scenario"]
    quantity_definition: Literal["planned_physical_stock_drawdown"]
    scope_review: Review
    coverage: Literal["attested_complete", "incomplete", "unknown"]
    days: list[ScenarioDay] = Field(min_length=1, max_length=31)
    budget: Constraint
    policy: InventoryPolicy
    assumptions: Assumptions

    @model_validator(mode="after")
    def original_kind(self):
        if self.ref.kind != "future_quantity_scenario":
            raise ValueError("Future scenario must retain its original kind")
        return self


class ReceiptLot(InitialLot):
    arrival_date: ArrivalDate
    unit_price: Amount
    price_basis_review: Review


class Order(StrictModel):
    order_id: UUID
    order_fixed_fee: Amount
    lines: list[ReceiptLot] = Field(min_length=1, max_length=MAX_RECEIPT_LOTS)


class CandidatePlan(StrictModel):
    ref: FactRef
    candidate_id: UUID
    completeness: Literal["attested_complete", "incomplete", "unknown"]
    completeness_basis_hash: SHA256
    plan_fixed_fee: Amount
    orders: list[Order] = Field(max_length=MAX_ORDERS)

    @model_validator(mode="after")
    def original_kind_and_members(self):
        if self.ref.kind != "purchase_candidate_plan":
            raise ValueError("Candidate must retain its complete original plan kind")
        orders, lots = set(), set()
        for order in self.orders:
            if order.order_id in orders:
                raise ValueError("Order identity repeated within one indivisible candidate")
            orders.add(order.order_id)
            for lot in order.lines:
                if lot.lot_id in lots:
                    raise ValueError("Receipt lot identity repeated within one candidate")
                lots.add(lot.lot_id)
        return self


INPUT_POLICY = {
    "scope": "single_sku_single_reviewed_physical_scope_quantity_unit_and_cost_unit",
    "numbers": "nonnegative_original_decimal_text_18_integer_6_fraction_digits_exact_no_conversion_zero_not_null",
    "cost": "same_explicit_cost_unit_unit_price_per_one_reviewed_quantity_unit_plus_order_and_plan_fees_no_inferred_catalog_price",
    "opening": "independent_count_actual_observed_clock_professional_review_complete_legacy_reconciliation_and_explicit_carry_forward_required_database_capture_alone_unknown",
    "conflicts": "preserve_raw_catalog_batch_count_frozen_and_unit_conflicts_as_unknown_never_choose_or_reconcile_automatically_signed_legacy_negative_preserved_but_invalid_for_inventory",
    "plans": "explicit_finite_indivisible_complete_candidates_shared_scenario_budget_no_line_recombination",
    "expiry": "reviewed_valid_through_inclusive_or_explicit_non_expiring_unknown_never_normalized",
    "future": "reviewed_daily_physical_drawdown_scenario_not_latent_demand_no_other_changes_and_static_frozen_quantity_explicit",
    "privacy": "opaque_scenario_tokens_closed_typed_facts_actual_source_sha_no_free_text_names_or_raw_unit_currency",
    "unknown": "unknown_candidate_blocks_proven_best_or_infeasible_for_declared_set_known_feasible_subset_only",
    "limits": {
        "utf8_bytes": MAX_BYTES,
        "candidates": MAX_CANDIDATES,
        "initial_lots": MAX_INITIAL_LOTS,
        "receipt_lots_total": MAX_RECEIPT_LOTS,
        "orders_total": MAX_ORDERS,
        "days": 31,
        "work_units": MAX_WORK_UNITS,
        "integer_bits": MAX_INTEGER_BITS,
    },
}
RECIPE = {
    "rule_id": RULE_ID,
    "version": "inventory_declared_candidate_plans_v1",
    "event_order": [
        "expire_existing_valid_through_before_date",
        "receive_then_immediately_remove_expired_arrivals",
        "fefo_drawdown_excludes_frozen",
        "check_daily_residual_and_shared_budget_constraints",
    ],
    "expiry": "valid_through_inclusive_non_expiring_after_all_dated_lots",
    "tie_break": "canonical_lot_uuid",
    "cost": "all_ordered_quantity_times_unit_price_plus_every_declared_order_fixed_fee_plus_plan_fixed_fee_including_unused_and_expired_receipts",
    "objective": "minimum_exact_declared_purchase_cost_among_feasible_whole_candidates_return_all_ties_no_automatic_selection",
    "feasibility": "all_reviewed_daily_drawdown_met_and_all_explicit_shared_budget_minimum_end_usable_maximum_end_total_rules_satisfied",
    "proof_scope": "only_complete_explicit_finite_declared_candidates_not_all_possible_procurement_combinations",
    "balance": "opening_plus_receipts_equals_allocated_plus_projected_expired_plus_closing_and_closing_equals_usable_plus_frozen",
    "projection_only": True,
    "prompt_handling": "provenance_only",
    "input_policy": INPUT_POLICY,
}


def recipe_digest():
    return hash_content(RECIPE)


def input_policy_digest():
    return hash_content(INPUT_POLICY)


class InventorySource(StrictModel):
    schema_version: Literal["inventory_source_v1"]
    scenario_id: UUID
    source_id: str = Field(max_length=110)
    content_hash: SHA256
    governance_hash: SHA256
    profile_id: UUID
    profile_content_hash: SHA256
    profile_governance_hash: SHA256
    rule_id: Literal["inventory_declared_candidate_plans_v1"]
    recipe_digest: SHA256
    input_policy_digest: SHA256
    scope: Literal["single_sku_single_physical_scope_single_quantity_and_cost_unit"]
    item_kind: Literal["pharmaceutical", "consumable"]
    item_token: SHA256
    scope_token: SHA256
    quantity_unit_token: SHA256
    cost_unit_token: SHA256
    timezone: str = Field(min_length=1, max_length=100)
    as_of: UtcText
    captured_at: UtcText
    date_from: DateText
    date_to: DateText
    declared_candidate_ids: list[UUID] = Field(min_length=1, max_length=MAX_CANDIDATES)
    candidate_set_review: Review
    candidate_set_basis_hash: SHA256
    member_manifest: list[FactRef] = Field(min_length=3, max_length=MAX_CANDIDATES + 2)
    member_manifest_hash: SHA256
    observation: StockObservation
    scenario: FutureQuantityScenario
    candidates: list[CandidatePlan] = Field(min_length=1, max_length=MAX_CANDIDATES)

    @model_validator(mode="after")
    def complete_domain(self):
        if self.source_id != f"inventory_scenario:{self.scenario_id}:{self.content_hash[:12]}":
            raise ValueError("Scenario source identity and original private content differ")
        if self.captured_at < self.as_of:
            raise ValueError("Scenario cannot capture a future original availability cutoff")
        batch_domain = self.observation.legacy_snapshot.batch_applicability
        if (self.item_kind == "pharmaceutical" and batch_domain == "not_applicable") or (self.item_kind == "consumable" and batch_domain == "applicable"):
            raise ValueError("Legacy batch applicability must retain the actual SKU kind; unknown remains unknown")
        if self.recipe_digest != recipe_digest() or self.input_policy_digest != input_policy_digest():
            raise ValueError("A new execution requires this exact reviewed fixed recipe and policy")
        try:
            zone = ZoneInfo(self.timezone)
            today = datetime.fromisoformat(self.as_of.replace("Z", "+00:00")).astimezone(zone).date()
            first, last = date.fromisoformat(self.date_from), date.fromisoformat(self.date_to)
            days = (last - first).days + 1
            if not 1 <= days <= 31 or first <= today:
                raise ValueError("Inventory planning requires 1..31 consecutive future business dates")
            expected = [(first + timedelta(days=i)).isoformat() for i in range(days)]
            for day in expected:
                day_bounds(day, self.timezone)
        except (ZoneInfoNotFoundError, OverflowError) as exc:
            raise ValueError("Invalid IANA timezone or Gregorian planning boundary") from exc
        if [day.date for day in self.scenario.days] != expected:
            raise ValueError("Every reviewed future date must appear once in chronological order")
        candidate_ids = [candidate.candidate_id for candidate in self.candidates]
        if candidate_ids != self.declared_candidate_ids or len(set(candidate_ids)) != len(candidate_ids):
            raise ValueError("Whole declared finite candidate membership differs or repeats")
        refs = [self.observation.ref, self.scenario.ref, *(row.ref for row in self.candidates)]
        if len({ref.source_record_id for ref in refs}) != len(refs) or [row.model_dump() for row in self.member_manifest] != [row.model_dump() for row in refs]:
            raise ValueError("Manifest must bind exactly every whole selected original without duplicates or omissions")
        if hash_content([row.model_dump() for row in self.member_manifest]) != self.member_manifest_hash:
            raise ValueError("Public manifest canonical SHA differs")
        if any(ref.published_at > self.as_of for ref in refs):
            raise ValueError("Selected original was unavailable at this declared cutoff")
        initial_ids = {row.lot_id for row in self.observation.lots}
        orders = lines = 0
        for candidate in self.candidates:
            orders += len(candidate.orders)
            for order in candidate.orders:
                lines += len(order.lines)
                for lot in order.lines:
                    if lot.lot_id in initial_ids:
                        raise ValueError("An arrival cannot duplicate existing physical opening stock")
                    if lot.arrival_date.value is not None and not self.date_from <= lot.arrival_date.value <= self.date_to:
                        raise ValueError("All declared paid receipts must be inside the comparison horizon")
        if orders > MAX_ORDERS or lines > MAX_RECEIPT_LOTS:
            raise ValueError("Whole candidate order/receipt count exceeds policy; no truncation")
        if len(canonical_json(self.model_dump()).encode()) > MAX_BYTES:
            raise ValueError("Whole public inventory Source exceeds UTF8 bound; no truncation")
        return self


class SourceBinding(StrictModel):
    scenario_id: UUID
    source_id: str = Field(max_length=110)
    content_hash: SHA256
    governance_hash: SHA256
    profile_id: UUID
    profile_content_hash: SHA256
    profile_governance_hash: SHA256
    rule_id: Literal["inventory_declared_candidate_plans_v1"]
    recipe_digest: SHA256
    input_policy_digest: SHA256
    member_manifest_hash: SHA256
    projection_hash: SHA256


Reason = Literal[
    "opening_not_independently_observed",
    "professional_review_not_confirmed",
    "scope_not_confirmed",
    "coverage_incomplete",
    "coverage_unknown",
    "unknown_quantity",
    "quantity_unit_unknown",
    "quantity_unit_mismatch",
    "cost_unit_unknown",
    "cost_unit_mismatch",
    "initial_total_conflict",
    "frozen_exceeds_quantity",
    "legacy_reconciliation_unknown",
    "legacy_batch_applicability_unknown",
    "legacy_quantity_unknown",
    "invalid_original_inventory_quantity",
    "physical_reconciliation_unknown",
    "unknown_frozen_quantity",
    "frozen_review_not_confirmed",
    "unknown_expiry",
    "expiry_review_not_confirmed",
    "unknown_arrival",
    "unknown_cost",
    "price_basis_not_confirmed",
    "candidate_incomplete",
    "candidate_set_not_confirmed",
    "opening_carry_forward_not_confirmed",
    "other_changes_not_confirmed",
    "frozen_continuation_not_confirmed",
    "policy_not_confirmed",
    "unknown_constraint",
]


class Allocation(StrictModel):
    lot_id: UUID
    quantity: ExactFraction


class Violation(StrictModel):
    code: Literal["unmet_scenario_quantity", "minimum_usable_not_met", "maximum_total_exceeded", "budget_exceeded"]
    date: DateText | None
    actual: ExactFraction
    limit: ExactFraction


class DayLedger(StrictModel):
    date: DateText
    day_start_at: UtcText
    day_end_at: UtcText
    opening_total: ExactFraction
    arrived: ExactFraction
    expired: ExactFraction
    allocated: ExactFraction
    unmet: ExactFraction
    closing_total: ExactFraction
    closing_usable: ExactFraction
    closing_frozen: ExactFraction
    allocations: list[Allocation] = Field(max_length=MAX_INITIAL_LOTS + MAX_RECEIPT_LOTS)
    expired_lots: list[Allocation] = Field(max_length=MAX_INITIAL_LOTS + MAX_RECEIPT_LOTS)
    received_lot_ids: list[UUID] = Field(max_length=MAX_RECEIPT_LOTS)
    lot_state_digest: SHA256


class LotBalance(StrictModel):
    lot_id: UUID
    quantity: ExactFraction
    frozen_quantity: ExactFraction


class Totals(StrictModel):
    ordered: ExactFraction | None
    received: ExactFraction | None
    fulfilled: ExactFraction | None
    unmet: ExactFraction | None
    expired: ExactFraction | None
    ending_total: ExactFraction | None
    ending_usable: ExactFraction | None
    ending_frozen: ExactFraction | None


class CandidateResult(StrictModel):
    candidate_id: UUID
    source_ref: FactRef
    status: Literal["feasible", "infeasible", "unknown"]
    inventory_status: Literal["feasible", "infeasible", "unknown"]
    cost_status: Literal["known", "unknown"]
    budget_status: Literal["satisfied", "violated", "unknown", "not_applicable"]
    total_cost: ExactFraction | None
    known_cost_subtotal: ExactFraction | None
    reasons: list[Reason] = Field(max_length=40)
    violations: list[Violation] = Field(max_length=94)
    daily: list[DayLedger] | None = Field(max_length=31)
    terminal_lots: list[LotBalance] | None = Field(max_length=MAX_INITIAL_LOTS + MAX_RECEIPT_LOTS)
    totals: Totals


class EngineVersions(StrictModel):
    fastapi: str = Field(pattern=r"^\d+\.\d+\.\d+[A-Za-z0-9.+_-]{0,50}$")
    pydantic: str = Field(pattern=r"^\d+\.\d+\.\d+[A-Za-z0-9.+_-]{0,50}$")
    pydantic_settings: str = Field(pattern=r"^\d+\.\d+\.\d+[A-Za-z0-9.+_-]{0,50}$")
    uvicorn: str = Field(pattern=r"^\d+\.\d+\.\d+[A-Za-z0-9.+_-]{0,50}$")


class CoreHashes(StrictModel):
    inventory_contract: SHA256
    inventory_model: SHA256
    inventory_config: SHA256
    inventory_server: SHA256


class InventoryRuntime(StrictModel):
    engine: Literal["stdlib_declared_inventory_candidates"]
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
    model_version: str = Field(pattern=r"^inventory:[a-f0-9]{64}$")


class InventoryAnalysis(StrictModel):
    schema_version: Literal["inventory_analysis_v1"]
    source_binding: SourceBinding
    rule_id: Literal["inventory_declared_candidate_plans_v1"]
    recipe_digest: SHA256
    input_policy_digest: SHA256
    instructions_digest: SHA256
    local_runtime: InventoryRuntime
    scope: Literal["declared_finite_candidate_set"]
    status: Literal["complete_comparison", "candidate_set_unknown", "input_unknown"]
    candidate_results: list[CandidateResult] = Field(min_length=1, max_length=MAX_CANDIDATES)
    best_known_feasible_candidate_ids: list[UUID] = Field(max_length=MAX_CANDIDATES)
    best_known_feasible_cost: ExactFraction | None
    best_among_declared_candidates: bool
    all_declared_candidates_proven_infeasible: bool
    candidate_count: int = Field(strict=True, ge=1, le=MAX_CANDIDATES)
    known_feasible_count: Count
    known_infeasible_count: Count
    unknown_count: Count
    automatically_selected_candidate: Literal[None]
    projection_only: Literal[True]
    work_units: int = Field(strict=True, ge=0, le=MAX_WORK_UNITS)

    @model_validator(mode="after")
    def closed_domain(self):
        ids = [row.candidate_id for row in self.candidate_results]
        if len(set(ids)) != len(ids) or self.candidate_count != len(ids):
            raise ValueError("Comparison cannot duplicate or omit declared candidates")
        counts = [sum(row.status == status for row in self.candidate_results) for status in ("feasible", "infeasible", "unknown")]
        if counts != [self.known_feasible_count, self.known_infeasible_count, self.unknown_count]:
            raise ValueError("Known and unknown candidate counts differ")
        if self.unknown_count and (self.best_among_declared_candidates or self.all_declared_candidates_proven_infeasible):
            raise ValueError("An unknown candidate prevents a proof about the whole declared set")
        if len(canonical_json(self.model_dump()).encode()) > MAX_BYTES:
            raise ValueError("Whole exact inventory proof exceeds UTF8 bound; no truncation")
        return self
