"""Strict private input only. Free text/identity never becomes native public text."""

from typing import Annotated, Literal

from pydantic import Field, model_validator

from app.ai.supply_contract import SHA256, UUID, DateText, Quantity, Review, StrictModel, Target, UtcText, day_bounds

Positive = Annotated[int, Field(strict=True, gt=0, le=2147483647)]
ItemKind = Literal["pharmaceutical", "consumable"]
Scope = Literal["hospital_inventory"]
Basis = Annotated[str, Field(min_length=20, max_length=4000)]
SOURCE_ROLES = frozenset({"admin", "director", "pharmacist", "super_admin"})


def check_basis(value):
    if not isinstance(value, str) or len("".join(value.split())) < 20 or len(value.encode()) > 4000:
        raise ValueError("At least20 nonwhite characters and at most4000 UTF8 bytes required")
    return value


class ProfessionalAttestation(StrictModel):
    status: Literal["confirmed", "unknown"]
    signer_user_id: Positive | None
    basis_note: Basis | None

    @model_validator(mode="after")
    def explicit(self):
        if self.status == "confirmed":
            if self.signer_user_id is None or self.basis_note is None:
                raise ValueError("Explicit actual pharmacist confirmation required")
            check_basis(self.basis_note)
        elif self.signer_user_id is not None or self.basis_note is not None:
            raise ValueError("Unknown is not a signature")
        return self


class UnitPayload(StrictModel):
    original_unit_text: str = Field(min_length=1, max_length=120)
    definition_basis_note: Basis
    professional_attestation: ProfessionalAttestation

    @model_validator(mode="after")
    def original_unit(self):
        if not self.original_unit_text.strip() or len(self.original_unit_text.encode()) > 480:
            raise ValueError("Original explicit unit must be nonblank and bounded; never infer it from drug strength")
        check_basis(self.definition_basis_note)
        return self


class UnitCreate(StrictModel):
    item_kind: ItemKind
    item_id: Positive
    scope: Scope
    payload: UnitPayload


class AuditReference(StrictModel):
    kind: Literal["pharmaceutical_ledger", "consumable_trace"]
    ledger_id: Positive | None
    trace_id: UUID | None

    @model_validator(mode="after")
    def one_actual_reference(self):
        if (self.kind == "pharmaceutical_ledger") != (self.ledger_id is not None) or (self.kind == "consumable_trace") != (self.trace_id is not None):
            raise ValueError("Only the exact selected original identifier is allowed")
        return self


class DailyPayload(StrictModel):
    kind: Literal["daily_quantity"]
    target: Target
    date: DateText
    timezone: str = Field(min_length=1, max_length=80)
    day_start_at: UtcText
    day_end_at: UtcText
    observed_at: UtcText
    quantity: Quantity
    original_unit_text: str | None = Field(max_length=120)
    unit_review: Review
    coverage: Literal["attested_complete", "incomplete", "unknown"]
    coverage_basis_note: Basis
    definition_basis_note: Basis
    method: Literal["direct_tally", "external_register"]
    external_record_key: str | None = Field(min_length=1, max_length=200)
    stock_constraint: Literal["none_observed", "partial", "full", "unknown"]
    stock_constraint_basis_note: Basis
    professional_attestation: ProfessionalAttestation
    audit_refs: list[AuditReference] = Field(max_length=64)

    @model_validator(mode="after")
    def whole_original(self):
        start, end = day_bounds(self.date, self.timezone)
        if (self.day_start_at, self.day_end_at) != (start, end) or not self.day_start_at < self.day_end_at <= self.observed_at:
            raise ValueError("Actual complete closed business day and separate original observation clock required")
        for value in (self.coverage_basis_note, self.definition_basis_note, self.stock_constraint_basis_note):
            check_basis(value)
        if self.method == "external_register":
            if self.external_record_key is None or not self.external_record_key.strip():
                raise ValueError("Explicit external record key required; not globally unique or auto-deduplicated")
        elif self.external_record_key is not None:
            raise ValueError("Direct tally does not silently become an external register")
        if self.original_unit_text is not None and (not self.original_unit_text.strip() or len(self.original_unit_text.encode()) > 480):
            raise ValueError("Unknown original unit stays null; no implicit conversion")
        if self.unit_review == "confirmed" and self.original_unit_text is None:
            raise ValueError("Confirmed original unit cannot be null")
        if self.professional_attestation.status == "unknown" and (self.unit_review == "confirmed" or self.coverage == "attested_complete"):
            raise ValueError("Technical recording/publication does not confirm unit or complete professional coverage")
        if len({(ref.kind, ref.ledger_id, ref.trace_id) for ref in self.audit_refs}) != len(self.audit_refs):
            raise ValueError("One reference cannot be repeated")
        return self


