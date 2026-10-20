"""Exact declared-scope workforce checks and bounded deterministic optimization.

All clocks, work integrals and limits use integers.  Optimistic graphs are
mathematical relaxations; they never become an observed roster or observed cost.
"""

import bisect
import hashlib
import heapq
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.ai.roster_contract import (
    MAX_BYTES,
    MAX_SAFE_INTEGER,
    RECIPE,
    RosterAnalysis,
    RosterBinding,
    RosterCandidateCheck,
    RosterCheck,
    RosterObjectiveValue,
    RosterSearchProof,
    RosterSessionAllocation,
    RosterSource,
    canonical_json,
    hash_content,
)

MINUTE = 60000000
DAY = 86400 * 1000000
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
RAW_DOMAIN_MAX = 2147483647


def clock_us(value):
    delta = datetime.fromisoformat(value.replace("Z", "+00:00")) - EPOCH
    return (delta.days * 86400 + delta.seconds) * 1000000 + delta.microseconds


def clock_text(value):
    result = EPOCH + timedelta(microseconds=value)
    if result.year < 1000:
        raise ValueError("Required dependency clock is outside the supported Gregorian domain")
    return result.isoformat(timespec="microseconds").replace("+00:00", "Z")


def merge_intervals(intervals):
    result = []
    for start, end in sorted(intervals):
        if start >= end:
            continue
        if result and start <= result[-1][1]:
            result[-1] = (result[-1][0], max(result[-1][1], end))
        else:
            result.append((start, end))
    return result


def subtract_intervals(intervals, removed):
    result = []
    cuts = merge_intervals(removed)
    for start, end in merge_intervals(intervals):
        cursor = start
        for low, high in cuts:
            if high <= cursor:
                continue
            if low >= end:
                break
            if low > cursor:
                result.append((cursor, low))
            cursor = max(cursor, high)
        if cursor < end:
            result.append((cursor, end))
    return result


class WorkIntegral:
    """A union measure; overlapping duties never double-count hours."""

    def __init__(self, intervals):
        self.intervals = merge_intervals(intervals)
        self.starts = [start for start, _ in self.intervals]
        self.ends = [end for _, end in self.intervals]
        self.prefix = [0]
        for start, end in self.intervals:
            self.prefix.append(self.prefix[-1] + end - start)

    def before(self, point):
        index = bisect.bisect_right(self.ends, point)
        value = self.prefix[index]
        if index < len(self.intervals) and self.starts[index] < point:
            value += point - self.starts[index]
        return value

    def between(self, start, end):
        return self.before(end) - self.before(start)

    def maximum_rolling(self, width, domain_start, domain_end):
        points = {domain_start, domain_end}
        for start, end in self.intervals:
            points.update(p for p in (start, end, start - width, end - width) if domain_start <= p <= domain_end)
        # Earliest witness is canonical when several windows attain the maximum.
        best, witness = -1, domain_start
        for point in sorted(points):
            value = self.between(point, point + width)
            if value > best:
                best, witness = value, point
        return best, witness, len(points)


def work_bounds(item, start=None, end=None):
    low = clock_us(start or item.start_at)
    high = clock_us(end or item.end_at)
    presence = [(low, high)]
    nonwork = [(clock_us(b.start_at), clock_us(b.end_at)) for b in item.breaks if b.counted_as_work is False]
    upper = subtract_intervals(presence, nonwork)
    if item.time_accounting_status == "verified":
        return upper, upper
    # Unknown completeness can hide further nonwork breaks.  No positive work
    # is asserted, while explicitly known nonwork is still removed above.
    return [], upper


def published(ref):
    return ref.status == "published"


def _check(kind, status, *, person=None, session=None, sources=(), options=(), reasons=(), **values):
    return RosterCheck(kind=kind, status=status, staff_id=person, session_id=session, source_ids=sorted(set(sources)), option_ids=sorted(set(options)), reason_codes=list(reasons), **values)


def _qualification(person, session, option):
    items = [q for q in person.qualifications if published(q.ref) and q.valid_from_at <= session.start_at and (q.valid_until_at is None or q.valid_until_at >= session.end_at)]
    positive = [q for q in items if q.employment_status == "active" and q.qualification_status == "verified" and session.required_job_hash in q.authorized_job_hashes and q.expiry_status != "unknown"]
    negative = [
        q for q in items if q.expiry_status != "unknown" and (q.employment_status == "inactive" or q.qualification_status == "verified" and session.required_job_hash not in q.authorized_job_hashes)
    ]
    # Any overlapping unresolved declaration prevents a positive declaration
    # silently winning over a contradictory or incomplete original.
    unresolved = any(
        not published(q.ref)
        or q.expiry_status == "unknown"
        or q.employment_status == "unknown"
        or q.qualification_status != "verified"
        or q.valid_from_at > session.start_at
        or q.valid_until_at is not None
        and q.valid_until_at < session.end_at
        for q in person.qualifications
        if q.valid_from_at < session.end_at and (q.valid_until_at is None or q.valid_until_at > session.start_at)
    )
    status = "unknown" if unresolved or positive and negative or not positive and not negative else "satisfied" if positive else "violated"
    return _check(
        "qualification",
        status,
        person=person.staff_id,
        session=session.session_id,
        sources=[q.ref.source_id for q in person.qualifications],
        options=[option.option_id],
        reasons=["whole_session_published_job_qualification" if status == "satisfied" else "qualification_missing_conflicting_unverified_or_not_authorized"],
    )


