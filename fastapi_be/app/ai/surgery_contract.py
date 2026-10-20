"""Strict, database-free declared-stage surgery scheduling facts and proof types."""

import hashlib
import json
import re
import uuid
from datetime import UTC, date, datetime, time, timedelta
from typing import Annotated, Literal, get_args, get_origin
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

RULE_ID = "surgery_declared_stage_resources_v1"
MAX_BYTES = 8 * 1024 * 1024
MAX_CASES = 256
MAX_ROOMS = 64
MAX_PERSONS = 512
MAX_EQUIPMENT = 512
MAX_STARTS = 32768
MAX_CHOICES = 65536
MAX_SEGMENTS = 8192
MAX_BUSY = 32768
MAX_FACTS = 8192
MAX_DUTIES = 32768
MAX_POLICIES = 4096
MAX_OFFSET_US = 366 * 86400 * 1000000
OPERATION_LIMIT = 20000000
NODE_LIMIT = 20000
FRONTIER_LIMIT = 4096


def canonical_json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def hash_content(value):
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def identity(value):
    if not isinstance(value, str) or str(uuid.UUID(value)) != value:
        raise ValueError("Canonical lower-case UUID required")
    return value


def utc(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{6}Z", value):
        raise ValueError("Canonical explicit UTC6 clock required")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.year < 1000 or parsed.isoformat(timespec="microseconds").replace("+00:00", "Z") != value:
        raise ValueError("Invalid Gregorian UTC clock")
    return value


def day_text(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d\d-\d\d", value):
        raise ValueError("Canonical business date required")
    parsed = date.fromisoformat(value)
    if parsed.year < 1000 or parsed.isoformat() != value:
        raise ValueError("Invalid Gregorian business date")
    return value


def local_midnight(day, timezone):
    try:
        zone = ZoneInfo(timezone)
        naive = datetime.combine(day, time())
        choices = set()
        for fold in (0, 1):
            clock = naive.replace(tzinfo=zone, fold=fold).astimezone(UTC)
            if clock.astimezone(zone).replace(tzinfo=None) == naive:
                choices.add(clock)
        if len(choices) != 1:
            raise ValueError("Nonexistent or ambiguous business midnight")
        return utc(next(iter(choices)).isoformat(timespec="microseconds").replace("+00:00", "Z"))
    except (ZoneInfoNotFoundError, OverflowError) as exc:
        raise ValueError("Invalid timezone or out-of-range boundary") from exc


def day_bounds(day, timezone):
    try:
        day = date.fromisoformat(day) if isinstance(day, str) else day
        return local_midnight(day, timezone), local_midnight(day + timedelta(days=1), timezone)
    except OverflowError as exc:
        raise ValueError("Business boundary exceeds Gregorian range") from exc


def unique(items, label, key=lambda item: item):
    values = [key(item) for item in items]
    if len(set(values)) != len(values):
        raise ValueError(f"Repeated {label}")


SHA256 = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
UUID = Annotated[str, Field(pattern=r"^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$"), AfterValidator(identity)]
UtcText = Annotated[str, Field(pattern=r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{6}Z$"), AfterValidator(utc)]
DateText = Annotated[str, Field(pattern=r"^\d{4}-\d\d-\d\d$"), AfterValidator(day_text)]
NatText = Annotated[str, Field(pattern=r"^(0|[1-9][0-9]*)$", max_length=38)]
IntText = Annotated[str, Field(pattern=r"^(0|-?[1-9][0-9]*)$", max_length=39)]
TotalText = Annotated[str, Field(pattern=r"^(0|[1-9][0-9]*)$", max_length=128)]
TechnicalKey = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,47}$")]
Count = Annotated[int, Field(strict=True, ge=0, le=2147483647)]
RefIds = Annotated[list[UUID], Field(min_length=1, max_length=MAX_FACTS)]
State = Literal["satisfied", "violated", "unknown", "not_applicable"]
CoverageStatus = Literal["attested_complete", "incomplete", "unknown"]
ObjectiveMode = Literal["all_required_then_min_declared_cost", "max_optional_scheduled_then_min_declared_cost"]
FactKind = Literal[
    "case_requirements",
    "duration_observation",
    "case_duration_estimate",
    "operating_room_identity_capability",
    "person_identity_qualification",
    "resource_availability_busy",
    "resource_occupation_policy",
    "equipment_identity_capability",
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    @model_validator(mode="before")
    @classmethod
    def exact_literals(cls, value):
        if isinstance(value, dict):
            for name, field in cls.model_fields.items():
                if name in value and get_origin(field.annotation) is Literal:
                    choices = get_args(field.annotation)
                    if choices and all(type(item) is bool for item in choices) and type(value[name]) is not bool:
                        raise ValueError("Actual boolean required")
        return value


class Interval(StrictModel):
    start_at: UtcText
    end_at: UtcText

    @model_validator(mode="after")
    def increasing(self):
        if self.start_at >= self.end_at:
            raise ValueError("Interval must have positive duration")
        return self


class Coverage(Interval):
    status: CoverageStatus
    basis_hash: SHA256


class Review(StrictModel):
    status: CoverageStatus
    basis_hash: SHA256


class PolicyReview(StrictModel):
    status: Literal["reviewed_policies", "attested_not_required", "unknown"]
    basis_hash: SHA256


class Amount(StrictModel):
    value: NatText | None
    absent_reason: Literal["unknown", "not_recorded"] | None

    @model_validator(mode="after")
    def absence(self):
        if (self.value is None) != (self.absent_reason is not None):
            raise ValueError("Original zero and explicit missing amount differ")
        return self


class Offset(StrictModel):
    value: IntText | None
    absent_reason: Literal["unknown", "not_recorded"] | None

    @model_validator(mode="after")
    def absence(self):
        if (self.value is None) != (self.absent_reason is not None):
            raise ValueError("Offset absence must be explicit")
        if self.value is not None and abs(int(self.value)) > MAX_OFFSET_US:
            raise ValueError("Offset exceeds declared technical range")
        return self


class KnownTime(StrictModel):
    kind: Literal["known"]
    at: UtcText


class AbsentTime(StrictModel):
    kind: Literal["not_applicable", "unknown"]
    basis_hash: SHA256


UtcLimit = Annotated[KnownTime | AbsentTime, Field(discriminator="kind")]


class FactRef(StrictModel):
    fact_id: UUID
    kind: FactKind
    content_hash: SHA256
    governance_hash: SHA256
    recorded_at: UtcText
    published_at: UtcText | None
    status: Literal["draft", "published", "rejected", "revoked"]
    revision: Annotated[int, Field(strict=True, ge=1, le=2147483647)]
    review: Literal["confirmed", "excluded", "unknown"]
    review_basis_hash: SHA256

    @model_validator(mode="after")
    def original_clocks(self):
        if self.status == "published" and self.published_at is None:
            raise ValueError("Published fact requires its actual availability clock")
        if self.published_at is not None and self.published_at < self.recorded_at:
            raise ValueError("Publication cannot precede original recording")
        return self


class WorkAmount(StrictModel):
    counted_as_work: bool | None
    absent_reason: Literal["unknown", "not_applicable"] | None

    @model_validator(mode="after")
    def absence(self):
        if (self.counted_as_work is None) != (self.absent_reason is not None):
            raise ValueError("Work accounting requires original false/true or explicit absence")
        return self


class Break(Interval, WorkAmount):
    pass


class Accounting(WorkAmount):
    breaks: list[Break] = Field(max_length=256)
    breaks_complete: bool
    time_accounting_status: Literal["verified", "unknown"]

    @model_validator(mode="after")
    def completeness(self):
        previous = None
        for item in self.breaks:
            if previous is not None and item.start_at < previous:
                raise ValueError("Original breaks must be ordered and nonoverlapping")
            previous = item.end_at
        if self.time_accounting_status == "verified" and (self.counted_as_work is None or not self.breaks_complete or any(item.counted_as_work is None for item in self.breaks)):
            raise ValueError("Verified accounting requires explicit complete facts")
        return self


class Capability(StrictModel):
    ref_ids: RefIds
    capability_hashes: list[SHA256] = Field(max_length=256)
    status: Literal["verified", "not_verified", "unknown"]
    valid_from_at: UtcText
    valid_until: UtcLimit
    basis_hash: SHA256


class Availability(Interval):
    ref_ids: RefIds
    state: Literal["available", "unavailable", "unknown"]
    basis_hash: SHA256


class Resource(StrictModel):
    resource_id: UUID
    kind: Literal["room", "person", "equipment"]
    identity_hash: SHA256
    identity_status: Literal["verified", "unknown"]
    ref_ids: RefIds
    capability_facts: list[Capability] = Field(max_length=4096)
    availability: list[Availability] = Field(max_length=32768)
    availability_coverage: Coverage
    all_locations_busy_coverage: Coverage
    transition_class_coverage: Review
    transition_policy_review: PolicyReview
    work_policy_review: PolicyReview | None
    all_locations_duty_coverage: Coverage | None

    @model_validator(mode="after")
    def person_only(self):
        if self.kind == "person":
            if self.work_policy_review is None or self.all_locations_duty_coverage is None:
                raise ValueError("Person work scope must be explicit, including unknown")
        elif self.work_policy_review is not None or self.all_locations_duty_coverage is not None:
            raise ValueError("Non-person work scope must be null")
        return self


class ResourceTarget(StrictModel):
    kind: Literal["resource"]
    resource_id: UUID


class PatientTarget(StrictModel):
    kind: Literal["patient"]
    patient_conflict_token: UUID


BusyTarget = Annotated[ResourceTarget | PatientTarget, Field(discriminator="kind")]


class Busy(StrictModel):
    interval_id: UUID
    target: BusyTarget
    ref_ids: RefIds
    start_at: UtcText
    end_at: UtcText | None
    end_absent_reason: Literal["ongoing_unknown_end", "not_recorded"] | None
    verified_until_at: UtcText | None
    continuity_status: Literal["confirmed", "unknown"]
    busy_status: Literal["committed", "completed", "cancelled", "unknown"]
    transition_class_hash: SHA256 | None
    transition_class_absent_reason: Literal["unknown", "not_applicable"] | None
    accounting: Accounting
    basis_hash: SHA256

    @model_validator(mode="after")
    def original_fields(self):
        if (self.end_at is None) != (self.end_absent_reason is not None):
            raise ValueError("Busy end absence must remain explicit")
        if self.end_at is not None and self.end_at <= self.start_at:
            raise ValueError("Known busy interval must be positive")
        if self.verified_until_at is not None and (self.verified_until_at < self.start_at or self.end_at is not None and self.verified_until_at > self.end_at):
            raise ValueError("Verified busy prefix exceeds original interval")
        if (self.transition_class_hash is None) != (self.transition_class_absent_reason is not None):
            raise ValueError("Transition class absence must be explicit")
        return self


class Duty(Interval):
    duty_id: UUID
    person_id: UUID
    accounting: Accounting
    ref_ids: RefIds
    basis_hash: SHA256

    @model_validator(mode="after")
    def break_bounds(self):
        if any(item.start_at < self.start_at or item.end_at > self.end_at for item in self.accounting.breaks):
            raise ValueError("Duty break must remain within its original duty")
        return self


class TransitionPair(StrictModel):
    from_class_hash: SHA256
    to_class_hash: SHA256
    minimum_gap_us: Amount
    penalty: Amount
    basis_hash: SHA256


class TransitionPolicy(StrictModel):
    policy_id: UUID
    ref_ids: RefIds
    resource_ids: list[UUID] = Field(min_length=1, max_length=1088)
    effective_from_at: UtcText
    effective_until: UtcLimit
    pairs: list[TransitionPair] = Field(max_length=32768)
    pair_coverage: CoverageStatus
    basis_hash: SHA256

    @model_validator(mode="after")
    def unique_pairs(self):
        unique(self.pairs, "directed transition pair", lambda x: (x.from_class_hash, x.to_class_hash))
        unique(self.resource_ids, "transition resource")
        return self


class WorkLimit(StrictModel):
    value: NatText | None
    unit: Literal["us", "min"]
    absent_reason: Literal["unknown", "not_applicable"] | None

    @model_validator(mode="after")
    def absence(self):
        if (self.value is None) != (self.absent_reason is not None):
            raise ValueError("Work limit absence must remain explicit")
        return self


class WorkWindow(Interval):
    minimum_work: WorkLimit
    maximum_work: WorkLimit


class WorkPolicy(StrictModel):
    policy_id: UUID
    ref_ids: RefIds
    person_ids: list[UUID] = Field(min_length=1, max_length=MAX_PERSONS)
    effective_from_at: UtcText
    effective_until: UtcLimit
    max_single_presence: WorkLimit
    max_work_rolling_24h: WorkLimit
    max_work_rolling_7d: WorkLimit
    minimum_rest: WorkLimit
    fixed_windows: list[WorkWindow] = Field(max_length=64)
    policy_reference_hash: SHA256
    basis_hash: SHA256


class Segment(StrictModel):
    segment_id: TechnicalKey
    start_offset_us: Offset
    end_offset_us: Offset
    ref_ids: RefIds


class Occupation(StrictModel):
    segment_ids: list[TechnicalKey] = Field(min_length=1, max_length=MAX_SEGMENTS)
    occupation_mode: Literal["segments", "envelope"]
    transition_class_hash: SHA256 | None
    transition_class_absent_reason: Literal["unknown", "not_applicable"] | None
    accounting: WorkAmount
    basis_hash: SHA256

    @model_validator(mode="after")
    def original_class(self):
        unique(self.segment_ids, "occupation segment")
        if (self.transition_class_hash is None) != (self.transition_class_absent_reason is not None):
            raise ValueError("Occupation transition class absence must be explicit")
        return self


class DutyBinding(StrictModel):
    duty_id: UUID | None
    status: Literal["verified", "unknown"]
    basis_hash: SHA256

    @model_validator(mode="after")
    def confirmed_identity(self):
        if self.status == "verified" and self.duty_id is None:
            raise ValueError("Verified membership requires its real duty")
        return self


class Choice(StrictModel):
    resource_id: UUID
    penalty: Amount
    duty_binding: DutyBinding | None


class Demand(StrictModel):
    slot_id: TechnicalKey
    capability_hashes: list[SHA256] = Field(max_length=256)
    occupation: Occupation
    domain_status: CoverageStatus
    choices: list[Choice] = Field(max_length=MAX_CHOICES)
    basis_hash: SHA256

    @model_validator(mode="after")
    def unique_domain(self):
        unique(self.choices, "resource/duty domain choice", lambda x: (x.resource_id, x.duty_binding.duty_id if x.duty_binding else None))
        unique(self.capability_hashes, "required capability")
        return self


class RoleDemand(Demand):
    role_kind: Literal["surgeon", "anesthesia", "assistant", "scrub_nurse", "circulating_nurse", "other"]
    other_role_hash: SHA256 | None

    @model_validator(mode="after")
    def role_identity(self):
        if (self.role_kind == "other") != (self.other_role_hash is not None):
            raise ValueError("Other role requires its original identity hash")
        return self


class StartChoice(StrictModel):
    start_at: UtcText
    penalty: Amount


class Timing(StrictModel):
    method: Literal["reviewed_case_estimate", "unknown"]
    semantics: Literal["declared_upper_bounds", "declared_point_durations", "unknown"]
    segments: list[Segment] = Field(min_length=1, max_length=MAX_SEGMENTS)
    basis_hash: SHA256


class PatientPresence(StrictModel):
    segment_ids: list[TechnicalKey] = Field(min_length=1, max_length=MAX_SEGMENTS)
    occupation_mode: Literal["segments", "envelope"]
    basis_hash: SHA256


class OtherRequirements(StrictModel):
    status: Literal["attested_not_required", "all_required_modeled", "incomplete", "unknown"]
    basis_hash: SHA256


class SurgeryCase(StrictModel):
    case_id: UUID
    patient_conflict_token: UUID | None
    patient_identity_status: Literal["verified", "unknown"]
    procedure_group_hash: SHA256
    ref_ids: RefIds
    required: bool
    release: UtcLimit
    deadline: UtcLimit
    start_domain_status: CoverageStatus
    starts: list[StartChoice] = Field(max_length=MAX_STARTS)
    timing: Timing
    patient_presence: PatientPresence
    room: Demand
    roles: list[RoleDemand] = Field(max_length=16)
    equipment: list[Demand] = Field(max_length=16)
    penalty_if_scheduled: Amount
    penalty_if_deferred: Amount | None
    other_requirements: OtherRequirements

    @model_validator(mode="after")
    def complete_case(self):
        if self.required == (self.penalty_if_deferred is not None):
            raise ValueError("Only explicitly optional cases have a defer branch/cost")
        if self.patient_identity_status == "verified" and self.patient_conflict_token is None:
            raise ValueError("Verified patient identity needs its conflict token")
        unique(self.starts, "case start", lambda x: x.start_at)
        if [x.start_at for x in self.starts] != sorted(x.start_at for x in self.starts):
            raise ValueError("Finite starts must be canonical and ordered")
        unique(self.timing.segments, "case segment", lambda x: x.segment_id)
        unique([self.room, *self.roles, *self.equipment], "case demand", lambda x: x.slot_id)
        if any(x.slot_id == "patient" for x in [self.room, *self.roles, *self.equipment]):
            raise ValueError("Patient presence has its own reserved technical demand identity")
        ids = {x.segment_id for x in self.timing.segments}
        for demand in [self.room, *self.roles, *self.equipment]:
            if not set(demand.occupation.segment_ids) <= ids:
                raise ValueError("Occupation refers to a different case segment")
        if not set(self.patient_presence.segment_ids) <= ids:
            raise ValueError("Patient presence refers to a different case segment")
        unique(self.patient_presence.segment_ids, "patient segment")
        return self


class BusinessDay(Interval):
    business_date: DateText


class Period(StrictModel):
    business_timezone: Annotated[str, Field(min_length=1, max_length=100)]
    date_from: DateText
    date_to: DateText
    days: list[BusinessDay] = Field(min_length=1, max_length=31)

    @model_validator(mode="after")
    def actual_days(self):
        first, last = date.fromisoformat(self.date_from), date.fromisoformat(self.date_to)
        count = (last - first).days + 1
        if not 1 <= count <= 31 or len(self.days) != count:
            raise ValueError("Explicit continuous one-to-31 business days required")
        for index, item in enumerate(self.days):
            day = first + timedelta(days=index)
            if item.business_date != day.isoformat() or (item.start_at, item.end_at) != day_bounds(day, self.business_timezone):
                raise ValueError("Explicit day boundaries differ from actual IANA/Gregorian boundaries")
        return self


class RuleBinding(StrictModel):
    rule_id: Literal["surgery_declared_stage_resources_v1"]
    rule_version: Literal["1"]
    profile_token: UUID
    profile_content_hash: SHA256
    profile_governance_hash: SHA256
    recipe_hash: SHA256
    input_policy_hash: SHA256


class Collection(StrictModel):
    collection_digest: SHA256
    case_collection_digest: SHA256
    resource_collection_digest: SHA256
    busy_collection_digest: SHA256
    fact_collection_digest: SHA256
    manifest_digest: SHA256


class ProblemCoverage(StrictModel):
    cases: Coverage
    resources: Coverage
    all_locations_busy: Coverage
    policies: Coverage
    finite_domains_status: CoverageStatus
    basis_hash: SHA256


class PersonPartition(StrictModel):
    status: Literal["verified_distinct_groups", "unknown"]
    basis_hash: SHA256


class SurgerySource(StrictModel):
    schema_version: Literal["surgery_source_v1"]
    scenario_id: UUID
    source_id: Annotated[str, Field(max_length=125)]
    content_hash: SHA256
    governance_hash: SHA256
    scope_token: UUID
    original_scope_hash: SHA256
    period: Period
    as_of: UtcText
    captured_at: UtcText
    rule_binding: RuleBinding
    objective_mode: ObjectiveMode
    collection: Collection
    problem_coverage: ProblemCoverage
    person_partition: PersonPartition
    manifest: list[FactRef] = Field(max_length=MAX_FACTS)
    resources: list[Resource] = Field(max_length=MAX_ROOMS + MAX_PERSONS + MAX_EQUIPMENT)
    busy_intervals: list[Busy] = Field(max_length=MAX_BUSY)
    duties: list[Duty] = Field(max_length=MAX_DUTIES)
    cases: list[SurgeryCase] = Field(max_length=MAX_CASES)
    transition_policies: list[TransitionPolicy] = Field(max_length=MAX_POLICIES)
    work_policies: list[WorkPolicy] = Field(max_length=MAX_POLICIES)

    @model_validator(mode="after")
    def complete_source(self):
        if self.source_id != f"surgery_scenario:{self.scenario_id}:{self.content_hash[:12]}":
            raise ValueError("Scenario identity and original content hash differ")
        if self.captured_at < self.as_of:
            raise ValueError("Capture cannot precede the original availability cutoff")
        if self.rule_binding.recipe_hash != recipe_digest() or self.rule_binding.input_policy_hash != input_policy_digest():
            raise ValueError("Only the exact fixed recipe/input policy is supported")
        if len(canonical_json(self.model_dump()).encode()) > MAX_BYTES:
            raise ValueError("Complete public source exceeds byte capacity; no truncation")
        for name, field in (
            ("fact", self.manifest),
            ("resource", self.resources),
            ("busy", self.busy_intervals),
            ("duty", self.duties),
            ("case", self.cases),
            ("transition policy", self.transition_policies),
            ("work policy", self.work_policies),
        ):
            identity_field = {"fact": "fact_id", "resource": "resource_id", "busy": "interval_id", "duty": "duty_id", "case": "case_id", "transition policy": "policy_id", "work policy": "policy_id"}[
                name
            ]
            unique(field, name, lambda x: getattr(x, identity_field))
        if self.collection.manifest_digest != hash_content([item.model_dump() for item in self.manifest]):
            raise ValueError("Public manifest digest differs from its complete actual members")
        if any(item.recorded_at > self.as_of or item.published_at is not None and item.published_at > self.as_of for item in self.manifest):
            raise ValueError("Original fact availability is later than the source cutoff")
        resources = {item.resource_id: item for item in self.resources}
        duties = {item.duty_id: item for item in self.duties}
        for kind, limit in (("room", MAX_ROOMS), ("person", MAX_PERSONS), ("equipment", MAX_EQUIPMENT)):
            if sum(item.kind == kind for item in self.resources) > limit:
                raise ValueError("Resource domain exceeds its complete engineering capacity")
        totals = [
            sum(len(case.starts) for case in self.cases),
            sum(len(case.timing.segments) for case in self.cases),
            sum(len(demand.choices) for case in self.cases for demand in case.roles),
            sum(len(demand.choices) for case in self.cases for demand in case.equipment),
        ]
        if any(n > limit for n, limit in zip(totals, (MAX_STARTS, MAX_SEGMENTS, MAX_CHOICES, MAX_CHOICES), strict=True)):
            raise ValueError("Full factor domain exceeds capacity; members cannot be omitted")
        for duty in self.duties:
            if duty.person_id not in resources or resources[duty.person_id].kind != "person":
                raise ValueError("Duty refers to a different natural person")
        for busy in self.busy_intervals:
            if busy.target.kind == "resource" and busy.target.resource_id not in resources:
                raise ValueError("Busy interval refers outside this complete resource domain")
            if busy.busy_status == "completed" and (busy.end_at is None or busy.end_at > self.as_of):
                raise ValueError("A completed original busy interval needs an actual closed end no later than the availability cutoff")
        for policy in self.transition_policies:
            if not set(policy.resource_ids) <= resources.keys():
                raise ValueError("Transition policy resource is missing")
        for policy in self.work_policies:
            if any(x not in resources or resources[x].kind != "person" for x in policy.person_ids):
                raise ValueError("Work policy person is missing")
        for case in self.cases:
            for demand, kind in [(case.room, "room"), *((x, "person") for x in case.roles), *((x, "equipment") for x in case.equipment)]:
                for choice in demand.choices:
                    if choice.resource_id not in resources or resources[choice.resource_id].kind != kind:
                        raise ValueError("Choice resource kind or complete domain differs")
                    if kind == "person":
                        binding = choice.duty_binding
                        if binding is None:
                            raise ValueError("Person choice needs explicit duty membership, including unknown")
                        if binding.duty_id is not None and (binding.duty_id not in duties or duties[binding.duty_id].person_id != choice.resource_id):
                            raise ValueError("Selected duty belongs to a different person")
                    elif choice.duty_binding is not None:
                        raise ValueError("Non-person choice cannot select a duty")
        manifest = {item.fact_id for item in self.manifest}
        manifest_kinds = {item.fact_id: item.kind for item in self.manifest}
        usable = {item.fact_id for item in self.manifest if item.status == "published" and item.review == "confirmed"}

        def require_kind(refs, kinds):
            if not any(manifest_kinds.get(ref) in kinds for ref in refs):
                raise ValueError("Fact references cannot substitute a different clinical/operational source kind")

        for resource in self.resources:
            kinds = {"room": {"operating_room_identity_capability"}, "person": {"person_identity_qualification"}, "equipment": {"equipment_identity_capability"}}[resource.kind]
            require_kind(resource.ref_ids, kinds)
            for capability in resource.capability_facts:
                require_kind(capability.ref_ids, kinds)
            for availability in resource.availability:
                require_kind(availability.ref_ids, {"resource_availability_busy"})
        for busy in self.busy_intervals:
            require_kind(busy.ref_ids, {"resource_availability_busy"})
        for duty in self.duties:
            require_kind(duty.ref_ids, {"resource_availability_busy", "resource_occupation_policy"})
        for policy in [*self.transition_policies, *self.work_policies]:
            require_kind(policy.ref_ids, {"resource_occupation_policy"})
        for case in self.cases:
            require_kind(case.ref_ids, {"case_requirements"})
            for segment in case.timing.segments:
                require_kind(segment.ref_ids, {"case_duration_estimate", "resource_occupation_policy"})

        def walk(value):
            if isinstance(value, BaseModel):
                if hasattr(value, "ref_ids"):
                    refs = value.ref_ids
                    if refs != sorted(set(refs)) or not set(refs) <= manifest:
                        raise ValueError("Original references must be closed, unique and canonical")
                    if not set(refs) <= usable:
                        raise ValueError("Only published and confirmed originals may project usable public fact objects; other roots remain in the manifest")
                for field in value.__class__.model_fields:
                    walk(getattr(value, field))
            elif isinstance(value, list):
                for item in value:
                    walk(item)

        for group in (self.resources, self.busy_intervals, self.duties, self.cases, self.transition_policies, self.work_policies):
            walk(group)
        return self


class SourceBinding(StrictModel):
    scenario_id: UUID
    source_id: Annotated[str, Field(max_length=125)]
    content_hash: SHA256
    governance_hash: SHA256
    projection_hash: SHA256
    collection_digest: SHA256


class Objective(StrictModel):
    optional_scheduled_count: Count | None
    penalty_points: TotalText


class RoleAssignment(StrictModel):
    slot_id: TechnicalKey
    person_id: UUID
    duty_id: UUID | None


class EquipmentAssignment(StrictModel):
    slot_id: TechnicalKey
    equipment_id: UUID


class Assignment(StrictModel):
    case_id: UUID
    start_at: UtcText
    room_id: UUID
    roles: list[RoleAssignment] = Field(max_length=16)
    equipment: list[EquipmentAssignment] = Field(max_length=16)


class Occupancy(Interval):
    case_id: UUID
    demand_key: TechnicalKey
    resource_id: UUID | None
    patient_conflict_token: UUID | None
    source_segment_ids: list[TechnicalKey] = Field(max_length=MAX_SEGMENTS)
    ref_ids: RefIds


class WitnessBase(StrictModel):
    status: State
    case_ids: list[UUID] = Field(max_length=MAX_CASES)
    resource_ids: list[UUID] = Field(max_length=1088)
    demand_keys: list[TechnicalKey] = Field(max_length=64)
    ref_ids: list[UUID] = Field(max_length=MAX_FACTS)


class OverlapWitness(WitnessBase):
    code: Literal["resource_overlap", "patient_overlap", "identity_unknown"]
    intervals: list[Interval] = Field(max_length=2)
    patient_conflict_token: UUID | None


class IntervalWitness(WitnessBase):
    code: Literal["qualification", "availability", "time_bounds", "duration", "duty_membership", "accounting_conflict"]
    intervals: list[Interval] = Field(max_length=4)
    basis_hashes: list[SHA256] = Field(max_length=MAX_FACTS)


class LimitWitness(WitnessBase):
    code: Literal["transition", "work_window", "minimum_rest", "maximum_presence", "rolling_work"]
    intervals: list[Interval] = Field(max_length=4)
    actual_us: TotalText | None
    minimum_us: TotalText | None
    maximum_us: TotalText | None
    penalty_points: TotalText | None
    policy_ids: list[UUID] = Field(max_length=MAX_POLICIES)


class ScopeWitness(WitnessBase):
    code: Literal["coverage", "domain_closure", "missing_required_resource", "cost_unknown", "policy_unknown", "requirements_unknown", "sequence_relaxed"]
    reason: Literal[
        "incomplete",
        "unknown",
        "not_recorded",
        "empty_complete_domain",
        "unavailable_original",
        "partial_effectivity",
        "conflicting_originals",
        "unknown_adjacency",
        "missing_policy",
        "missing_pair",
        "identity_unverified",
        "unknown_timing",
        "accounting_unknown",
        "outside_coverage",
    ]
    basis_hashes: list[SHA256] = Field(max_length=MAX_FACTS)


Witness = Annotated[OverlapWitness | IntervalWitness | LimitWitness | ScopeWitness, Field(discriminator="code")]


class CheckCounts(StrictModel):
    satisfied: Count
    violated: Count
    unknown: Count
    not_applicable: Count


class CheckClassCount(StrictModel):
    check_class: Literal["scope", "duration", "time", "identity", "overlap", "qualification", "availability", "busy", "transition", "duty", "accounting", "work", "cost", "requirements"]
    counts: CheckCounts


class CheckSummary(StrictModel):
    counts: CheckCounts
    by_class: list[CheckClassCount] = Field(max_length=14)
    canonical_checks_digest: SHA256


class Candidate(StrictModel):
    status: Literal["feasible_under_declared_scope", "provisional_unknown"]
    assignments: list[Assignment] = Field(max_length=MAX_CASES)
    deferred_case_ids: list[UUID] = Field(max_length=MAX_CASES)
    scheduled_count: Count
    optional_scheduled_count: Count
    exact_penalty_points: TotalText | None
    penalty_lower_bound: TotalText
    duration_condition: Literal["declared_upper_bounds", "declared_point_durations", "mixed", "unknown"]
    occupancies: list[Occupancy] = Field(max_length=300000)
    check_summary: CheckSummary
    violations: list[Witness] = Field(max_length=32768)
    unknowns: list[Witness] = Field(max_length=32768)
    candidate_digest: SHA256


class SearchLimits(StrictModel):
    operation_limit: Count
    node_limit: Count
    frontier_limit: Count


class SearchProof(StrictModel):
    graph: Literal["definite", "optimistic"]
    termination: Literal["exhausted", "bound_closed", "operation_limit", "node_limit", "frontier_limit", "input_unknown"]
    expanded_nodes: Count
    primitive_operations: Count
    frontier_nodes: Count
    incumbent_objective: Objective | None
    optimistic_bound: Objective | None
    frontier_digest: SHA256
    incumbent_assignment_digest: SHA256 | None
    work_limits: SearchLimits


class CoreHashes(StrictModel):
    surgery_contract: SHA256
    surgery_model: SHA256
    surgery_config: SHA256
    surgery_server: SHA256


class EngineVersions(StrictModel):
    fastapi: Annotated[str, Field(max_length=32)]
    pydantic: Annotated[str, Field(max_length=32)]
    pydantic_settings: Annotated[str, Field(max_length=32)]
    uvicorn: Annotated[str, Field(max_length=32)]


class SurgeryRuntime(StrictModel):
    engine: Literal["stdlib_declared_stage_surgery_optimizer"]
    python_version: Annotated[str, Field(max_length=32)]
    engine_versions: EngineVersions
    core_sha256: CoreHashes
    recipe_digest: SHA256
    input_policy_digest: SHA256
    timezone_database_digest: SHA256
    clinical_validation: Literal["not_provided"]
    operational_validation: Literal["not_provided"]
    prompt_handling: Literal["provenance_only"]
    runtime_digest: SHA256
    model_version: Annotated[str, Field(pattern=r"^surgery:[a-f0-9]{64}$")]


class SurgeryAnalysis(StrictModel):
    schema_version: Literal["surgery_analysis_v1"]
    source_binding: SourceBinding
    instructions_digest: SHA256
    objective_mode: ObjectiveMode
    scope_status: Literal["closed_declared_problem", "incomplete_declared_problem"]
    solve_status: Literal["optimal_proven", "feasible_not_proven", "infeasible_proven", "feasibility_unknown", "input_unknown"]
    solution: Candidate | None
    feasible_incumbent_objective: Objective | None
    best_feasible_optional_count: Count | None
    optimistic_objective_bound: Objective | None
    optional_count_gap: Count | None
    penalty_gap_when_count_bound_closed: TotalText | None
    definite_search: SearchProof
    optimistic_search: SearchProof
    input_issues: list[Witness] = Field(max_length=32768)
    local_runtime: SurgeryRuntime
    forecast_or_clinical_guarantee: Literal["not_provided"]
    automatic_booking: Literal[False]


INPUT_POLICY = {
    "identity": "Problem-local canonical UUIDs; exact current private raw-to-capsule-to-public projection is verified by the application, never inferred from hashes alone.",
    "privacy": "No patient/admission/User/Doctor/equipment database keys, names, diagnoses, operation titles, notes or original question. Cross-scope busy capsules preserve operational facts and raw digests under separate raw-audit authorization.",
    "availability": "Original recorded_at <= published_at <= as_of; all known clocks remain UTC6. No historical backfill or guessed naive timezone. Explicit IANA day bounds; overflow/nonexistent/ambiguous midnight is rejected.",
    "missing": "Zero/false/null remain distinct. Unknown timing, capacity, qualification, identity, policy, busy, requirement or domain closure is never a normal/default fact.",
    "domains": "All reviewed finite starts and demand resource/duty choices are complete and factorized. Incomplete case/resource/start domains cannot prove global infeasibility or optimality. No hidden time grid, truncation or invented external resource.",
    "timing": "Only reviewed case estimates or unknown; no unimplemented statistical estimator. Signed exact microseconds, explicit zero segments, positive main-room occupancy; upper/point durations are declared conditions, not clinical guarantees.",
    "resources": "Patient presence is independent of room. One concrete asset per equipment quantity slot. Different role/equipment demands cannot union away quantity; same-demand stages union or envelope only as explicitly declared.",
    "person_qualification": "Each person role needs at least one explicitly reviewed authorization capability hash supported over every occupied interval by actual effective qualification facts. Empty role capability requirements mean unknown, never authorized by identity, role_kind, platform role or title alone.",
    "equipment_capability": "Equipment identity and effective capability require explicit equipment_identity_capability originals. Equipment names, database status, resource anchors and availability/busy facts cannot substitute capability or identity evidence. Unknown capability never becomes verified availability.",
    "work": "Reviewed explicit duty membership only. Duty baseline and selected counted work use interval union, never double-count. Confirmed non-work break vs counted surgery is a conflicting original, not overwritten. Rest applies between distinct explicit duties; full duty span defines maximum presence. All-location duty/work prefix/suffix coverage is required. Applicable policies are conjunctive; absent policy is unknown unless explicitly reviewed not required.",
    "sequence": "Extra transitions are separate from declared intrinsic stages. Missing directed pair is unknown, not zero. Partial adjacency gap/cost is not monotone. Optimistic unknown occupancy/status/identity that can change adjacency relaxes the affected resource's extra transition gaps and costs together; cost lower bound zero. Known hard overlaps and identities remain enforced.",
    "scope": "Only the declared closed case/resource/period/policy problem; no hospital-wide or real booking guarantee. Candidate output never creates a reservation or changes clinical state.",
}

RECIPE = {
    "rule_id": RULE_ID,
    "rule_version": "1",
    "schema_version": "12",
    "model_prefix": "surgery:",
    "objectives": {
        "all_required_then_min_declared_cost": "Required cases hard; minimize exact nonnegative declared total penalty, optional deferral remains a choice.",
        "max_optional_scheduled_then_min_declared_cost": "Required cases hard; maximize optional scheduled count then minimize declared penalty lexicographically.",
    },
    "intervals": "Exact UTC microseconds; [start,end); explicit zero has no occupancy; reversed original segment is a violated candidate fact, never swapped.",
    "accounting": "Exact integer microseconds; original minutes multiply by 60000000 without floating point. Rolling 24h and 7d extrema use all interval endpoint and shifted-endpoint breakpoints; fixed windows are separate rules.",
    "search": "Deterministic factorized best-bound binary sibling-range cursor; no Cartesian expansion or dominance. Complete parent remains until decision child and remaining range are both committed/closed. Budget interrupt retains the complete original parent bound.",
    "bounds": "Only irrevocable separable cost plus independent remaining minima; unknown nonnegative cost has lower bound zero. Optional upper bound counts all remaining possible optional cases. No partial sequence/minimum-work/rest-grouping pruning. Global optimistic bound includes all frontier and complete optimistic incumbent.",
    "graphs": "Definite complete leaves require all hard checks satisfied; optimistic relaxes unknown constraints while preserving a true supergraph. Incomplete underlying domains force input_unknown rather than global proof. Optimistic candidate never becomes executable solution.",
    "operations": {
        "limit_per_graph": OPERATION_LIMIT,
        "node_limit_per_graph": NODE_LIMIT,
        "frontier_limit_per_graph": FRONTIER_LIMIT,
        "grammar": "One source/factor/constraint scalar visit, option-bound contribution, interval overlap/endpoint contribution, qualification/availability/policy contribution or leaf check is one charged operation; repeated scans and every canonical check record's structural/scalar values charge per member. Hash/UTF8/parse have separate fixed byte/count limits. Interrupt during a leaf/bound leaves that node unclassified with its original admissible bound.",
    },
    "order": "Required cases then factor-domain cardinality then case UUID; schedule before defer; chronological starts, UUID resource/duty choices, slot keys; best bound then deeper decision before range then deterministic serial.",
    "caps": {
        "wire_bytes": MAX_BYTES,
        "canonical_check_stream_bytes_per_candidate": MAX_BYTES,
        "cases": MAX_CASES,
        "rooms": MAX_ROOMS,
        "persons": MAX_PERSONS,
        "equipment": MAX_EQUIPMENT,
        "starts": MAX_STARTS,
        "role_choices": MAX_CHOICES,
        "equipment_choices": MAX_CHOICES,
        "segments": MAX_SEGMENTS,
        "busy": MAX_BUSY,
        "facts": MAX_FACTS,
        "duties": MAX_DUTIES,
        "policies_each": MAX_POLICIES,
        "days": 31,
    },
    "verification": "All cohort persons' work rules including unselected fixed-window minima, all declared resource final timelines including fixed busy transition costs, selected constraints, search operations, frontier, objectives and fixed explanation are recomputed from the complete public source; digest-only validation is insufficient.",
    "clinical_validation": "not_provided",
    "operational_validation": "not_provided",
    "automatic_booking": False,
    "prompt_handling": "provenance_only",
    "input_policy": INPUT_POLICY,
}


def recipe_digest():
    return hash_content(RECIPE)


def input_policy_digest():
    return hash_content(INPUT_POLICY)