class SourceCreate(StrictModel):
    item_kind: ItemKind
    item_id: Positive
    scope: Scope
    unit_definition_id: UUID | None
    expected_unit_content_hash: SHA256 | None
    expected_unit_governance_hash: SHA256 | None
    payload: DailyPayload

    @model_validator(mode="after")
    def explicit_unit(self):
        absent = self.unit_definition_id is None
        if absent != (self.expected_unit_content_hash is None) or absent != (self.expected_unit_governance_hash is None) or absent and self.payload.unit_review == "confirmed":
            raise ValueError("Unit is an explicitly selected complete governed original or unknown")
        if any((ref.kind == "pharmaceutical_ledger") != (self.item_kind == "pharmaceutical") for ref in self.payload.audit_refs):
            raise ValueError("Audit original must belong to actual selected SKU kind")
        return self


class SourceReview(StrictModel):
    expected_revision: int = Field(strict=True, ge=1, le=3)
    expected_content_hash: SHA256
    decision: Literal["publish", "reject"]
    basis_note: Basis

    @model_validator(mode="after")
    def meaningful(self):
        check_basis(self.basis_note)
        return self


class SourceRevoke(StrictModel):
    expected_revision: int = Field(strict=True, ge=1, le=3)
    expected_content_hash: SHA256
    basis_note: str = Field(min_length=20, max_length=1000)

    @model_validator(mode="after")
    def meaningful(self):
        check_basis(self.basis_note)
        return self


class FrozenIdentity(StrictModel):
    record_kind: Literal["unit", "daily"]
    source_kind: Literal["unit_definition", "daily_quantity"]
    source_record_id: UUID
    unit_definition_id: UUID | None
    schema_version: Literal["supply_unit_private_v1", "supply_daily_private_v1"]
    item_kind: ItemKind
    item_id: Positive
    scope: Scope
    target: Target | None
    date: DateText | None
    day_start_at: UtcText | None
    day_end_at: UtcText | None
    observed_at: UtcText | None
    recorded_at: UtcText
    created_by: Positive


class Governance(StrictModel):
    status: Literal["draft", "published", "rejected", "revoked"]
    revision: int = Field(strict=True, ge=1, le=3)
    reviewed_by: Positive | None
    reviewed_at: UtcText | None
    review_basis_note: str = Field(max_length=4000)
    revoked_by: Positive | None
    revoked_at: UtcText | None
    revoke_reason: str = Field(max_length=1000)


class EligibilityBasis(StrictModel):
    schema_version: Literal["supply_current_eligibility_v1"]
    current_parent_state_hash: SHA256
    not_professional_or_operational_validation: Literal[True]


class SourceWrapper(FrozenIdentity, Governance):
    review_basis_note: str | None = Field(max_length=4000)
    revoke_reason: str | None = Field(max_length=1000)
    content_hash: SHA256
    source_id: str = Field(max_length=110)
    governance_hash: SHA256
    payload: UnitPayload | DailyPayload | None
    parent_binding: dict[str, object] | None
    professional_status: Literal["confirmed", "unknown"]
    signer_user_id: Positive | None
    signed_at: UtcText | None
    parent_current: bool
    eligible: bool
    exclusion_reasons: list[
        Literal["source_not_published", "original_sku_changed", "original_sku_unavailable", "professional_signature_changed", "unit_definition_changed", "audit_original_changed"]
    ] = Field(max_length=6)
    can_record: bool
    can_review: bool
    can_revoke: bool
    audit_only: bool
    eligibility_basis: EligibilityBasis


class CaptureSourceWrapper(SourceWrapper):
    capture_view: Literal[True]