def _availability(person, session, option):
    start, end = clock_us(session.start_at), clock_us(session.end_at)
    items = [a for a in person.availability if a.start_at < session.end_at and a.end_at > session.start_at]
    points = sorted({start, end, *(max(start, clock_us(a.start_at)) for a in items), *(min(end, clock_us(a.end_at)) for a in items)})
    statuses = []
    for low, high in zip(points, points[1:]):
        states = {a.availability if published(a.ref) else "unknown" for a in items if clock_us(a.start_at) <= low and clock_us(a.end_at) >= high}
        statuses.append("satisfied" if states == {"available"} else "violated" if states == {"unavailable"} else "unknown")
    status = "violated" if "violated" in statuses else "unknown" if "unknown" in statuses else "satisfied"
    return _check(
        "availability",
        status,
        person=person.staff_id,
        session=session.session_id,
        sources=[a.ref.source_id for a in items],
        options=[option.option_id],
        reasons=["explicit_whole_session_availability" if status == "satisfied" else "unavailable_or_unreviewed_gap_or_conflict"],
    )


def _option_checks(person, session, option):
    return [
        _qualification(person, session, option),
        _availability(person, session, option),
        _check(
            "accounting",
            "satisfied" if option.time_accounting_status == "verified" else "unknown",
            person=person.staff_id,
            session=session.session_id,
            options=[option.option_id],
            reasons=["explicit_complete_break_accounting" if option.time_accounting_status == "verified" else "break_accounting_unknown"],
        ),
        _check(
            "cost",
            "satisfied" if option.cost_points.value is not None else "unknown",
            person=person.staff_id,
            session=session.session_id,
            options=[option.option_id],
            actual_count=option.cost_points.value,
            reasons=["reviewed_nonnegative_penalty" if option.cost_points.value is not None else "penalty_not_observed"],
        ),
        _check(
            "capacity",
            "satisfied" if option.slot_capacity.value is not None else "unknown",
            person=person.staff_id,
            session=session.session_id,
            options=[option.option_id],
            actual_count=option.slot_capacity.value,
            reasons=["reviewed_net_dated_capacity" if option.slot_capacity.value is not None else "net_capacity_unknown"],
        ),
    ]


def _duration_check(kind, lower, upper, limit, *, minimum=False, person, sources, options, start=None, end=None, windows=None):
    common = dict(
        person=person,
        sources=sources,
        options=options,
        witness_start_at=clock_text(start) if start is not None else None,
        witness_end_at=clock_text(end) if end is not None else None,
        evaluated_window_count=windows,
    )
    if limit.value is None:
        return _check(
            kind,
            "not_applicable" if limit.absent_reason == "not_applicable" else "unknown",
            reasons=["explicit_rule_not_applicable" if limit.absent_reason == "not_applicable" else "numeric_limit_unknown"],
            **common,
        )
    cap = limit.value * MINUTE
    if minimum:
        status = "violated" if upper < cap else "satisfied" if lower >= cap else "unknown"
    else:
        status = "violated" if lower > cap else "satisfied" if upper <= cap else "unknown"
    reasons = ["exact_work_lower_and_upper_bound" if lower != upper else "exact_integer_duration"]
    actual = lower
    if actual > MAX_SAFE_INTEGER:
        actual = None
        reasons.append("duration_exceeds_numeric_proof_field_use_exact_witness_clocks")
    return _check(kind, status, actual_microseconds=actual, limit_microseconds=cap, reasons=reasons, **common)


