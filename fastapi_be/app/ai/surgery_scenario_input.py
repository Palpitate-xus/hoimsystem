"""Explicit private finite-domain declarations; original facts are loaded by SQL."""

from datetime import date, datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, model_validator

from app.ai.surgery_contract import (
    MAX_BYTES,
    MAX_CASES,
    MAX_EQUIPMENT,
    MAX_FACTS,
    MAX_PERSONS,
    MAX_ROOMS,
    MAX_STARTS,
    SHA256,
    UUID,
    Amount,
    CoverageStatus,
    FactKind,
    ObjectiveMode,
    Period,
    StartChoice,
    StrictModel,
    TechnicalKey,
    UtcText,
    canonical_json,
    day_bounds,
)


class Basis(StrictModel):
    basis_note: str = Field(min_length=20, max_length=4000)

    @model_validator(mode="after")
    def explicit_basis(self):
        if len("".join(self.basis_note.split())) < 20 or len(self.basis_note.encode()) > 4000:
            raise ValueError("Review requires twenty non-whitespace characters and at most 4000 UTF8 bytes")
        return self


class PeriodSelection(StrictModel):
    business_timezone: str = Field(min_length=1, max_length=100)
    date_from: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    date_to: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    as_of: UtcText

    @model_validator(mode="after")
    def complete_local_period(self):
        try:
            period_for(self)
        except OverflowError as exc:
            raise ValueError("Planning dates exceed representable calendar boundaries") from exc
        return self


def period_for(selection):
    """Construct and revalidate every actual local midnight, including DST."""
    first, last = date.fromisoformat(selection.date_from), date.fromisoformat(selection.date_to)
    count = (last - first).days + 1
    if not 1 <= count <= 31:
        raise ValueError("A continuous one-to-31-day planning period is required")
    try:
        local_as_of = datetime.fromisoformat(selection.as_of.replace("Z", "+00:00")).astimezone(ZoneInfo(selection.business_timezone)).date()
    except (ZoneInfoNotFoundError, OverflowError) as exc:
        raise ValueError("An actual available IANA timezone is required") from exc
    if first < local_as_of or last > local_as_of + timedelta(days=366):
        raise ValueError("Planning dates must be within the explicit cutoff day and the next 366 days")
    days = []
    for index in range(count):
        day = first + timedelta(days=index)
        start, end = day_bounds(day, selection.business_timezone)
        days.append({"business_date": day.isoformat(), "start_at": start, "end_at": end})
    return Period(business_timezone=selection.business_timezone, date_from=selection.date_from, date_to=selection.date_to, days=days)


class OriginalReference(StrictModel):
    source_record_id: UUID
    expected_content_hash: SHA256
    expected_governance_hash: SHA256


class MemberDeclaration(OriginalReference, Basis):
    source_kind: FactKind
    selection: Literal["confirmed", "excluded", "unknown"]


class DomainChoice(StrictModel):
    resource_id: UUID
    penalty: Amount
    duty_source: OriginalReference | None
    duty_binding_status: Literal["verified", "unknown", "not_applicable"] | None
    duty_basis_note: str | None = Field(min_length=20, max_length=4000)

    @model_validator(mode="after")
    def original_duty(self):
        if self.duty_source is not None and (self.duty_binding_status != "verified" or self.duty_basis_note is None):
            raise ValueError("A selected original duty requires explicit verified membership and basis")
        if self.duty_basis_note is not None:
            Basis(basis_note=self.duty_basis_note)
        if self.duty_binding_status is None and (self.duty_source is not None or self.duty_basis_note is not None):
            raise ValueError("Non-person choices have no person-duty fields")
        if self.duty_binding_status == "verified" and self.duty_source is None:
            raise ValueError("Verified duty membership requires its actual original")
        if self.duty_binding_status in {"unknown", "not_applicable"} and (self.duty_source is not None or self.duty_basis_note is None):
            raise ValueError("Missing duty remains an explicit declaration with original basis")
        return self


class DemandDomain(Basis):
    slot_id: TechnicalKey
    domain_status: CoverageStatus
    choices: list[DomainChoice] = Field(max_length=512)

    @model_validator(mode="after")
    def unique_resource_duty_choices(self):
        keys = [(item.resource_id, item.duty_source.source_record_id if item.duty_source else None) for item in self.choices]
        if len(keys) != len(set(keys)):
            raise ValueError("Duplicate concrete resource and duty choice")
        return self


