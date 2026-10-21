"""Private original facts. No public tokens, inferred units or default reviews."""

from datetime import date, timedelta
from typing import Annotated, Literal

from pydantic import Field, model_validator

from app.ai.inventory_contract import SHA256, UUID, ArrivalDate, DateText, DateValue, DecimalText, Review, StrictModel, UtcText, day_bounds
from app.ai.supply_source_input import ProfessionalAttestation, SourceReview, SourceRevoke, check_basis

Positive = Annotated[int, Field(strict=True, gt=0, le=2147483647)]
Basis = Annotated[str, Field(min_length=20, max_length=4000)]
ItemKind = Literal["pharmaceutical", "consumable"]
SourceKind = Literal["inventory_observation", "future_quantity_scenario", "purchase_candidate_plan"]
SOURCE_ROLES = frozenset({"admin", "director", "pharmacist", "super_admin"})


def original_text(value, maximum):
    if value is not None and (not value.strip() or len(value.encode()) > maximum * 4):
        raise ValueError("An original text must be nonblank and UTF8 bounded; unknown stays null")
    return value


class Quantity(StrictModel):
    value: DecimalText | None
    absent_reason: Literal["unknown", "not_recorded"] | None
    original_unit_text: str | None = Field(max_length=120)
    unit_review: Review

    @model_validator(mode="after")
    def original_amount(self):
        if (self.value is None) != (self.absent_reason is not None):
            raise ValueError("Original zero and an absent quantity differ")
        original_text(self.original_unit_text, 120)
        if self.unit_review == "confirmed" and self.original_unit_text is None:
            raise ValueError("An explicitly confirmed quantity unit cannot be unknown")
        return self


class Cost(StrictModel):
    value: DecimalText | None
    absent_reason: Literal["unknown", "not_recorded"] | None
    currency_text: str | None = Field(max_length=32)
    original_cost_unit_text: str | None = Field(max_length=120)
    unit_review: Review

    @model_validator(mode="after")
    def original_cost(self):
        if (self.value is None) != (self.absent_reason is not None):
            raise ValueError("Zero cost cannot replace an unknown original price")
        original_text(self.currency_text, 32)
        original_text(self.original_cost_unit_text, 120)
        if self.unit_review == "confirmed" and (self.currency_text is None or self.original_cost_unit_text is None):
            raise ValueError("Confirmed currency and cost unit require both original texts")
        return self


class InitialLot(StrictModel):
    lot_id: UUID
    original_lot_key: str | None = Field(max_length=200)
    quantity: Quantity
    frozen_quantity: Quantity
    valid_through: DateValue
    expiry_review: Review
    frozen_review: Review

    @model_validator(mode="after")
    def own_lot(self):
        original_text(self.original_lot_key, 200)
        return self


def professional_fields(value):
    """A technical record/publication alone never supplies a professional claim."""
    if isinstance(value, dict):
        for key, child in value.items():
            if key == "professional_attestation":
                continue
            if (key.endswith("_review") or key in {"physical_reconciliation", "legacy_reconciliation"}) and child == "confirmed":
                return True
            if key in {"coverage", "completeness"} and child == "attested_complete":
                return True
            if professional_fields(child):
                return True
    elif isinstance(value, list):
        return any(professional_fields(item) for item in value)
    return False


class OriginalPayload(StrictModel):
    definition_basis_note: Basis
    professional_attestation: ProfessionalAttestation

    @model_validator(mode="after")
    def qualified_claims(self):
        check_basis(self.definition_basis_note)
        if self.professional_attestation.status != "confirmed" and professional_fields(self.model_dump(mode="json")):
            raise ValueError("Unconfirmed technical originals cannot sign professional completeness or unit claims")
        return self


class InventoryObservation(OriginalPayload):
    kind: Literal["inventory_observation"]
    method: Literal["independent_count", "legacy_current_capture"]
    observed_at: UtcText | None
    scope_review: Review
    coverage: Literal["attested_complete", "incomplete", "unknown"]
    coverage_basis_note: Basis
    lots: list[InitialLot] = Field(max_length=4096)
    declared_total_quantity: Quantity
    physical_reconciliation: Review
    reconciliation_basis_note: Basis
    legacy_reconciliation: Review
    legacy_reconciliation_basis_note: Basis

    @model_validator(mode="after")
    def actual_observation(self):
        if (self.method == "independent_count") != (self.observed_at is not None):
            raise ValueError("Only independent counting has an actual physical observed_at; database capture never invents one")
        if len({row.lot_id for row in self.lots}) != len(self.lots):
            raise ValueError("Original physical lot identities must be unique")
        for note in (self.coverage_basis_note, self.reconciliation_basis_note, self.legacy_reconciliation_basis_note):
            check_basis(note)
        # Numeric catalog/lot/frozen contradictions are retained as originals.
        # They prevent a known native inventory result, not original recording.
        return self