def _person_checks(source, person, selected, sessions, *, partial=False):
    """Known violations survive unknown accounting; partial omits lower targets."""
    checks, presence, lower_work, upper_work = [], [], [], []
    duty_sources = []
    option_ids = [o.option_id for o in selected]
    for duty in person.duties:
        duty_sources.append(duty.ref.source_id)
        if duty.commitment_status == "cancelled":
            continue
        if not published(duty.ref) or duty.commitment_status == "unknown":
            checks.append(_check("accounting", "unknown", person=person.staff_id, sources=[duty.ref.source_id], reasons=["external_duty_commitment_or_publication_unknown"]))
            # An uncertain duty cannot prove a violation or satisfy minimum work.
            _, high = work_bounds(duty)
            upper_work.extend(high)
            continue
        presence.append((clock_us(duty.start_at), clock_us(duty.end_at), duty.ref.source_id, None))
        low, high = work_bounds(duty)
        lower_work.extend(low)
        upper_work.extend(high)
        checks.append(
            _check(
                "accounting", "satisfied" if duty.time_accounting_status == "verified" else "unknown", person=person.staff_id, sources=[duty.ref.source_id], reasons=["original_duty_break_accounting"]
            )
        )
    for option in selected:
        session = sessions[option.session_id]
        presence.append((clock_us(session.start_at), clock_us(session.end_at), None, option.option_id))
        low, high = work_bounds(option, session.start_at, session.end_at)
        lower_work.extend(low)
        upper_work.extend(high)
    presence.sort()
    for left, right in zip(presence, presence[1:]):
        if right[0] < left[1]:
            checks.append(
                _check(
                    "presence_overlap",
                    "violated",
                    person=person.staff_id,
                    sources=[v for v in (left[2], right[2]) if v],
                    options=[v for v in (left[3], right[3]) if v],
                    witness_start_at=clock_text(right[0]),
                    witness_end_at=clock_text(min(left[1], right[1])),
                    reasons=["full_presence_overlap_break_does_not_release_staff"],
                )
            )
    if not any(c.kind == "presence_overlap" for c in checks):
        checks.append(_check("presence_overlap", "satisfied", person=person.staff_id, sources=duty_sources, options=option_ids, reasons=["all_known_full_presence_intervals_nonoverlapping"]))
    start, end = clock_us(source.planning_start_at), clock_us(source.planning_end_at)
    policies = [
        p
        for p in source.work_policies
        if person.staff_id in p.applicable_staff_ids and p.effective_from_at < source.planning_end_at and (p.effective_until_at is None or p.effective_until_at > source.planning_start_at)
    ]
    full_policies = []
    for policy in policies:
        full = (
            published(policy.ref)
            and policy.effective_from_at <= source.planning_start_at
            and (
                policy.effective_until_at is not None
                and policy.effective_until_at >= source.planning_end_at
                or policy.effective_until_at is None
                and policy.effective_until_absent_reason == "not_applicable"
            )
        )
        checks.append(
            _check(
                "policy",
                "satisfied" if full else "unknown",
                person=person.staff_id,
                sources=[policy.ref.source_id],
                reasons=["all_applicable_published_policies_conjoined" if full else "policy_partial_validity_or_unknown_governance_not_silently_omitted"],
            )
        )
        if full:
            full_policies.append(policy)
    if not full_policies:
        checks.append(_check("policy", "unknown", person=person.staff_id, reasons=["no_whole_period_published_applicable_policy"]))
    integral_low, integral_high = WorkIntegral(lower_work), WorkIntegral(upper_work)
    dependency_start, dependency_end = start, end
    for policy in full_policies:
        refs = duty_sources + [policy.ref.source_id]
        for low, high, duty_id, option_id in presence:
            # Original duties entirely beyond the planning horizon still matter
            # for fixed/rolling/rest, but the single-duty planning check is local.
            if high <= start or low >= end:
                continue
            checks.append(
                _duration_check(
                    "single_duty_presence",
                    high - low,
                    high - low,
                    policy.max_single_duty_presence_minutes,
                    person=person.staff_id,
                    sources=[v for v in (policy.ref.source_id, duty_id) if v],
                    options=[option_id] if option_id else [],
                    start=low,
                    end=high,
                )
            )
        rest = policy.minimum_rest_minutes
        if rest.value is not None:
            pad = rest.value * MINUTE
            dependency_start, dependency_end = min(dependency_start, start - pad), max(dependency_end, end + pad)
            relevant = [(a, b, sid, oid) for a, b, sid, oid in presence if b >= start - pad and a <= end + pad]
            for left, right in zip(relevant, relevant[1:]):
                gap = max(0, right[0] - left[1])
                checks.append(
                    _duration_check(
                        "minimum_rest",
                        gap,
                        gap,
                        rest,
                        minimum=True,
                        person=person.staff_id,
                        sources=[v for v in (policy.ref.source_id, left[2], right[2]) if v],
                        options=[v for v in (left[3], right[3]) if v],
                        start=left[1],
                        end=max(left[1], right[0]),
                    )
                )
        else:
            checks.append(_duration_check("minimum_rest", 0, 0, rest, minimum=True, person=person.staff_id, sources=[policy.ref.source_id], options=option_ids))
        for width, field, kind in ((DAY, policy.max_work_minutes_rolling_24h, "rolling_24h"), (7 * DAY, policy.max_work_minutes_rolling_7d, "rolling_7d")):
            if field.absent_reason == "not_applicable":
                checks.append(_duration_check(kind, 0, 0, field, person=person.staff_id, sources=[policy.ref.source_id], options=option_ids))
                continue
            dependency_start, dependency_end = min(dependency_start, start - width), max(dependency_end, end + width)
            low, witness, count = integral_low.maximum_rolling(width, start - width, end)
            high, _, _ = integral_high.maximum_rolling(width, start - width, end)
            checks.append(_duration_check(kind, low, high, field, person=person.staff_id, sources=refs, options=option_ids, start=witness, end=witness + width, windows=count))
        for window in policy.fixed_work_windows:
            low, high = clock_us(window.start_at), clock_us(window.end_at)
            dependency_start, dependency_end = min(dependency_start, low), max(dependency_end, high)
            measured_low, measured_high = integral_low.between(low, high), integral_high.between(low, high)
            coverage = person.all_locations_duty_coverage
            if coverage.status != "attested_complete" or coverage.start_at > window.start_at or coverage.end_at < window.end_at:
                # Missing duties could fill any part of this union-measure
                # window.  An incomplete inventory cannot prove a lower-target
                # failure merely because no original was returned.
                measured_high = high - low
            if not partial:
                checks.append(
                    _duration_check(
                        "fixed_minimum_work", measured_low, measured_high, window.minimum_work_minutes, minimum=True, person=person.staff_id, sources=refs, options=option_ids, start=low, end=high
                    )
                )
            checks.append(
                _duration_check("fixed_maximum_work", measured_low, measured_high, window.maximum_work_minutes, person=person.staff_id, sources=refs, options=option_ids, start=low, end=high)
            )
    coverage = person.all_locations_duty_coverage
    # Force explicit Gregorian range rejection rather than clipping dependencies.
    first, last = clock_text(dependency_start), clock_text(dependency_end)
    covered = coverage.status == "attested_complete" and coverage.start_at <= first and coverage.end_at >= last
    checks.append(
        _check(
            "context_coverage",
            "satisfied" if covered else "unknown",
            person=person.staff_id,
            sources=duty_sources,
            options=option_ids,
            witness_start_at=first,
            witness_end_at=last,
            reasons=["all_location_prefix_suffix_and_fixed_window_coverage" if covered else "external_work_context_incomplete_or_not_covering_dependency_envelope"],
        )
    )
    return checks


