"""Exact declared-scope workforce checks and bounded deterministic optimization.

All clocks, work integrals and limits use integers.  Optimistic graphs are
mathematical relaxations; they never become an observed roster or observed cost.
"""

import bisect
import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.ai.roster_contract import (
    MAX_SAFE_INTEGER,
    RosterCandidateCheck,
    RosterCheck,
    RosterSessionAllocation,
    RosterSource,
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