class PlannedDay(StrictModel):
    date: DateText
    day_start_at: UtcText
    day_end_at: UtcText
    required_quantity: Quantity


def period(value):
    first, last = date.fromisoformat(value.date_from), date.fromisoformat(value.date_to)
    count = (last - first).days + 1
    if not 1 <= count <= 31:
        raise ValueError("One to31 complete future IANA business days required")
    result = []
    for offset in range(count):
        day = (first + timedelta(days=offset)).isoformat()
        start, end = day_bounds(day, value.timezone)
        result.append((day, start, end))
    return result


class FutureQuantityScenario(OriginalPayload):
    kind: Literal["future_quantity_scenario"]
    timezone: str = Field(min_length=1, max_length=100)
    date_from: DateText
    date_to: DateText
    basis: Literal["reviewed_operational_scenario"]
    quantity_definition: Literal["planned_physical_stock_drawdown"]
    scope_review: Review
    coverage: Literal["attested_complete", "incomplete", "unknown"]
    coverage_basis_note: Basis
    days: list[PlannedDay] = Field(min_length=1, max_length=31)

    @model_validator(mode="after")
    def complete_explicit_days(self):
        if [(row.date, row.day_start_at, row.day_end_at) for row in self.days] != period(self):
            raise ValueError("Every original future day and its actual IANA UTC bounds must appear once in order")
        check_basis(self.coverage_basis_note)
        return self


class ReceiptLot(InitialLot):
    arrival_date: ArrivalDate
    unit_price: Cost
    price_basis_review: Review
    price_basis_note: Basis

    @model_validator(mode="after")
    def original_per_unit_cost(self):
        check_basis(self.price_basis_note)
        return self


class Order(StrictModel):
    order_id: UUID
    original_order_key: str | None = Field(max_length=200)
    order_fixed_fee: Cost
    lines: list[ReceiptLot] = Field(min_length=1, max_length=8192)

    @model_validator(mode="after")
    def original_order(self):
        original_text(self.original_order_key, 200)
        return self


class PurchaseCandidatePlan(OriginalPayload):
    kind: Literal["purchase_candidate_plan"]
    timezone: str = Field(min_length=1, max_length=100)
    date_from: DateText
    date_to: DateText
    completeness: Literal["attested_complete", "incomplete", "unknown"]
    completeness_basis_note: Basis
    plan_fixed_fee: Cost
    orders: list[Order] = Field(max_length=8192)

    @model_validator(mode="after")
    def one_whole_plan(self):
        period(self)
        check_basis(self.completeness_basis_note)
        orders, lots = set(), set()
        for order in self.orders:
            if order.order_id in orders:
                raise ValueError("One original order cannot appear twice within the same plan")
            orders.add(order.order_id)
            for lot in order.lines:
                if lot.lot_id in lots:
                    raise ValueError("One receipt lot cannot appear twice within the same plan")
                lots.add(lot.lot_id)
                if lot.arrival_date.value is not None and not self.date_from <= lot.arrival_date.value <= self.date_to:
                    raise ValueError("Known arrivals outside this entire plan period cannot be silently omitted")
        if len(lots) > 8192:
            raise ValueError("Whole original plan receipt-lot cap exceeded")
        return self


Payload = Annotated[InventoryObservation | FutureQuantityScenario | PurchaseCandidatePlan, Field(discriminator="kind")]


class SourceCreate(StrictModel):
    item_kind: ItemKind
    item_id: Positive
    scope: Literal["hospital_inventory"]
    unit_definition_id: UUID | None
    expected_unit_content_hash: SHA256 | None
    expected_unit_governance_hash: SHA256 | None
    payload: Payload

    @model_validator(mode="after")
    def whole_unit_reference(self):
        absent = self.unit_definition_id is None
        if absent != (self.expected_unit_content_hash is None) or absent != (self.expected_unit_governance_hash is None):
            raise ValueError("Original unit requires its actual identity/content/governance together, or all unknown")
        values = self.payload.model_dump(mode="json")

        def quantities(value):
            if isinstance(value, dict):
                if set(value) == {"value", "absent_reason", "original_unit_text", "unit_review"}:
                    yield value
                for child in value.values():
                    yield from quantities(child)
            elif isinstance(value, list):
                for child in value:
                    yield from quantities(child)

        if absent and any(value["unit_review"] == "confirmed" for value in quantities(values)):
            raise ValueError("A confirmed inventory quantity requires the original governed unit reference")
        return self


# Exact existing governance inputs deliberately retain their code-point/UTF8
# semantics: review<=4000UTF8 bytes; revoke<=1000codepoints and4000UTF8 bytes.
SOURCE_REVIEW = SourceReview
SOURCE_REVOKE = SourceRevoke