def check_candidate(source, selected_option_ids):
    if not isinstance(source, RosterSource):
        source = RosterSource.model_validate(source)
    selected_set = set(selected_option_ids)
    options = {o.option_id: o for o in source.options}
    if len(selected_set) != len(selected_option_ids) or not selected_set <= options.keys():
        raise ValueError("Candidate must identify distinct actual original options")
    selected = [options[key] for key in sorted(selected_set)]
    sessions = {s.session_id: s for s in source.sessions}
    staff = {p.staff_id: p for p in source.staff}
    checks = [
        _check(
            "personnel_coverage",
            "satisfied" if source.personnel_coverage == "attested_complete" else "unknown",
            reasons=["complete_declared_department_doctor_cohort" if source.personnel_coverage == "attested_complete" else "cohort_unknown_not_all_hospital_optimality"],
        ),
        _check(
            "personnel_coverage",
            "satisfied" if source.session_requirements_coverage == "attested_complete" else "unknown",
            reasons=["complete_reviewed_dated_session_collection" if source.session_requirements_coverage == "attested_complete" else "session_requirements_collection_incomplete"],
        ),
    ]
    for option in selected:
        checks.extend(_option_checks(staff[option.staff_id], sessions[option.session_id], option))
    for person in sorted(source.staff, key=lambda p: p.staff_id):
        checks.extend(_person_checks(source, person, [o for o in selected if o.staff_id == person.staff_id], sessions))
    allocations = []
    for session in sorted(source.sessions, key=lambda s: s.session_id):
        assigned = [o for o in selected if o.session_id == session.session_id]
        ids = [o.option_id for o in assigned]
        count = len(assigned)
        for kind, okay, limit in (("minimum_staff", count >= session.minimum_staff, session.minimum_staff), ("maximum_staff", count <= session.maximum_staff, session.maximum_staff)):
            checks.append(
                _check(
                    kind,
                    "satisfied" if okay else "violated",
                    session=session.session_id,
                    options=ids,
                    actual_count=count,
                    limit_count=limit,
                    reasons=["assigned_people_not_continuous_presence_staffing"],
                )
            )
        capacity = sum(o.slot_capacity.value for o in assigned) if all(o.slot_capacity.value is not None for o in assigned) else None
        required, ceiling = session.required_slots.value, session.facility_slot_ceiling.value
        if required is not None and ceiling is not None and ceiling < required:
            required_status = "violated"
        elif required is None or capacity is None or ceiling is None:
            required_status = "unknown"
        else:
            required_status = "satisfied" if min(capacity, ceiling) >= required else "violated"
        checks.append(
            _check(
                "required_slots", required_status, session=session.session_id, options=ids, actual_count=capacity, limit_count=required, reasons=["reviewed_dated_required_slots_not_forecast_or_stock"]
            )
        )
        checks.append(
            _check(
                "facility_slot_ceiling",
                "unknown" if ceiling is None else "satisfied",
                session=session.session_id,
                actual_count=ceiling,
                reasons=["explicit_facility_ceiling" if ceiling is not None else "facility_ceiling_unknown"],
            )
        )
        planned = None if required is None or capacity is None or ceiling is None else required if source.objective_mode == "meet_targets_min_penalty" else min(capacity, ceiling)
        allocations.append(
            RosterSessionAllocation(
                session_id=session.session_id,
                assigned_staff=count,
                staff_slot_capacity=capacity,
                required_slots=required,
                facility_slot_ceiling=ceiling,
                planned_slots=planned,
                capacity_headroom=None if capacity is None or ceiling is None or required is None else max(0, min(capacity, ceiling) - required),
            )
        )
    status = "violated" if any(c.status == "violated" for c in checks) else "unknown" if any(c.status == "unknown" for c in checks) else "feasible_under_declared_scope"
    return RosterCandidateCheck(
        status=status,
        selected_option_ids=sorted(selected_set),
        cost_points=sum(o.cost_points.value for o in selected) if all(o.cost_points.value is not None for o in selected) else None,
        total_planned_slots=sum(a.planned_slots for a in allocations) if all(a.planned_slots is not None for a in allocations) else None,
        checks=checks,
        session_allocations=allocations,
    )


