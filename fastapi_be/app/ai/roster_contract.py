"""Database-free public facts and exact optimization proof contract for feature 63."""

import hashlib
import json
import re
import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

RULE_ID = "roster_declared_constraints_v1"
MAX_STAFF = 512
MAX_SESSIONS = 256
MAX_OPTIONS = 32768
MAX_BYTES = 8 * 1024 * 1024
MAX_INTERVALS = 32768
MAX_SAFE_INTEGER = 9007199254740991
MAX_POLICY_MINUTES = MAX_SAFE_INTEGER // 60000000
SHA256 = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
Count = Annotated[int, Field(strict=True, ge=0, le=MAX_SAFE_INTEGER)]
RawCount = Annotated[int, Field(strict=True, ge=0, le=2147483647)]
ObjectiveMode = Literal["meet_targets_min_penalty", "max_slots_then_min_penalty"]
Microseconds = Annotated[int, Field(strict=True, ge=0, le=MAX_SAFE_INTEGER)]
FactKind = Literal["qualification", "duty_interval", "availability", "work_rule_policy"]
CheckStatus = Literal["satisfied", "violated", "unknown", "not_applicable"]
PREFIXES = {"qualification": "roster_qualification", "duty_interval": "roster_duty", "availability": "roster_availability", "work_rule_policy": "roster_work_policy"}