class CaseDomain(Basis):
    application_id: UUID
    requirements: OriginalReference
    duration_estimate: OriginalReference
    start_domain_status: CoverageStatus
    starts: list[StartChoice] = Field(max_length=MAX_STARTS)
    room: DemandDomain
    roles: list[DemandDomain] = Field(max_length=16)
    equipment: list[DemandDomain] = Field(max_length=16)
    penalty_if_scheduled: Amount
    penalty_if_deferred: Amount | None

    @model_validator(mode="after")
    def finite_starts_and_distinct_demands(self):
        if [item.start_at for item in self.starts] != sorted({item.start_at for item in self.starts}):
            raise ValueError("Finite starts must be explicit, distinct and ordered")
        if any(item.duty_binding_status is not None for demand in [self.room, *self.equipment] for item in demand.choices):
            raise ValueError("Room and equipment choices cannot borrow person-duty membership")
        if any(item.duty_binding_status is None for demand in self.roles for item in demand.choices):
            raise ValueError("Person choices require explicit original duty membership or its absence")
        slots = [self.room.slot_id, *(item.slot_id for item in self.roles), *(item.slot_id for item in self.equipment)]
        if len(set(slots)) != len(slots) or "patient" in slots:
            raise ValueError("Distinct demands and independent patient presence are required")
        return self


class CoverageDeclaration(Basis):
    start_at: UtcText
    end_at: UtcText
    status: CoverageStatus

    @model_validator(mode="after")
    def positive_coverage(self):
        if self.start_at >= self.end_at:
            raise ValueError("Declared coverage requires a positive original interval")
        return self


class PolicyDeclaration(Basis):
    status: Literal["reviewed_policies", "attested_not_required", "unknown"]


class ResourceDeclaration(Basis):
    resource_id: UUID
    expected_resource_hash: SHA256
    expected_membership_id: UUID
    expected_membership_hash: SHA256
    expected_membership_governance_hash: SHA256
    availability_coverage: CoverageDeclaration
    all_locations_busy_coverage: CoverageDeclaration
    transition_class_status: CoverageStatus
    transition_policy_review: PolicyDeclaration
    work_policy_review: PolicyDeclaration | None
    all_locations_duty_coverage: CoverageDeclaration | None


class ProblemDeclaration(Basis):
    cases: CoverageDeclaration
    resources: CoverageDeclaration
    all_locations_busy: CoverageDeclaration
    policies: CoverageDeclaration
    finite_domains_status: CoverageStatus


class PersonPartitionDeclaration(Basis):
    status: Literal["verified_distinct_groups", "unknown"]
    resource_ids: list[UUID] = Field(max_length=MAX_PERSONS)

    @model_validator(mode="after")
    def explicit_person_cohort(self):
        if self.resource_ids != sorted(set(self.resource_ids)):
            raise ValueError("The whole reviewed person cohort must be explicit, distinct and ordered")
        return self


class ScenarioCreate(Basis):
    pool_id: UUID
    period: PeriodSelection
    expected_capture_digest: SHA256
    objective_mode: ObjectiveMode
    problem_coverage: ProblemDeclaration
    person_partition: PersonPartitionDeclaration
    members: list[MemberDeclaration] = Field(max_length=MAX_FACTS)
    cases: list[CaseDomain] = Field(max_length=MAX_CASES)
    resources: list[ResourceDeclaration] = Field(max_length=MAX_ROOMS + MAX_PERSONS + MAX_EQUIPMENT)

    @model_validator(mode="after")
    def whole_request(self):
        if len({item.application_id for item in self.cases}) != len(self.cases) or len({item.resource_id for item in self.resources}) != len(self.resources):
            raise ValueError("Repeated actual case or physical resource")
        members = {item.source_record_id: item for item in self.members}
        if len(members) != len(self.members):
            raise ValueError("Every relevant root requires exactly one complete member review")
        for case in self.cases:
            references = [
                (case.requirements, "case_requirements"),
                (case.duration_estimate, "case_duration_estimate"),
                *((choice.duty_source, "resource_availability_busy") for demand in case.roles for choice in demand.choices if choice.duty_source is not None),
            ]
            for reference, expected_kind in references:
                member = members.get(reference.source_record_id)
                if (
                    member is None
                    or member.source_kind != expected_kind
                    or member.selection != "confirmed"
                    or any(getattr(member, key) != getattr(reference, key) for key in OriginalReference.model_fields)
                ):
                    raise ValueError("Every selected case/duty original must match its explicit confirmed member review")
        if sum(len(item.starts) for item in self.cases) > MAX_STARTS:
            raise ValueError("Complete finite starts exceed capacity; no truncation")
        selected = {item.resource_id for item in self.resources}
        if not set(self.person_partition.resource_ids) <= selected:
            raise ValueError("Person identity review cannot refer to a different resource cohort")
        if any(choice.resource_id not in selected for case in self.cases for demand in [case.room, *case.roles, *case.equipment] for choice in demand.choices):
            raise ValueError("Every candidate must belong to the complete declared physical resource cohort")
        if any(start.start_at < self.period.as_of for case in self.cases for start in case.starts):
            raise ValueError("A declared planning start cannot precede its original availability cutoff")
        if len(canonical_json(self.model_dump()).encode()) > MAX_BYTES:
            raise ValueError("Complete private declaration exceeds 8MiB; no truncation")
        return self