def implementation_hashes():
    base = Path(__file__).parent
    return {name: hashlib.sha256((base / (name + ".py")).read_bytes()).hexdigest() for name in ("roster_contract", "roster_model", "roster_config", "roster_server")}


# These are defined work operations, not wall-clock or Python-instruction counts:
# option eligibility evaluations, produced constraint checks, rolling endpoint
# evaluations, bound session evaluations and expanded decision nodes.
class _BudgetStopError(Exception):
    pass


class _Budget:
    def __init__(self, maximum):
        self.maximum = maximum
        self.operations = 0

    def charge(self, amount=1):
        if self.operations + amount > self.maximum:
            raise _BudgetStopError
        self.operations += amount


@dataclass(frozen=True)
class _Node:
    index: int
    selected_mask: int
    counts: tuple
    capacities: tuple
    cost: int


@dataclass
class _SearchResult:
    proof: RosterSearchProof
    solution: RosterCandidateCheck | None


def _objective_key(source, value):
    return (value.penalty_points,) if source.objective_mode == "meet_targets_min_penalty" else (-value.planned_slots, value.penalty_points)


def _objective_from_key(source, key):
    if key is None:
        return None
    return RosterObjectiveValue(planned_slots=None if source.objective_mode == "meet_targets_min_penalty" else -key[0], penalty_points=key[-1])


def _candidate_objective(source, candidate):
    if candidate.status != "feasible_under_declared_scope" or candidate.cost_points is None or candidate.total_planned_slots is None:
        return None
    return RosterObjectiveValue(planned_slots=None if source.objective_mode == "meet_targets_min_penalty" else candidate.total_planned_slots, penalty_points=candidate.cost_points)


def _relaxations(source, base_checks, option_checks):
    result = set()
    unknown_checks = [c for c in base_checks if c.status == "unknown"] + [c for group in option_checks.values() for c in group if c.status == "unknown"]
    if any(c.kind in ("qualification", "availability") for c in unknown_checks):
        result.add("unknown_eligibility_allowed")
    if any(c.kind in ("context_coverage", "accounting") for c in unknown_checks):
        result.add("unknown_external_duty_omitted")
        result.add("unknown_work_accounting_lower_bound")
    if any(c.kind in ("policy", "single_duty_presence", "minimum_rest", "rolling_24h", "rolling_7d", "fixed_minimum_work", "fixed_maximum_work") for c in unknown_checks):
        result.add("unknown_numeric_constraint_omitted")
    if any(o.cost_points.value is None for o in source.options):
        result.add("unknown_cost_nonnegative_domain_lower_bound")
    if any(o.slot_capacity.value is None for o in source.options) or any(s.facility_slot_ceiling.value is None for s in source.sessions):
        result.add("unknown_capacity_integer_domain_upper_bound")
    if any(s.required_slots.value is None for s in source.sessions):
        result.add("unknown_required_slots_nonnegative_domain_lower_bound")
    return sorted(result)