def canonical_json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def hash_content(value):
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def utc(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{6}Z", value):
        raise ValueError("A canonical explicit UTC microsecond clock is required")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.year < 1000 or parsed.isoformat(timespec="microseconds").replace("+00:00", "Z") != value:
        raise ValueError("Invalid Gregorian UTC clock")
    return value


def identity(value):
    if not isinstance(value, str) or str(uuid.UUID(value)) != value:
        raise ValueError("A canonical UUID is required")
    return value


UtcText = Annotated[str, Field(pattern=r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{6}Z$")]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Interval(StrictModel):
    start_at: UtcText
    end_at: UtcText
    _clocks = field_validator("start_at", "end_at")(utc)

    @model_validator(mode="after")
    def increasing(self):
        if self.start_at >= self.end_at:
            raise ValueError("An interval must have positive duration")
        return self


class ConstraintValue(StrictModel):
    value: RawCount | None
    absent_reason: Literal["unknown", "not_applicable"] | None

    @model_validator(mode="after")
    def explicitly_missing(self):
        if (self.value is None) != (self.absent_reason is not None):
            raise ValueError("Known zero and explicit absence are distinct")
        return self


class MinuteConstraintValue(ConstraintValue):
    value: Annotated[int, Field(strict=True, ge=0, le=MAX_POLICY_MINUTES)] | None


class RosterFactRef(StrictModel):
    kind: FactKind
    source_record_id: str
    source_id: str = Field(min_length=1, max_length=140)
    content_hash: SHA256
    governance_hash: SHA256
    status: Literal["draft", "published", "rejected", "revoked"]
    revision: int = Field(strict=True, ge=1, le=2147483647)
    recorded_at: UtcText
    _id = field_validator("source_record_id")(identity)
    _clock = field_validator("recorded_at")(utc)

    @model_validator(mode="after")
    def complete_identity(self):
        if self.source_id != f"{PREFIXES[self.kind]}:{self.source_record_id}:{self.content_hash[:12]}":
            raise ValueError("Fact kind, identity and complete content digest differ")
        return self


class Coverage(Interval):
    status: Literal["attested_complete", "incomplete", "unknown"]
    basis_hash: SHA256


class RosterQualification(StrictModel):
    ref: RosterFactRef
    employment_status: Literal["active", "inactive", "unknown"]
    qualification_status: Literal["verified", "not_verified", "unknown"]
    authorized_job_hashes: list[SHA256] = Field(max_length=256)
    valid_from_at: UtcText
    valid_until_at: UtcText | None
    expiry_status: Literal["known", "unknown", "not_applicable"]
    basis_hash: SHA256
    _start = field_validator("valid_from_at")(utc)

    @field_validator("valid_until_at")
    @classmethod
    def end_clock(cls, value):
        return utc(value) if value is not None else value

    @model_validator(mode="after")
    def matching_kind(self):
        if self.ref.kind != "qualification" or (self.expiry_status == "known") != (self.valid_until_at is not None):
            raise ValueError("Qualification kind or explicit expiry differs")
        if self.valid_until_at is not None and self.valid_from_at >= self.valid_until_at:
            raise ValueError("Qualification validity must have positive duration")
        if len(set(self.authorized_job_hashes)) != len(self.authorized_job_hashes):
            raise ValueError("Repeated job identity")
        return self


class RosterBreak(Interval):
    counted_as_work: bool | None
    counted_as_work_absent_reason: Literal["unknown", "not_applicable"] | None

    @model_validator(mode="after")
    def explicit_accounting(self):
        if (self.counted_as_work is None) != (self.counted_as_work_absent_reason is not None):
            raise ValueError("Break accounting absence must be explicit")
        return self


def validate_breaks(parent, breaks):
    previous = None
    for item in breaks:
        if item.start_at < parent.start_at or item.end_at > parent.end_at or previous is not None and item.start_at < previous:
            raise ValueError("Breaks must be contained, ordered and nonoverlapping")
        previous = item.end_at


class DutyAccounting(Interval):
    breaks: list[RosterBreak] = Field(max_length=256)
    breaks_complete: bool
    time_accounting_status: Literal["verified", "unknown"]

    @model_validator(mode="after")
    def original_breaks(self):
        validate_breaks(self, self.breaks)
        if self.time_accounting_status == "verified" and (not self.breaks_complete or any(item.counted_as_work is None for item in self.breaks)):
            raise ValueError("Verified accounting requires explicit complete break facts")
        return self


class RosterDuty(DutyAccounting):
    ref: RosterFactRef
    commitment_status: Literal["committed", "completed", "cancelled", "unknown"]
    work_location: Literal["home_department", "other_department", "external", "unknown"]
    job_key_hash: SHA256 | None
    job_key_absent_reason: Literal["unknown", "not_applicable"] | None
    basis_hash: SHA256

    @model_validator(mode="after")
    def matching_kind(self):
        if self.ref.kind != "duty_interval":
            raise ValueError("Duty fact kind differs")
        if (self.job_key_hash is None) != (self.job_key_absent_reason is not None):
            raise ValueError("Original job-key absence must be explicit")
        if self.commitment_status == "completed" and self.end_at > self.ref.recorded_at:
            raise ValueError("Completed duty cannot end after its original recording")
        return self


class RosterAvailability(Interval):
    ref: RosterFactRef
    availability: Literal["available", "unavailable", "unknown"]
    basis_kind: Literal["staff_declaration", "approved_leave", "administrative_confirmation", "other"]
    basis_hash: SHA256

    @model_validator(mode="after")
    def matching_kind(self):
        if self.ref.kind != "availability":
            raise ValueError("Availability fact kind differs")
        return self


class RosterWorkWindow(Interval):
    minimum_work_minutes: MinuteConstraintValue
    maximum_work_minutes: MinuteConstraintValue

    @model_validator(mode="after")
    def consistent_window(self):
        span = datetime.fromisoformat(self.end_at.replace("Z", "+00:00")) - datetime.fromisoformat(self.start_at.replace("Z", "+00:00"))
        if span.days > 366 or span.days == 366 and (span.seconds or span.microseconds):
            raise ValueError("A fixed work window cannot exceed 366 days")
        low, high = self.minimum_work_minutes.value, self.maximum_work_minutes.value
        if low is not None and high is not None and low > high:
            raise ValueError("Known fixed-window lower bound exceeds upper bound")
        return self


class RosterWorkPolicy(StrictModel):
    ref: RosterFactRef
    applicable_staff_ids: list[str] = Field(min_length=1, max_length=MAX_STAFF)
    effective_from_at: UtcText
    effective_until_at: UtcText | None
    effective_until_absent_reason: Literal["unknown", "not_applicable"] | None
    max_single_duty_presence_minutes: MinuteConstraintValue
    max_work_minutes_rolling_24h: MinuteConstraintValue
    max_work_minutes_rolling_7d: MinuteConstraintValue
    minimum_rest_minutes: MinuteConstraintValue
    fixed_work_windows: list[RosterWorkWindow] = Field(max_length=64)
    basis_hash: SHA256
    policy_reference_hash: SHA256
    _start = field_validator("effective_from_at")(utc)

    @field_validator("effective_until_at")
    @classmethod
    def optional_end(cls, value):
        return utc(value) if value is not None else None

    @model_validator(mode="after")
    def matching_kind(self):
        if self.ref.kind != "work_rule_policy":
            raise ValueError("Work-policy fact kind differs")
        if len(set(self.applicable_staff_ids)) != len(self.applicable_staff_ids):
            raise ValueError("Repeated policy person identity")
        for staff_id in self.applicable_staff_ids:
            identity(staff_id)
        if (self.effective_until_at is None) != (self.effective_until_absent_reason is not None):
            raise ValueError("Policy end absence must remain explicit")
        if self.effective_until_at is not None and self.effective_from_at >= self.effective_until_at:
            raise ValueError("Policy validity must have positive duration")
        return self


class RosterStaff(StrictModel):
    staff_id: str
    identity_binding_hash: SHA256
    qualifications: list[RosterQualification] = Field(max_length=1024)
    duties: list[RosterDuty] = Field(max_length=4096)
    availability: list[RosterAvailability] = Field(max_length=4096)
    all_locations_duty_coverage: Coverage
    _id = field_validator("staff_id")(identity)


class RosterSession(Interval):
    session_id: str
    business_date: str = Field(pattern=r"^\d{4}-\d\d-\d\d$")
    required_job_hash: SHA256
    minimum_staff: Count
    maximum_staff: Count
    required_slots: ConstraintValue
    facility_slot_ceiling: ConstraintValue
    requirements_basis_hash: SHA256
    capacity_basis_hash: SHA256
    _id = field_validator("session_id")(identity)

    @model_validator(mode="after")
    def staffing_bounds(self):
        if self.minimum_staff > self.maximum_staff or self.maximum_staff > MAX_STAFF:
            raise ValueError("Session assigned-person bounds are inconsistent")
        return self


class RosterOption(StrictModel):
    option_id: str
    staff_id: str
    session_id: str
    cost_points: ConstraintValue
    slot_capacity: ConstraintValue
    breaks: list[RosterBreak] = Field(max_length=256)
    breaks_complete: bool
    time_accounting_status: Literal["verified", "unknown"]
    basis_hash: SHA256
    _ids = field_validator("option_id", "staff_id", "session_id")(identity)


class RosterSource(StrictModel):
    schema_version: Literal["roster_source_v1"]
    problem_id: str
    source_id: str
    content_hash: SHA256
    problem_governance_hash: SHA256
    scope_binding_hash: SHA256
    manifest_digest: SHA256
    rule_id: Literal["roster_declared_constraints_v1"]
    recipe_digest: SHA256
    input_policy_digest: SHA256
    objective_mode: ObjectiveMode
    planning_start_at: UtcText
    planning_end_at: UtcText
    business_timezone: str = Field(min_length=1, max_length=80)
    business_dates: list[str] = Field(min_length=1, max_length=31)
    as_of: UtcText
    captured_at: UtcText
    capture_mode: Literal["current_capture"]
    personnel_coverage: Literal["attested_complete", "incomplete", "unknown"]
    personnel_coverage_basis_hash: SHA256
    session_requirements_coverage: Literal["attested_complete", "incomplete", "unknown"]
    session_requirements_coverage_basis_hash: SHA256
    work_policies: list[RosterWorkPolicy] = Field(max_length=4096)
    staff: list[RosterStaff] = Field(max_length=MAX_STAFF)
    sessions: list[RosterSession] = Field(max_length=MAX_SESSIONS)
    options: list[RosterOption] = Field(max_length=MAX_OPTIONS)
    submitted_candidate: list[str] | None
    _id = field_validator("problem_id")(identity)
    _clocks = field_validator("planning_start_at", "planning_end_at", "as_of", "captured_at")(utc)

    @model_validator(mode="after")
    def complete_problem(self):
        from datetime import date, timedelta
        from zoneinfo import ZoneInfo

        if self.source_id != f"roster_problem:{self.problem_id}:{self.content_hash[:12]}":
            raise ValueError("Problem identity and complete private digest differ")
        if self.recipe_digest != recipe_digest() or self.input_policy_digest != input_policy_digest():
            raise ValueError("Problem is not bound to this exact local algorithm and input policy")
        if self.planning_start_at >= self.planning_end_at or self.as_of > self.captured_at:
            raise ValueError("Planning or original-availability clocks are inconsistent")
        dates = [date.fromisoformat(value) for value in self.business_dates]
        if any(str(value) != raw for value, raw in zip(dates, self.business_dates, strict=True)) or any(value != dates[0] + timedelta(days=index) for index, value in enumerate(dates)):
            raise ValueError("Business dates must be an explicit complete consecutive local-date interval")
        zone = ZoneInfo(self.business_timezone)
        first = datetime.fromisoformat(self.planning_start_at.replace("Z", "+00:00")).astimezone(zone)
        last = datetime.fromisoformat(self.planning_end_at.replace("Z", "+00:00")).astimezone(zone)
        if first.date() != dates[0] or last.date() != dates[-1] + timedelta(days=1) or first.time().isoformat() != "00:00:00" or last.time().isoformat() != "00:00:00":
            raise ValueError("Explicit UTC planning boundaries must match declared business-date midnights")
        staff = {item.staff_id: item for item in self.staff}
        sessions = {item.session_id: item for item in self.sessions}
        if (
            len(staff) != len(self.staff)
            or len(sessions) != len(self.sessions)
            or len({item.option_id for item in self.options}) != len(self.options)
            or len({(item.staff_id, item.session_id) for item in self.options}) != len(self.options)
        ):
            raise ValueError("Duplicate person, dated session, option or person/session option")
        if len(staff) * len(sessions) > MAX_OPTIONS or len(self.options) != len(staff) * len(sessions):
            raise ValueError("Every person/session pair requires one explicit original option; the complete Cartesian collection cannot be truncated")
        refs = [p.ref for p in self.work_policies]
        refs += [item.ref for person in self.staff for group in (person.qualifications, person.duties, person.availability) for item in group]
        if len(refs) > MAX_INTERVALS or len({item.source_id for item in refs}) != len(refs) or any(item.recorded_at > self.as_of for item in refs):
            raise ValueError("Fact collection is duplicated, oversized or unavailable at capture")
        if any(not set(item.applicable_staff_ids) <= set(staff) for item in self.work_policies):
            raise ValueError("Work policy references a person outside the complete problem scope")
        for session in self.sessions:
            start = datetime.fromisoformat(session.start_at.replace("Z", "+00:00")).astimezone(zone)
            if session.start_at < self.planning_start_at or session.end_at > self.planning_end_at or session.business_date not in self.business_dates or str(start.date()) != session.business_date:
                raise ValueError("Dated session differs from its original business day or UTC planning scope")
        for option in self.options:
            if option.staff_id not in staff or option.session_id not in sessions:
                raise ValueError("Option references an absent person or dated session")
            session = sessions[option.session_id]
            DutyAccounting(start_at=session.start_at, end_at=session.end_at, breaks=option.breaks, breaks_complete=option.breaks_complete, time_accounting_status=option.time_accounting_status)
        if self.submitted_candidate is not None:
            if len(self.submitted_candidate) > MAX_OPTIONS or len(set(self.submitted_candidate)) != len(self.submitted_candidate):
                raise ValueError("Candidate option identities must be unique and bounded")
            if not set(self.submitted_candidate) <= {item.option_id for item in self.options}:
                raise ValueError("Candidate references an absent original option")
        if len(canonical_json(self.model_dump()).encode()) > MAX_BYTES:
            raise ValueError("Complete public problem exceeds the UTF-8 limit")
        return self


class RosterBinding(StrictModel):
    problem_id: str
    source_id: str
    content_hash: SHA256
    problem_governance_hash: SHA256
    scope_binding_hash: SHA256
    manifest_digest: SHA256
    projection_hash: SHA256
    rule_id: Literal["roster_declared_constraints_v1"]
    recipe_digest: SHA256
    input_policy_digest: SHA256


class RosterCheck(StrictModel):
    kind: Literal[
        "personnel_coverage",
        "policy",
        "qualification",
        "availability",
        "accounting",
        "context_coverage",
        "presence_overlap",
        "single_duty_presence",
        "minimum_rest",
        "rolling_24h",
        "rolling_7d",
        "fixed_minimum_work",
        "fixed_maximum_work",
        "minimum_staff",
        "maximum_staff",
        "required_slots",
        "facility_slot_ceiling",
        "cost",
        "capacity",
    ]
    status: CheckStatus
    staff_id: str | None = None
    session_id: str | None = None
    source_ids: list[str] = Field(default_factory=list, max_length=MAX_INTERVALS)
    option_ids: list[str] = Field(default_factory=list, max_length=MAX_OPTIONS)
    witness_start_at: UtcText | None = None
    witness_end_at: UtcText | None = None
    actual_microseconds: Microseconds | None = None
    limit_microseconds: Microseconds | None = None
    actual_count: Count | None = None
    limit_count: Count | None = None
    evaluated_window_count: Count | None = None
    reason_codes: list[str] = Field(max_length=64)


class RosterSessionAllocation(StrictModel):
    session_id: str
    assigned_staff: Count
    staff_slot_capacity: Count | None
    required_slots: Count | None
    facility_slot_ceiling: Count | None
    planned_slots: Count | None
    capacity_headroom: Count | None


class RosterCandidateCheck(StrictModel):
    status: Literal["feasible_under_declared_scope", "violated", "unknown"]
    selected_option_ids: list[str] = Field(max_length=MAX_OPTIONS)
    cost_points: Count | None
    total_planned_slots: Count | None
    checks: list[RosterCheck] = Field(max_length=131072)
    session_allocations: list[RosterSessionAllocation] = Field(max_length=MAX_SESSIONS)


class RosterObjectiveValue(StrictModel):
    planned_slots: Count | None
    penalty_points: Count


class RosterSearchProof(StrictModel):
    graph: Literal["definite", "optimistic"]
    expanded_nodes: Count
    primitive_operations: Count
    frontier_nodes: Count
    termination: Literal["exhausted", "bound_closed", "node_limit", "operation_limit", "frontier_limit", "input_unknown"]
    incumbent_objective: RosterObjectiveValue | None
    optimistic_bound: RosterObjectiveValue | None
    frontier_digest: SHA256
    relaxations: list[
        Literal[
            "unknown_eligibility_allowed",
            "unknown_external_duty_omitted",
            "unknown_work_accounting_lower_bound",
            "unknown_numeric_constraint_omitted",
            "unknown_cost_nonnegative_domain_lower_bound",
            "unknown_capacity_integer_domain_upper_bound",
            "unknown_required_slots_nonnegative_domain_lower_bound",
        ]
    ] = Field(max_length=16)


class RosterRuntime(StrictModel):
    engine: Literal["stdlib_roster_branch_and_bound"]
    model_version: str = Field(pattern=r"^roster:[a-f0-9]{64}$")
    runtime_digest: SHA256
    python_version: str = Field(min_length=1, max_length=80)
    engine_versions: dict[str, str]
    core_sha256: dict[str, SHA256]
    recipe_digest: SHA256
    input_policy_digest: SHA256
    timezone_database_digest: SHA256
    clinical_validation: Literal["not_provided"]
    operational_validation: Literal["not_provided"]
    prompt_handling: Literal["provenance_only"]


class RosterAnalysis(StrictModel):
    schema_version: Literal["roster_analysis_v1"]
    source_binding: RosterBinding
    objective_mode: ObjectiveMode
    solve_status: Literal["optimal_proven", "feasible_not_proven", "infeasible_proven", "feasibility_unknown", "input_unknown"]
    optimality_proven: bool
    infeasibility_proven: bool
    optimistic_objective_bound: RosterObjectiveValue | None
    feasible_incumbent_objective: RosterObjectiveValue | None
    planned_slots_gap: Count | None
    penalty_gap_when_slot_bound_closed: Count | None
    solution: RosterCandidateCheck | None
    submitted_candidate_check: RosterCandidateCheck | None
    definite_search: RosterSearchProof
    optimistic_search: RosterSearchProof
    warnings: list[str] = Field(max_length=128)
    missing_data: list[str] = Field(max_length=128)
    instructions_digest: SHA256
    local_runtime: RosterRuntime


INPUT_POLICY = {
    "facts": "published_immutable_originals_current_capture_complete_manifest_and_explicit_review_no_name_title_or_old_time_inference",
    "privacy": "only_problem_local_staff_session_tokens_job_hashes_typed_facts_and_basis_hashes_no_names_contacts_leave_health_certificate_or_appointment_identity",
    "unknown": "never_zero_or_unrestricted_qualification_availability_preference_capacity_break_accounting_or_global_prefix_suffix_coverage",
    "staff_universe": "all_current_doctors_in_one_department_including_without_periodic_schedule_all_locations_work_context",
    "slots": "explicit_reviewed_dated_required_slots_facility_ceiling_and_net_person_session_capacity_not_shared_stock_forecast_records_or_booked_inventory",
    "source_limit": "reject_whole_utf8_oversize_or_member_cap_never_truncate",
}
RECIPE = {
    "rule_id": RULE_ID,
    "version": "declared_constraints_exact_integer_v1",
    "objectives": {
        "meet_targets_min_penalty": "minimize_total_explicit_reviewed_assignment_penalty_hard_staffing_and_required_slot_targets",
        "max_slots_then_min_penalty": "lexicographic_maximize_total_planned_slots_then_minimize_total_explicit_reviewed_penalty_no_free_weights",
    },
    "planning_dates": "one_to_31_explicit_consecutive_business_local_dates_UTC_midnights_validate_IANA_not_86400_times_days",
    "arithmetic": "integer_UTC_microseconds_no_float_minutes_times_60000000_policy_minutes_max150119987_other_raw_counts_max2147483647",
    "presence": "complete_duty_start_end_no_overlap_breaks_do_not_release_person_or_reset_rest",
    "work": "union_duty_work_segments_subtract_only_explicit_nonwork_breaks_complete_accounting_required_for_confirmed_feasibility",
    "rolling": "continuous_UTC24h_7d_maximum_at_domain_boundaries_work_endpoints_or_endpoints_minus_window_exact_prefix_integral",
    "rolling_start_domain": "closed_hull_planning_start_minus_window_through_planning_end_all_influencing_prefix_and_suffix",
    "rest": "adjacent_full_presence_intervals_including_all_locations_prefix_and_suffix_no_boundary_reset",
    "fixed_work_windows": "explicit_up_to64_up_to366day_windows_exact_work_intersection_no_plan_boundary_reset",
    "staff_counts": "number_assigned_to_whole_dated_session_not_instantaneous_service_coverage",
    "planned_slots": "meet_mode_required_slots_only_max_mode_min_of_facility_ceiling_and_sum_reviewed_net_staff_capacity_both_hard_required_targets_no_booking_or_stock_mutation",
    "policy": "all_published_applicable_whole_period_policies_conjoined_no_most_favorable_selection_no_policy_unknown_partial_validity_or_unknown_expiry_is_explicit_unknown_and_optimistic_relaxation_not_NA_not_complete_infeasibility_proof_explicit_local_constraints_not_universal_labor_law_compliance",
    "unknown_work": "unknown_commitment_or_accounting_has_zero_confirmed_work_lower_bound_and_original_presence_upper_bound_missing_inventory_fixed_window_upper_bound_is_full_window_not_zero",
    "graphs": "definite_confirmed_eligible_and_optimistic_unknown_relaxed_no_unknown_as_observed_fact",
    "proof": "admissible_frontier_lower_bound_and_known_feasible_upper_bound_optimal_only_bounds_close_infeasible_only_possible_tree_exhausted",
    "search": {
        "node_limit_per_graph": 32768,
        "operation_limit_per_graph": 2000000,
        "frontier_limit_per_graph": 4096,
        "deterministic_order": "canonical_source_identity_and_domain_cost_then_identity",
        "operations": "option_eligibility_evaluations_produced_constraint_checks_rolling_endpoint_evaluations_session_bound_evaluations_and_decision_expansions_not_Python_instruction_or_wallclock_count",
        "interruption": "commit_children_and_incumbent_only_after_whole_parent_expansion_within_budget_otherwise_retain_parent_frontier_bound_no_discarded_sibling",
        "bounds": "session_staff_cardinality_and_capacity_domain_upper_bound_cheapest_necessary_remaining_cardinality_cost_lower_bound_ignore_coupling_only_for_admissible_relaxation",
        "walltime": "not_a_numeric_search_stop_outer_timeout_returns_no_analysis",
    },
    "capacities": {"staff": MAX_STAFF, "sessions": MAX_SESSIONS, "options": MAX_OPTIONS, "facts": MAX_INTERVALS, "bytes": MAX_BYTES},
    "prompt_handling": "provenance_only",
    "input_policy": INPUT_POLICY,
}


def recipe_digest():
    return hash_content(RECIPE)


def input_policy_digest():
    return hash_content(INPUT_POLICY)