def _search(source, graph):
    limits = RECIPE["search"]
    budget = _Budget(limits["operation_limit_per_graph"])
    sessions = sorted(source.sessions, key=lambda s: s.session_id)
    session_map = {s.session_id: s for s in sessions}
    staff = {p.staff_id: p for p in source.staff}
    base_checks = [c for p in source.staff for c in _person_checks(source, p, [], session_map, partial=True)]
    eligibility = {o.option_id: _option_checks(staff[o.staff_id], session_map[o.session_id], o) for o in source.options}
    relaxation = _relaxations(source, base_checks, eligibility) if graph == "optimistic" else []
    initial_unknown = source.personnel_coverage != "attested_complete" or source.session_requirements_coverage != "attested_complete"
    if graph == "definite":
        initial_unknown |= any(c.status == "unknown" for c in base_checks)
        initial_unknown |= any(s.required_slots.value is None or s.facility_slot_ceiling.value is None for s in sessions)
    if initial_unknown:
        return _SearchResult(
            RosterSearchProof(
                graph=graph,
                expanded_nodes=0,
                primitive_operations=0,
                frontier_nodes=0,
                termination="input_unknown",
                incumbent_objective=None,
                optimistic_bound=None,
                frontier_digest=hash_content([graph, "input_unknown"]),
                relaxations=relaxation,
            ),
            None,
        )
    # Every original pair exists in Source.  Only a checked hard exclusion may
    # remove it from this graph; absence in an input collection never excludes.
    allowed = [o for o in source.options if not any(c.status == "violated" or graph == "definite" and c.status == "unknown" for c in eligibility[o.option_id])]
    allowed.sort(key=lambda o: (o.session_id, o.cost_points.value if o.cost_points.value is not None else 0, o.staff_id, o.option_id))
    session_index = {s.session_id: i for i, s in enumerate(sessions)}
    option_session = [session_index[o.session_id] for o in allowed]
    option_capacity = [o.slot_capacity.value if o.slot_capacity.value is not None else RAW_DOMAIN_MAX for o in allowed]
    option_cost = [o.cost_points.value if o.cost_points.value is not None else 0 for o in allowed]
    ranges, capacity_suffix, max_capacity_suffix, cost_prefix = [], [], [], []
    cursor = 0
    for index, _session in enumerate(sessions):
        start = cursor
        while cursor < len(allowed) and option_session[cursor] == index:
            cursor += 1
        ranges.append((start, cursor))
        caps = option_capacity[start:cursor]
        suffix, maximum = [0] * (len(caps) + 1), [0] * (len(caps) + 1)
        for position in range(len(caps) - 1, -1, -1):
            suffix[position] = suffix[position + 1] + caps[position]
            maximum[position] = max(maximum[position + 1], caps[position])
        capacity_suffix.append(suffix)
        max_capacity_suffix.append(maximum)
        prefix = [0]
        for value in option_cost[start:cursor]:
            prefix.append(prefix[-1] + value)
        cost_prefix.append(prefix)

    def normalize(node):
        index = node.index
        while index < len(allowed):
            si = option_session[index]
            if node.counts[si] < sessions[si].maximum_staff:
                break
            index = ranges[si][1]
        return replace(node, index=index)

    def bound(node):
        penalty, total_slots = node.cost, 0
        for si, session in enumerate(sessions):
            budget.charge()
            first, last = ranges[si]
            position = min(last, max(first, node.index)) - first
            remaining = last - first - position
            room = session.maximum_staff - node.counts[si]
            if room < 0 or node.counts[si] + min(room, remaining) < session.minimum_staff:
                return None
            maximum = max_capacity_suffix[si][position]
            extra_upper = min(capacity_suffix[si][position], min(room, remaining) * maximum)
            cap_upper = node.capacities[si] + extra_upper
            ceiling = session.facility_slot_ceiling.value if session.facility_slot_ceiling.value is not None else RAW_DOMAIN_MAX
            required = session.required_slots.value if session.required_slots.value is not None else 0
            if min(cap_upper, ceiling) < required:
                return None
            needed = max(0, session.minimum_staff - node.counts[si])
            shortfall = max(0, required - node.capacities[si])
            if shortfall:
                if not maximum:
                    return None
                needed = max(needed, (shortfall + maximum - 1) // maximum)
            if needed > min(room, remaining):
                return None
            # Canonical session options are sorted by nonnegative domain cost;
            # cheapest required cardinality ignores coupling, hence admissible.
            penalty += cost_prefix[si][position + needed] - cost_prefix[si][position]
            total_slots += min(cap_upper, ceiling)
        return (penalty,) if source.objective_mode == "meet_targets_min_penalty" else (-total_slots, penalty)

    def leaf_key(node):
        if source.objective_mode == "meet_targets_min_penalty":
            return (node.cost,)
        slots = sum(min(node.capacities[si], s.facility_slot_ceiling.value if s.facility_slot_ceiling.value is not None else RAW_DOMAIN_MAX) for si, s in enumerate(sessions))
        return (-slots, node.cost)

    def selected_options(node):
        bits, selected = node.selected_mask, []
        while bits:
            lowest = bits & -bits
            selected.append(allowed[lowest.bit_length() - 1])
            bits -= lowest
        return selected

    frontier, serial, expanded = [], 0, 0
    incumbent_key, real_key, solution = None, None, None
    termination = "exhausted"
    root = _Node(0, 0, (0,) * len(sessions), (0,) * len(sessions), 0)
    base_violated = any(c.status == "violated" for c in base_checks)
    try:
        budget.charge(len(source.options) + len(base_checks) + sum(len(c) for c in eligibility.values()))
        initial_bound = None if base_violated else bound(root)
    except _BudgetStopError:
        # Preprocessing cannot consume the root or silently certify anything.
        generic = (
            (0,) if source.objective_mode == "meet_targets_min_penalty" else (-sum(s.facility_slot_ceiling.value if s.facility_slot_ceiling.value is not None else RAW_DOMAIN_MAX for s in sessions), 0)
        )
        proof = RosterSearchProof(
            graph=graph,
            expanded_nodes=0,
            primitive_operations=budget.operations,
            frontier_nodes=1,
            termination="operation_limit",
            incumbent_objective=None,
            optimistic_bound=_objective_from_key(source, generic),
            frontier_digest=hash_content(["unexpanded_root", generic]),
            relaxations=relaxation,
        )
        return _SearchResult(proof, None)
    if initial_bound is not None:
        heapq.heappush(frontier, (initial_bound, 0, serial, root))
    while frontier:
        if incumbent_key is not None and frontier[0][0] >= incumbent_key:
            termination = "bound_closed"
            break
        if expanded >= limits["node_limit_per_graph"]:
            termination = "node_limit"
            break
        parent_bound, _, _, original = frontier[0]
        node = normalize(original)
        children = []
        new_incumbent, new_real, new_solution = incumbent_key, real_key, solution
        try:
            budget.charge()
            if node.index == len(allowed):
                candidate = check_candidate(source, [o.option_id for o in selected_options(node)])
                budget.charge(len(candidate.checks) + sum(c.evaluated_window_count or 0 for c in candidate.checks))
                possible = candidate.status != "violated" if graph == "optimistic" else candidate.status == "feasible_under_declared_scope"
                if possible:
                    key = leaf_key(node)
                    if new_incumbent is None or key < new_incumbent:
                        new_incumbent = key
                    objective = _candidate_objective(source, candidate)
                    if objective is not None:
                        key_actual = _objective_key(source, objective)
                        if new_real is None or key_actual < new_real:
                            new_real, new_solution = key_actual, candidate
            else:
                index = node.index
                option = allowed[index]
                si = option_session[index]
                # Exclusion and inclusion are independent children.  Neither is
                # committed until both have been bounded within the operation
                # budget; an interrupted expansion retains its whole parent.
                excluded = normalize(replace(node, index=index + 1))
                excluded_bound = bound(excluded)
                if excluded_bound is not None and (incumbent_key is None or excluded_bound < incumbent_key):
                    children.append((excluded_bound, excluded))
                existing = [o for o in selected_options(node) if o.staff_id == option.staff_id]
                partial_checks = _person_checks(source, staff[option.staff_id], existing + [option], session_map, partial=True)
                budget.charge(len(partial_checks) + sum(c.evaluated_window_count or 0 for c in partial_checks))
                if not any(c.status == "violated" or graph == "definite" and c.status == "unknown" for c in partial_checks):
                    counts, capacities = list(node.counts), list(node.capacities)
                    counts[si] += 1
                    capacities[si] += option_capacity[index]
                    included = normalize(_Node(index + 1, node.selected_mask | (1 << index), tuple(counts), tuple(capacities), node.cost + option_cost[index]))
                    included_bound = bound(included)
                    if included_bound is not None and (incumbent_key is None or included_bound < incumbent_key):
                        children.append((included_bound, included))
        except _BudgetStopError:
            termination = "operation_limit"
            break
        if len(frontier) - 1 + len(children) > limits["frontier_limit_per_graph"]:
            termination = "frontier_limit"
            break
        heapq.heappop(frontier)
        expanded += 1
        incumbent_key, real_key, solution = new_incumbent, new_real, new_solution
        for child_bound, child in children:
            serial += 1
            heapq.heappush(frontier, (child_bound, -child.index, serial, child))
    candidate_bounds = ([incumbent_key] if incumbent_key is not None else []) + ([frontier[0][0]] if frontier else [])
    optimum_bound = min(candidate_bounds) if candidate_bounds else None
    frontier_facts = [
        {"bound": item[0], "index": item[3].index, "mask": str(item[3].selected_mask), "counts": item[3].counts, "capacities": item[3].capacities, "cost": item[3].cost} for item in sorted(frontier)
    ]
    proof = RosterSearchProof(
        graph=graph,
        expanded_nodes=expanded,
        primitive_operations=budget.operations,
        frontier_nodes=len(frontier),
        termination=termination,
        incumbent_objective=_objective_from_key(source, incumbent_key),
        optimistic_bound=_objective_from_key(source, optimum_bound),
        frontier_digest=hash_content(frontier_facts),
        relaxations=relaxation,
    )
    return _SearchResult(proof, solution)


def compute_roster(source, instructions_digest, runtime):
    if not isinstance(source, RosterSource):
        source = RosterSource.model_validate(source)
    definite, optimistic = _search(source, "definite"), _search(source, "optimistic")
    candidates = [r.solution for r in (definite, optimistic) if r.solution is not None]
    solution = min(candidates, key=lambda c: _objective_key(source, _candidate_objective(source, c))) if candidates else None
    incumbent = _candidate_objective(source, solution) if solution else None
    bound = optimistic.proof.optimistic_bound
    infeasible = optimistic.proof.termination == "exhausted" and optimistic.proof.incumbent_objective is None
    optimal = incumbent is not None and bound is not None and _objective_key(source, incumbent) == _objective_key(source, bound)
    if incumbent is not None and bound is not None and _objective_key(source, bound) > _objective_key(source, incumbent):
        raise ValueError("Optimistic lower bound exceeds an actually feasible objective")
    status = (
        "input_unknown"
        if optimistic.proof.termination == "input_unknown"
        else "infeasible_proven"
        if infeasible
        else "optimal_proven"
        if optimal
        else "feasible_not_proven"
        if solution is not None
        else "feasibility_unknown"
    )
    slot_gap = None
    penalty_gap = None
    if incumbent is not None and bound is not None:
        if source.objective_mode == "max_slots_then_min_penalty":
            slot_gap = bound.planned_slots - incumbent.planned_slots
        if source.objective_mode == "meet_targets_min_penalty" or slot_gap == 0:
            penalty_gap = incumbent.penalty_points - bound.penalty_points
    submitted = check_candidate(source, source.submitted_candidate) if source.submitted_candidate is not None else None
    base = check_candidate(source, [])
    missing = sorted({reason for candidate in (base, solution, submitted) if candidate is not None for check in candidate.checks if check.status == "unknown" for reason in check.reason_codes})
    source_binding = RosterBinding(**{key: getattr(source, key) for key in RosterBinding.model_fields if key != "projection_hash"}, projection_hash=hash_content(source.model_dump()))
    analysis = RosterAnalysis(
        schema_version="roster_analysis_v1",
        source_binding=source_binding,
        objective_mode=source.objective_mode,
        solve_status=status,
        optimality_proven=optimal,
        infeasibility_proven=infeasible,
        optimistic_objective_bound=bound,
        feasible_incumbent_objective=incumbent,
        planned_slots_gap=slot_gap,
        penalty_gap_when_slot_bound_closed=penalty_gap,
        solution=solution,
        submitted_candidate_check=submitted,
        definite_search=definite.proof,
        optimistic_search=optimistic.proof,
        warnings=[
            "candidate_plan_only_no_appointment_stock_or_staff_schedule_write",
            "proof_limited_to_complete_declared_department_cohort_dated_sessions_and_local_reviewed_constraints",
            "assigned_person_counts_do_not_certify_continuous_instantaneous_staffing",
            "not_independently_operationally_validated",
        ],
        missing_data=missing,
        instructions_digest=instructions_digest,
        local_runtime=runtime,
    )
    if len(canonical_json(analysis.model_dump()).encode()) > MAX_BYTES:
        raise ValueError("Complete optimization proof exceeds the UTF-8 bound; no truncation is allowed")
    return analysis


def validate_analysis_binding(analysis, source, instructions_digest, model_version):
    if not isinstance(analysis, RosterAnalysis):
        analysis = RosterAnalysis.model_validate(analysis)
    if analysis.local_runtime.model_version != model_version:
        raise ValueError("Requested model differs from actual runtime")
    expected = compute_roster(source, instructions_digest, analysis.local_runtime)
    if analysis.model_dump() != expected.model_dump():
        raise ValueError("Complete optimization, candidate constraints, objectives and frontier proof do not recompute")
    return analysis


def generation_result_for_analysis(analysis):
    if not isinstance(analysis, RosterAnalysis):
        analysis = RosterAnalysis.model_validate(analysis)
    descriptions = {
        "optimal_proven": "已在声明范围与确定性搜索界限下证明所选目标最优。",
        "feasible_not_proven": "已有满足声明约束的候选方案，尚未证明目标最优。",
        "infeasible_proven": "在完整声明范围与乐观放宽图中已证明不存在可行方案。",
        "feasibility_unknown": "尚不能确认存在满足全部声明约束的方案。",
        "input_unknown": "人员或需求范围不完整，无法给出完整可行性与最优性证明。",
    }
    return {
        "summary": descriptions[analysis.solve_status],
        "sections": [
            {
                "title": "声明范围排班与日期号源候选",
                "content": "原量、资格、可用性、连续工时、休息、候选与乐观搜索界限见结构化结果；未知项未补0。由排班负责人核对后决定是否采用。",
                "source_ids": [analysis.source_binding.source_id],
            }
        ],
        "warnings": analysis.warnings,
        "missing_data": analysis.missing_data,
    }
