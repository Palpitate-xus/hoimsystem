"""Exact declared-stage constraints and deterministic finite-domain optimization.

No database, application settings, dotenv, network, learned durations, or clinical
defaults. Every result is conditional on the reviewed facts in SurgerySource.
"""

import hashlib
import heapq
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from pydantic import BaseModel

from app.ai.surgery_contract import (
    FRONTIER_LIMIT,
    MAX_BYTES,
    NODE_LIMIT,
    OPERATION_LIMIT,
    Assignment,
    Candidate,
    SearchProof,
    SurgeryAnalysis,
    SurgeryRuntime,
    SurgerySource,
    canonical_json,
    hash_content,
    input_policy_digest,
    recipe_digest,
)

EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
DAY_US = 86400 * 1000000


def implementation_hashes():
    return {f"surgery_{name}": hashlib.sha256(Path(__file__).with_name(f"surgery_{name}.py").read_bytes()).hexdigest() for name in ("contract", "model", "config", "server")}


def clock_us(value):
    delta = datetime.fromisoformat(value.replace("Z", "+00:00")) - EPOCH
    return (delta.days * 86400 + delta.seconds) * 1000000 + delta.microseconds


def utc_us(value):
    try:
        clock = EPOCH + timedelta(microseconds=value)
        if clock.year < 1000:
            raise ValueError("Derived clock exceeds supported Gregorian range")
        return clock.isoformat(timespec="microseconds").replace("+00:00", "Z")
    except OverflowError as exc:
        raise ValueError("Derived clock exceeds supported Gregorian range") from exc


class BudgetLimitError(Exception):
    def __init__(self, reason):
        self.reason = reason
        super().__init__(reason)


@dataclass(slots=True)
class Budget:
    operations: int = 0
    limit: int = OPERATION_LIMIT

    def charge(self, number=1):
        if number < 0:
            raise ValueError("Negative primitive charge")
        if self.operations + number > self.limit:
            raise BudgetLimitError("operation_limit")
        self.operations += number


def overlaps(a, b):
    return max(a[0], b[0]) < min(a[1], b[1])


def union(intervals, budget):
    result = []
    for start, end in sorted(intervals):
        budget.charge()
        if start >= end:
            continue
        if result and start <= result[-1][1]:
            result[-1] = (result[-1][0], max(end, result[-1][1]))
        else:
            result.append((start, end))
    return result


def intersection(a, b):
    low, high = max(a[0], b[0]), min(a[1], b[1])
    return (low, high) if low < high else None


def span_dict(interval):
    return {"start_at": utc_us(interval[0]), "end_at": utc_us(interval[1])}


def contains(coverage, interval):
    return coverage.status == "attested_complete" and clock_us(coverage.start_at) <= interval[0] and clock_us(coverage.end_at) >= interval[1]


class Checks:
    def __init__(self, budget, retain=True):
        self.budget = budget
        self.retain = retain
        self.counts = {key: 0 for key in ("satisfied", "violated", "unknown", "not_applicable")}
        self.classes = defaultdict(lambda: {key: 0 for key in self.counts})
        self.digest = hashlib.sha256(b"[")
        self.number = 0
        self.check_stream_bytes = 2
        self.witness_bytes = 0
        self.violations = []
        self.unknowns = []
        self.hard_unknown = False

    def add(self, check_class, code, status, *, cases=(), resources=(), demands=(), refs=(), hard=True, **data):
        self.budget.charge()
        base = {"status": status, "case_ids": sorted(set(cases)), "resource_ids": sorted(set(resources)), "demand_keys": sorted(set(demands)), "ref_ids": sorted(set(refs))}
        record = {"check_class": check_class, "code": code, **base, **data}
        # A check with thousands of provenance members is not a scalar operation.
        # Charge every structural value before repeated normalization/serialization.
        stack = [record]
        while stack:
            self.budget.charge()
            value = stack.pop()
            if isinstance(value, dict):
                stack.extend(value.values())
            elif isinstance(value, (list, tuple)):
                stack.extend(value)
        encoded = canonical_json(record).encode()
        self.check_stream_bytes += len(encoded) + (1 if self.number else 0)
        if self.check_stream_bytes > MAX_BYTES:
            raise ValueError("Complete canonical check stream exceeds proof construction capacity; no truncation")
        if self.number:
            self.digest.update(b",")
        self.digest.update(encoded)
        self.number += 1
        self.counts[status] += 1
        self.classes[check_class][status] += 1
        if status == "unknown" and hard:
            self.hard_unknown = True
        if self.retain and status in ("violated", "unknown"):
            witness = {"code": code, **base, **data}
            self.witness_bytes += len(canonical_json(witness).encode()) + 1
            if self.witness_bytes > MAX_BYTES or len(self.unknowns) + len(self.violations) >= 32768:
                raise ValueError("Complete constraint witnesses exceed proof capacity; no truncation")
            (self.violations if status == "violated" else self.unknowns).append(witness)

    def scope(self, check_class, code, status, reason="unknown", bases=(), **kwargs):
        self.add(check_class, code, status, reason=reason, basis_hashes=sorted(set(bases)), **kwargs)

    def intervals(self, check_class, code, status, intervals=(), bases=(), **kwargs):
        self.add(check_class, code, status, intervals=[span_dict(x) for x in intervals], basis_hashes=sorted(set(bases)), **kwargs)

    def limit(self, code, status, actual=None, minimum=None, maximum=None, penalty=None, intervals=(), policies=(), **kwargs):
        self.add(
            "transition" if code == "transition" else "work",
            code,
            status,
            intervals=[span_dict(x) for x in intervals],
            actual_us=str(actual) if actual is not None and actual >= 0 else None,
            minimum_us=str(minimum) if minimum is not None else None,
            maximum_us=str(maximum) if maximum is not None else None,
            penalty_points=str(penalty) if penalty is not None else None,
            policy_ids=sorted(set(policies)),
            **kwargs,
        )

    def summary(self):
        value = self.digest.copy()
        value.update(b"]")
        return {"counts": dict(self.counts), "by_class": [{"check_class": key, "counts": self.classes[key]} for key in sorted(self.classes)], "canonical_checks_digest": value.hexdigest()}


@dataclass(slots=True)
class Use:
    case_id: str
    demand_key: str
    resource_id: str | None
    patient: str | None
    intervals: list
    refs: tuple
    segment_ids: tuple
    class_hash: str | None
    counted_work: bool | None
    duty_id: str | None
    unknown: bool
    kind: str


def eligible(refs, facts, budget):
    result = True
    for ref in refs:
        budget.charge()
        fact = facts[ref]
        result = result and fact.status == "published" and fact.review == "confirmed"
    return result


def normalized_segments(case, segment_ids, mode, start, facts, budget):
    segments = {x.segment_id: x for x in case.timing.segments}
    known = []
    starts, ends = [], []
    unknown = False
    reversed_segment = False
    refs = set(case.ref_ids)
    for segment_id in segment_ids:
        budget.charge()
        item = segments[segment_id]
        refs.update(item.ref_ids)
        trusted = eligible(item.ref_ids, facts, budget)
        left = int(item.start_offset_us.value) if trusted and item.start_offset_us.value is not None else None
        right = int(item.end_offset_us.value) if trusted and item.end_offset_us.value is not None else None
        if left is not None:
            starts.append(start + left)
            utc_us(start + left)
        if right is not None:
            ends.append(start + right)
            utc_us(start + right)
        if left is None or right is None:
            unknown = True
        elif right < left:
            reversed_segment = True
        elif right > left:
            known.append((start + left, start + right))
    if mode == "envelope":
        # Any actual envelope starts <= each known start and ends >= each known end.
        # Its provable core is bounded by min known starts / max known ends only;
        # unknown extents remain unknown, not a completed envelope.
        if starts and ends and min(starts) < max(ends):
            known = [(min(starts), max(ends))]
        else:
            known = []
    return union(known, budget), unknown, reversed_segment, tuple(sorted(refs))


def selected_uses(source, assignments, checks, record_case_id=None):
    facts = {x.fact_id: x for x in source.manifest}
    cases = {x.case_id: x for x in source.cases}
    uses = []
    for assignment in assignments:
        checks.budget.charge()
        case = cases[assignment.case_id]
        start = clock_us(assignment.start_at)
        chosen = {case.room.slot_id: assignment.room_id, **{x.slot_id: x.person_id for x in assignment.roles}, **{x.slot_id: x.equipment_id for x in assignment.equipment}}
        selected_duties = {x.slot_id: x.duty_id for x in assignment.roles}
        for demand, kind in [
            (case.room, "room"),
            *((x, "person") for x in sorted(case.roles, key=lambda x: x.slot_id)),
            *((x, "equipment") for x in sorted(case.equipment, key=lambda x: x.slot_id)),
            (case.patient_presence, "patient"),
        ]:
            checks.budget.charge()
            occupation = demand if kind == "patient" else demand.occupation
            key = "patient" if kind == "patient" else demand.slot_id
            intervals, unknown, reversed_segment, refs = normalized_segments(case, occupation.segment_ids, occupation.occupation_mode, start, facts, checks.budget)
            unknown = unknown or not eligible(case.ref_ids, facts, checks.budget)
            if case.timing.method == "unknown" or case.timing.semantics == "unknown":
                unknown = True
                intervals = []
                reversed_segment = False
            if record_case_id is not None and case.case_id != record_case_id:
                pass
            elif reversed_segment or unknown or kind == "room" and not intervals:
                status = "violated" if reversed_segment or kind == "room" and not intervals and not unknown else "unknown"
                checks.intervals("duration", "duration", status, intervals=intervals[:1], bases=[case.timing.basis_hash], cases=[case.case_id], demands=[key], refs=refs)
            else:
                checks.intervals("duration", "duration", "satisfied", intervals=intervals[:1], cases=[case.case_id], demands=[key], refs=refs)
            uses.append(
                Use(
                    case.case_id,
                    key,
                    None if kind == "patient" else chosen[key],
                    case.patient_conflict_token if kind == "patient" else None,
                    intervals,
                    refs,
                    tuple(sorted(occupation.segment_ids)),
                    None if kind == "patient" else occupation.transition_class_hash,
                    None if kind == "patient" else occupation.accounting.counted_as_work,
                    selected_duties.get(key),
                    unknown,
                    kind,
                )
            )
    return uses


def validate_assignment_domain(source, assignments, deferred, checks, partial=False):
    cases = {x.case_id: x for x in source.cases}
    seen = set()
    if len(deferred) != len(set(deferred)):
        raise ValueError("Repeated deferred case")
    for assignment in assignments:
        checks.budget.charge()
        if assignment.case_id not in cases or assignment.case_id in seen or assignment.case_id in deferred:
            raise ValueError("Assignment case membership is inconsistent")
        seen.add(assignment.case_id)
        case = cases[assignment.case_id]
        checks.budget.charge(len(case.starts))
        if assignment.start_at not in {x.start_at for x in case.starts}:
            raise ValueError("Assignment is outside the complete finite start domain")
        if (
            len(assignment.roles) != len(case.roles)
            or {x.slot_id for x in assignment.roles} != {x.slot_id for x in case.roles}
            or len(assignment.equipment) != len(case.equipment)
            or {x.slot_id for x in assignment.equipment} != {x.slot_id for x in case.equipment}
        ):
            raise ValueError("Assignment must select every exact role and equipment quantity slot")
        for demand, resource_id, duty_id in [
            (case.room, assignment.room_id, None),
            *((x, next(y.person_id for y in assignment.roles if y.slot_id == x.slot_id), next(y.duty_id for y in assignment.roles if y.slot_id == x.slot_id)) for x in case.roles),
            *((x, next(y.equipment_id for y in assignment.equipment if y.slot_id == x.slot_id), None) for x in case.equipment),
        ]:
            checks.budget.charge(len(demand.choices))
            if not any(x.resource_id == resource_id and (x.duty_binding.duty_id if x.duty_binding else None) == duty_id for x in demand.choices):
                raise ValueError("Assignment is outside the declared resource/duty choice domain")
    for case_id in deferred:
        checks.budget.charge()
        if case_id not in cases or cases[case_id].required:
            raise ValueError("Required/missing cases cannot be deferred")
    if not partial and seen | set(deferred) != cases.keys():
        raise ValueError("A complete candidate must account for every original case")


def qualification_status(resource, demand, interval, facts, budget):
    if not demand.capability_hashes:
        return "unknown" if resource.kind == "person" else "satisfied"
    all_results = []
    for capability in demand.capability_hashes:
        budget.charge()
        boundaries = {interval[0], interval[1]}
        relevant = []
        for item in resource.capability_facts:
            budget.charge(1 + len(item.capability_hashes))
            if capability not in item.capability_hashes:
                continue
            left = clock_us(item.valid_from_at)
            right = clock_us(item.valid_until.at) if item.valid_until.kind == "known" else interval[1]
            overlap = intersection(interval, (left, right))
            if overlap:
                boundaries.update(overlap)
                relevant.append((item, left, right, eligible(item.ref_ids, facts, budget)))
        results = []
        points = sorted(boundaries)
        for start, end in zip(points, points[1:]):
            states = set()
            for item, left, right, trusted in relevant:
                budget.charge()
                if left <= start and right >= end:
                    states.add(item.status if trusted and item.valid_until.kind != "unknown" else "unknown")
            results.append("satisfied" if states == {"verified"} else "violated" if states == {"not_verified"} else "unknown")
        all_results.extend(results)
    return "violated" if "violated" in all_results else "unknown" if "unknown" in all_results else "satisfied"


def availability_status(resource, interval, facts, budget):
    boundaries = {interval[0], interval[1]}
    relevant = []
    for item in resource.availability:
        budget.charge()
        span = (clock_us(item.start_at), clock_us(item.end_at))
        overlap = intersection(interval, span)
        if overlap:
            boundaries.update(overlap)
            relevant.append((item, span, eligible(item.ref_ids, facts, budget)))
    states = []
    points = sorted(boundaries)
    for start, end in zip(points, points[1:]):
        values = set()
        for item, span, trusted in relevant:
            budget.charge()
            if span[0] <= start and span[1] >= end:
                values.add(item.state if trusted else "unknown")
        states.append("satisfied" if values == {"available"} else "violated" if values == {"unavailable"} else "unknown")
    return "violated" if "violated" in states else "unknown" if "unknown" in states or not contains(resource.availability_coverage, interval) else "satisfied"


def monotone_checks(source, assignments, uses, checks, new_case_id=None):
    facts = {x.fact_id: x for x in source.manifest}
    resources = {x.resource_id: x for x in source.resources}
    cases = {x.case_id: x for x in source.cases}
    demands = {(case.case_id, demand.slot_id): demand for case in source.cases for demand in [case.room, *case.roles, *case.equipment]}
    period = (clock_us(source.period.days[0].start_at), clock_us(source.period.days[-1].end_at))
    for assignment in assignments:
        if new_case_id is not None and assignment.case_id != new_case_id:
            continue
        checks.budget.charge()
        case = cases[assignment.case_id]
        case_uses = [x for x in uses if x.case_id == case.case_id]
        anchor = clock_us(assignment.start_at)
        checks.intervals("time", "time_bounds", "satisfied" if period[0] <= anchor < period[1] else "violated", cases=[case.case_id], bases=[source.original_scope_hash], refs=case.ref_ids)
        for limit, lower in ((case.release, True), (case.deadline, False)):
            if limit.kind == "known":
                at = clock_us(limit.at)
                violation = any((start < at if lower else end > at) for use in case_uses for start, end in use.intervals)
                status = "violated" if violation else "unknown" if any(x.unknown for x in case_uses) else "satisfied"
            else:
                status = "unknown" if limit.kind == "unknown" else "not_applicable"
            checks.intervals("time", "time_bounds", status, cases=[case.case_id], refs=case.ref_ids)
    for use in uses:
        if new_case_id is not None and use.case_id != new_case_id:
            continue
        checks.budget.charge()
        case = cases[use.case_id]
        if use.kind == "patient":
            if case.patient_identity_status != "verified" or use.patient is None:
                checks.add("identity", "identity_unknown", "unknown", cases=[use.case_id], demands=[use.demand_key], refs=use.refs, intervals=[], patient_conflict_token=use.patient)
            continue
        resource = resources[use.resource_id]
        trusted = eligible(resource.ref_ids, facts, checks.budget)
        checks.add(
            "identity",
            "identity_unknown",
            "satisfied" if trusted and resource.identity_status == "verified" else "unknown",
            cases=[use.case_id],
            resources=[use.resource_id],
            demands=[use.demand_key],
            refs=resource.ref_ids,
            intervals=[],
            patient_conflict_token=None,
        )
        demand = demands[use.case_id, use.demand_key]
        for interval in use.intervals:
            checks.budget.charge()
            checks.intervals(
                "qualification",
                "qualification",
                qualification_status(resource, demand, interval, facts, checks.budget),
                intervals=[interval],
                bases=[resource.identity_hash],
                cases=[use.case_id],
                resources=[use.resource_id],
                demands=[use.demand_key],
                refs=use.refs,
            )
            checks.intervals(
                "availability",
                "availability",
                availability_status(resource, interval, facts, checks.budget),
                intervals=[interval],
                bases=[resource.availability_coverage.basis_hash],
                cases=[use.case_id],
                resources=[use.resource_id],
                demands=[use.demand_key],
                refs=use.refs,
            )
            if not contains(resource.all_locations_busy_coverage, interval):
                checks.scope(
                    "scope",
                    "coverage",
                    "unknown",
                    "outside_coverage",
                    bases=[resource.all_locations_busy_coverage.basis_hash],
                    cases=[use.case_id],
                    resources=[use.resource_id],
                    demands=[use.demand_key],
                    refs=use.refs,
                )
    for index, left in enumerate(uses):
        if new_case_id is not None and left.case_id != new_case_id:
            continue
        for other_index, right in enumerate(uses):
            if index == other_index or (new_case_id is None or right.case_id == new_case_id) and other_index < index:
                continue
            checks.budget.charge()
            same_patient = left.kind == right.kind == "patient" and left.patient is not None and left.patient == right.patient
            same_resource = left.resource_id is not None and left.resource_id == right.resource_id
            uncertain_identity = left.kind == right.kind == "person" and left.resource_id != right.resource_id and source.person_partition.status == "unknown"
            if not (same_patient or same_resource or uncertain_identity):
                continue
            for a in left.intervals:
                for b in right.intervals:
                    checks.budget.charge()
                    if overlaps(a, b):
                        code = "patient_overlap" if same_patient else "identity_unknown" if uncertain_identity else "resource_overlap"
                        checks.add(
                            "overlap",
                            code,
                            "unknown" if uncertain_identity else "violated",
                            cases=[left.case_id, right.case_id],
                            resources=[x for x in (left.resource_id, right.resource_id) if x],
                            demands=[left.demand_key, right.demand_key],
                            refs=[*left.refs, *right.refs],
                            intervals=[span_dict(a), span_dict(b)],
                            patient_conflict_token=left.patient if same_patient else None,
                        )
    for use in uses:
        if new_case_id is not None and use.case_id != new_case_id:
            continue
        for busy in source.busy_intervals:
            checks.budget.charge()
            matches = (
                busy.target.kind == "resource"
                and use.resource_id == busy.target.resource_id
                or busy.target.kind == "patient"
                and use.kind == "patient"
                and use.patient == busy.target.patient_conflict_token
            )
            if not matches or busy.busy_status == "cancelled":
                continue
            trusted = eligible(busy.ref_ids, facts, checks.budget)
            if not trusted or busy.busy_status == "unknown":
                checks.scope(
                    "busy",
                    "coverage",
                    "unknown",
                    "unavailable_original" if not trusted else "unknown",
                    bases=[busy.basis_hash],
                    cases=[use.case_id],
                    resources=[use.resource_id] if use.resource_id else [],
                    refs=busy.ref_ids,
                )
                continue
            left = clock_us(busy.start_at)
            end = busy.end_at or (busy.verified_until_at if busy.continuity_status == "confirmed" else None)
            right = clock_us(end) if end else left
            for interval in use.intervals:
                checks.budget.charge()
                if left < right and overlaps(interval, (left, right)):
                    checks.add(
                        "busy",
                        "patient_overlap" if use.kind == "patient" else "resource_overlap",
                        "violated",
                        cases=[use.case_id],
                        resources=[use.resource_id] if use.resource_id else [],
                        demands=[use.demand_key],
                        refs=[*use.refs, *busy.ref_ids],
                        intervals=[span_dict(interval), span_dict((left, right))],
                        patient_conflict_token=use.patient if use.kind == "patient" else None,
                    )
                elif busy.end_at is None and interval[1] > right and interval[1] > left:
                    checks.scope("busy", "coverage", "unknown", "unknown", bases=[busy.basis_hash], cases=[use.case_id], resources=[use.resource_id] if use.resource_id else [], refs=busy.ref_ids)


def source_scope_checks(source, checks):
    period = (clock_us(source.period.days[0].start_at), clock_us(source.period.days[-1].end_at))
    complete = source.problem_coverage.finite_domains_status == "attested_complete"
    for name in ("cases", "resources", "all_locations_busy", "policies"):
        coverage = getattr(source.problem_coverage, name)
        status = "satisfied" if contains(coverage, period) else "unknown"
        checks.scope("scope", "coverage", status, "outside_coverage", bases=[coverage.basis_hash])
        if name in ("cases", "resources"):
            complete = complete and status == "satisfied"
    for case in source.cases:
        checks.budget.charge()
        domains = [case.start_domain_status, *(x.domain_status for x in [case.room, *case.roles, *case.equipment])]
        if any(x != "attested_complete" for x in domains):
            complete = False
    checks.scope("scope", "domain_closure", "satisfied" if complete else "unknown", "incomplete", bases=[source.problem_coverage.basis_hash])
    return complete


def fixed_busy_checks(source, checks):
    groups = defaultdict(list)
    for busy in source.busy_intervals:
        checks.budget.charge()
        if busy.busy_status == "cancelled":
            continue
        if busy.busy_status == "unknown" or busy.end_at is None:
            checks.scope("busy", "coverage", "unknown", "unknown", refs=busy.ref_ids, bases=[busy.basis_hash])
        if busy.busy_status == "unknown":
            continue
        end = busy.end_at or (busy.verified_until_at if busy.continuity_status == "confirmed" else None)
        if end is None or end <= busy.start_at:
            continue
        key = (busy.target.kind, busy.target.resource_id if busy.target.kind == "resource" else busy.target.patient_conflict_token)
        groups[key].append((clock_us(busy.start_at), clock_us(end), busy))
    for key in sorted(groups):
        active = []
        for start, end, busy in sorted(groups[key], key=lambda x: (x[0], x[1], x[2].interval_id)):
            checks.budget.charge()
            remaining = []
            for left, right, previous in active:
                checks.budget.charge()
                if right <= start:
                    continue
                remaining.append((left, right, previous))
                checks.add(
                    "busy",
                    "resource_overlap" if key[0] == "resource" else "patient_overlap",
                    "violated",
                    resources=[key[1]] if key[0] == "resource" else [],
                    refs=[*previous.ref_ids, *busy.ref_ids],
                    intervals=[span_dict((left, right)), span_dict((start, end))],
                    patient_conflict_token=key[1] if key[0] == "patient" else None,
                )
            remaining.append((start, end, busy))
            active = remaining


def separable_cost(source, assignments, deferred, checks):
    cases = {x.case_id: x for x in source.cases}
    total = 0
    exact = True

    def add(amount, case_id):
        nonlocal total, exact
        checks.budget.charge()
        if amount.value is None:
            exact = False
            checks.scope("cost", "cost_unknown", "unknown", amount.absent_reason, cases=[case_id], hard=False)
        else:
            total += int(amount.value)

    for assignment in assignments:
        case = cases[assignment.case_id]
        add(case.penalty_if_scheduled, case.case_id)
        for start in case.starts:
            checks.budget.charge()
            if start.start_at == assignment.start_at:
                add(start.penalty, case.case_id)
                break
        for demand, resource_id, duty_id in [
            (case.room, assignment.room_id, None),
            *((x, next(y.person_id for y in assignment.roles if y.slot_id == x.slot_id), next(y.duty_id for y in assignment.roles if y.slot_id == x.slot_id)) for x in case.roles),
            *((x, next(y.equipment_id for y in assignment.equipment if y.slot_id == x.slot_id), None) for x in case.equipment),
        ]:
            for choice in demand.choices:
                checks.budget.charge()
                if choice.resource_id == resource_id and (choice.duty_binding.duty_id if choice.duty_binding else None) == duty_id:
                    add(choice.penalty, case.case_id)
                    break
    for case_id in deferred:
        add(cases[case_id].penalty_if_deferred, case_id)
    return total, exact


def output_occupancies(uses, checks):
    output = []
    size = checks.witness_bytes
    for use in uses:
        for interval in use.intervals:
            checks.budget.charge()
            value = {
                "case_id": use.case_id,
                "demand_key": use.demand_key,
                "resource_id": use.resource_id,
                "patient_conflict_token": use.patient,
                **span_dict(interval),
                "source_segment_ids": list(use.segment_ids),
                "ref_ids": list(use.refs),
            }
            size += len(canonical_json(value).encode()) + 1
            if size > MAX_BYTES or len(output) >= 300000:
                raise ValueError("Complete selected-stage proof exceeds capacity; no truncation")
            output.append(value)
    return output


def check_partial_assignments(source, assignments, budget, new_case_id=None):
    """Only permanent violations; no adjacency, minima, or duty-group pruning."""
    checks = Checks(budget, retain=False)
    uses = selected_uses(source, assignments, checks, record_case_id=new_case_id)
    monotone_checks(source, assignments, uses, checks, new_case_id=new_case_id)
    return checks.counts["violated"] == 0


def policy_effect(policy, interval):
    start = clock_us(policy.effective_from_at)
    if policy.effective_until.kind == "known":
        end = clock_us(policy.effective_until.at)
        if end <= interval[0] or start >= interval[1]:
            return "outside"
    else:
        end = interval[1]
    return "full" if start <= interval[0] and end >= interval[1] and policy.effective_until.kind != "unknown" else "partial"


def transition_checks(source, uses, checks, graph):
    resources = {x.resource_id: x for x in source.resources}
    facts = {x.fact_id: x for x in source.manifest}
    total, exact = 0, True
    by_resource = defaultdict(list)
    policy_index = defaultdict(list)
    for policy in source.transition_policies:
        for resource_id in policy.resource_ids:
            checks.budget.charge()
            policy_index[resource_id].append(policy)
    unknown_resources = set()
    selected_resources = set(resources)
    for use in uses:
        checks.budget.charge()
        if use.resource_id is None:
            continue
        if use.unknown or resources[use.resource_id].identity_status == "unknown" or use.kind == "person" and source.person_partition.status == "unknown":
            unknown_resources.add(use.resource_id)
        for start, end in use.intervals:
            by_resource[use.resource_id].append((start, end, use.case_id, use.demand_key, use.class_hash, use.refs))
    # An unresolved identity can merge a separate stream, hence alter adjacency.
    unknown_kinds = {item.kind for item in source.resources if item.identity_status == "unknown"}
    for resource_id in selected_resources:
        if resources[resource_id].kind in unknown_kinds:
            unknown_resources.add(resource_id)
    for busy in source.busy_intervals:
        checks.budget.charge()
        if busy.target.kind != "resource" or busy.target.resource_id not in selected_resources or busy.busy_status == "cancelled":
            continue
        resource_id = busy.target.resource_id
        if busy.busy_status == "unknown" or not eligible(busy.ref_ids, facts, checks.budget):
            unknown_resources.add(resource_id)
            continue
        end = busy.end_at or (busy.verified_until_at if busy.continuity_status == "confirmed" else None)
        if busy.end_at is None:
            unknown_resources.add(resource_id)
        if end is not None and end > busy.start_at:
            by_resource[resource_id].append((clock_us(busy.start_at), clock_us(end), busy.interval_id, "busy", busy.transition_class_hash, tuple(busy.ref_ids)))
    for resource_id in sorted(selected_resources):
        checks.budget.charge()
        resource = resources[resource_id]
        timeline = sorted(by_resource[resource_id])
        period = (clock_us(source.period.days[0].start_at), clock_us(source.period.days[-1].end_at))
        policies = []
        for policy in policy_index[resource_id]:
            checks.budget.charge()
            if policy_effect(policy, period) != "outside":
                policies.append(policy)
        review = resource.transition_policy_review
        if review.status == "unknown" or review.status == "reviewed_policies" and not policies:
            checks.scope("transition", "policy_unknown", "unknown", "missing_policy", resources=[resource_id], bases=[review.basis_hash])
            exact = False
        elif review.status == "attested_not_required" and policies:
            checks.scope("transition", "policy_unknown", "unknown", "conflicting_originals", resources=[resource_id], bases=[review.basis_hash])
        if not policies:
            continue
        if resource_id in unknown_resources:
            checks.scope("transition", "sequence_relaxed", "unknown", "unknown_adjacency", resources=[resource_id], bases=[resource.identity_hash, resource.transition_class_coverage.basis_hash])
            exact = False
            continue
        for left, right in zip(timeline, timeline[1:]):
            checks.budget.charge()
            if left[2:4] == right[2:4]:
                continue
            gap = right[0] - left[1]
            # Effectivity concerns the boundary pair, including its exact clocks.
            span = (min(left[1], right[0]), max(left[1], right[0]) + 1)
            for policy in sorted(policies, key=lambda x: x.policy_id):
                checks.budget.charge()
                effect = policy_effect(policy, span)
                if effect == "outside":
                    continue
                if effect != "full":
                    checks.scope("transition", "policy_unknown", "unknown", "partial_effectivity", resources=[resource_id], refs=policy.ref_ids, bases=[policy.basis_hash])
                    exact = False
                    continue
                pair = None
                for item in policy.pairs:
                    checks.budget.charge()
                    if (item.from_class_hash, item.to_class_hash) == (left[4], right[4]):
                        pair = item
                        break
                if pair is None:
                    checks.scope("transition", "policy_unknown", "unknown", "missing_pair", resources=[resource_id], refs=policy.ref_ids, bases=[policy.basis_hash])
                    exact = False
                    continue
                if pair.minimum_gap_us.value is None:
                    checks.scope("transition", "policy_unknown", "unknown", pair.minimum_gap_us.absent_reason, resources=[resource_id], refs=policy.ref_ids, bases=[pair.basis_hash])
                else:
                    minimum = int(pair.minimum_gap_us.value)
                    checks.limit(
                        "transition",
                        "satisfied" if gap >= minimum else "violated",
                        actual=gap,
                        minimum=minimum,
                        intervals=[(left[0], left[1]), (right[0], right[1])],
                        policies=[policy.policy_id],
                        resources=[resource_id],
                        refs=policy.ref_ids,
                    )
                if pair.penalty.value is None:
                    exact = False
                    checks.scope("cost", "cost_unknown", "unknown", pair.penalty.absent_reason, hard=False, resources=[resource_id], refs=policy.ref_ids, bases=[pair.basis_hash])
                else:
                    total += int(pair.penalty.value)
    return total, exact


def account_intervals(interval, accounting, budget):
    """Return a proven counted-work subset plus explicit nonwork breaks."""
    work, nonwork = [], []
    cursor = interval[0]
    complete = accounting.time_accounting_status == "verified"
    for item in accounting.breaks:
        budget.charge()
        start, end = clock_us(item.start_at), clock_us(item.end_at)
        if start < interval[0] or end > interval[1]:
            complete = False
            continue
        if accounting.counted_as_work is True and accounting.breaks_complete and cursor < start:
            work.append((cursor, start))
        if item.counted_as_work is True:
            work.append((start, end))
        elif item.counted_as_work is False:
            nonwork.append((start, end))
        cursor = end
    if accounting.counted_as_work is True and accounting.breaks_complete and cursor < interval[1]:
        work.append((cursor, interval[1]))
    return work, nonwork, complete


class WorkIntegral:
    def __init__(self, intervals, budget):
        self.intervals = union(intervals, budget)
        self.prefix = [0]
        self.budget = budget
        for start, end in self.intervals:
            budget.charge()
            self.prefix.append(self.prefix[-1] + end - start)

    def until(self, point):
        low, high = 0, len(self.intervals)
        while low < high:
            self.budget.charge()
            mid = (low + high) // 2
            if self.intervals[mid][0] < point:
                low = mid + 1
            else:
                high = mid
        if low == 0:
            return 0
        start, end = self.intervals[low - 1]
        return self.prefix[low - 1] + max(0, min(point, end) - start)

    def within(self, start, end):
        self.budget.charge()
        return self.until(end) - self.until(start)

    def rolling_maximum(self, width, affected):
        # All breakpoints of F(t)-F(t-width), plus the affected range boundaries.
        lower, upper = affected[0], affected[1] + width
        points = {lower, upper}
        for start, end in self.intervals:
            self.budget.charge()
            for point in (start, end, start + width, end + width):
                if lower <= point <= upper:
                    points.add(point)
        maximum, window = 0, (lower - width, lower)
        for end in sorted(points):
            self.budget.charge()
            actual = self.within(end - width, end)
            if actual > maximum:
                maximum, window = actual, (end - width, end)
        return maximum, window


def work_value(limit):
    return int(limit.value) * (60000000 if limit.unit == "min" else 1) if limit.value is not None else None


def witness_spans(intervals):
    try:
        for start, end in intervals:
            utc_us(start)
            utc_us(end)
        return intervals
    except ValueError:
        return []


def work_checks(source, assignments, uses, checks, graph):
    resources = {x.resource_id: x for x in source.resources}
    duties = {x.duty_id: x for x in source.duties}
    cases = {x.case_id: x for x in source.cases}
    by_person = defaultdict(list)
    policy_index = defaultdict(list)
    for policy in source.work_policies:
        for person_id in policy.person_ids:
            checks.budget.charge()
            policy_index[person_id].append(policy)
    for resource in source.resources:
        checks.budget.charge()
        if resource.kind == "person":
            by_person[resource.resource_id] = []
    for use in uses:
        checks.budget.charge()
        if use.kind == "person":
            by_person[use.resource_id].append(use)
    for person_id in sorted(by_person):
        person = resources[person_id]
        person_uses = by_person[person_id]
        period = (clock_us(source.period.days[0].start_at), clock_us(source.period.days[-1].end_at))
        scope_span = period
        for use in person_uses:
            for interval in use.intervals:
                checks.budget.charge()
                scope_span = (min(scope_span[0], interval[0]), max(scope_span[1], interval[1]))
        policies = []
        for policy in policy_index[person_id]:
            checks.budget.charge()
            if policy_effect(policy, scope_span) != "outside":
                policies.append(policy)
        review = person.work_policy_review
        if review.status == "attested_not_required" and not policies:
            continue
        if review.status == "unknown" or not policies:
            checks.scope("work", "policy_unknown", "unknown", "missing_policy", resources=[person_id], bases=[review.basis_hash])
        elif review.status == "attested_not_required":
            checks.scope("work", "policy_unknown", "unknown", "conflicting_originals", resources=[person_id], bases=[review.basis_hash])
        selected_duties = set()
        known_work = []
        complete_work = True
        original_nonwork = []
        presence = [interval for use in person_uses for interval in use.intervals]
        if person_uses and not presence:
            checks.scope("work", "coverage", "unknown", "unknown_timing", resources=[person_id])
        affected = (min([period[0], *(x[0] for x in presence)]), max([period[1], *(x[1] for x in presence)]))
        # Duty boundary/rest/policy scope cannot be shrunk to the surgery segment.
        for use in person_uses:
            checks.budget.charge()
            duty = duties.get(use.duty_id)
            if duty is not None:
                affected = (min(affected[0], clock_us(duty.start_at)), max(affected[1], clock_us(duty.end_at)))
        dependency = affected
        for policy in policies:
            checks.budget.charge()
            rest = work_value(policy.minimum_rest) or 0
            radius = max(rest, DAY_US if policy.max_work_rolling_24h.value is not None else 0, 7 * DAY_US if policy.max_work_rolling_7d.value is not None else 0)
            dependency = (min(dependency[0], affected[0] - radius), max(dependency[1], affected[1] + radius))
            for window in policy.fixed_windows:
                checks.budget.charge()
                dependency = (min(dependency[0], clock_us(window.start_at)), max(dependency[1], clock_us(window.end_at)))
        complete_work = contains(person.all_locations_duty_coverage, dependency)
        checks.scope("work", "coverage", "satisfied" if complete_work else "unknown", "outside_coverage", resources=[person_id], bases=[person.all_locations_duty_coverage.basis_hash])
        relevant_duties = []
        for duty in source.duties:
            checks.budget.charge()
            interval = (clock_us(duty.start_at), clock_us(duty.end_at))
            if duty.person_id != person_id or not overlaps(interval, dependency):
                continue
            relevant_duties.append(duty)
            work, nonwork, complete = account_intervals(interval, duty.accounting, checks.budget)
            known_work.extend(work)
            original_nonwork.extend(nonwork)
            complete_work = complete_work and complete
        for use in person_uses:
            checks.budget.charge()
            case = cases[use.case_id]
            demand = next(x for x in case.roles if x.slot_id == use.demand_key)
            binding = next(x.duty_binding for x in demand.choices if x.resource_id == person_id and x.duty_binding.duty_id == use.duty_id)
            duty = duties.get(use.duty_id)
            status = "unknown"
            if binding.status == "verified" and duty is not None:
                selected_duties.add(duty.duty_id)
                span = (clock_us(duty.start_at), clock_us(duty.end_at))
                status = "violated" if any(not (span[0] <= start and end <= span[1]) for start, end in use.intervals) else "unknown" if use.unknown else "satisfied"
            checks.intervals(
                "duty", "duty_membership", status, intervals=use.intervals[:1], bases=[binding.basis_hash], cases=[use.case_id], resources=[person_id], demands=[use.demand_key], refs=use.refs
            )
            if use.counted_work is True:
                known_work.extend(use.intervals)
                for interval in use.intervals:
                    for nonwork in original_nonwork:
                        checks.budget.charge()
                        if overlaps(interval, nonwork):
                            checks.intervals(
                                "accounting", "accounting_conflict", "violated", intervals=[interval, nonwork], cases=[use.case_id], resources=[person_id], demands=[use.demand_key], refs=use.refs
                            )
            elif use.counted_work is None:
                complete_work = False
            complete_work = complete_work and not use.unknown
        # Actual all-location work capsules can add work not duplicated by a duty.
        for busy in source.busy_intervals:
            checks.budget.charge()
            if busy.target.kind != "resource" or busy.target.resource_id != person_id or busy.busy_status == "cancelled":
                continue
            end = busy.end_at or (busy.verified_until_at if busy.continuity_status == "confirmed" else None)
            if end is None or busy.busy_status == "unknown":
                complete_work = False
                continue
            interval = (clock_us(busy.start_at), clock_us(end))
            if not overlaps(interval, dependency):
                continue
            work, _, complete = account_intervals(interval, busy.accounting, checks.budget)
            known_work.extend(work)
            complete_work = complete_work and complete and busy.end_at is not None
            if work and not any(clock_us(duty.start_at) <= interval[0] and clock_us(duty.end_at) >= interval[1] for duty in relevant_duties):
                complete_work = False
        if not complete_work:
            checks.scope("accounting", "coverage", "unknown", "accounting_unknown", resources=[person_id])
        integral = WorkIntegral(known_work, checks.budget)
        for policy in sorted(policies, key=lambda x: x.policy_id):
            checks.budget.charge()
            effect_span = affected
            for window in policy.fixed_windows:
                checks.budget.charge()
                effect_span = (min(effect_span[0], clock_us(window.start_at)), max(effect_span[1], clock_us(window.end_at)))
            effect = policy_effect(policy, effect_span)
            if effect == "outside":
                continue
            if effect != "full":
                checks.scope("work", "policy_unknown", "unknown", "partial_effectivity", resources=[person_id], refs=policy.ref_ids, bases=[policy.basis_hash])
                continue
            common = {"resources": [person_id], "policies": [policy.policy_id], "refs": policy.ref_ids}
            limits = [
                ("maximum_presence", policy.max_single_presence),
                ("rolling_work", policy.max_work_rolling_24h),
                ("rolling_work", policy.max_work_rolling_7d),
                ("minimum_rest", policy.minimum_rest),
            ]
            for code, limit in limits:
                checks.budget.charge()
                if limit.value is None and limit.absent_reason == "unknown":
                    checks.scope("work", "policy_unknown", "unknown", "unknown", resources=[person_id], refs=policy.ref_ids, bases=[policy.basis_hash])
            maximum_presence = work_value(policy.max_single_presence)
            if maximum_presence is not None:
                for duty in relevant_duties:
                    checks.budget.charge()
                    span = (clock_us(duty.start_at), clock_us(duty.end_at))
                    if not overlaps(span, affected):
                        continue
                    checks.limit(
                        "maximum_presence", "violated" if span[1] - span[0] > maximum_presence else "satisfied", actual=span[1] - span[0], maximum=maximum_presence, intervals=[span], **common
                    )
            for width, limit in ((DAY_US, policy.max_work_rolling_24h), (7 * DAY_US, policy.max_work_rolling_7d)):
                maximum = work_value(limit)
                if maximum is not None:
                    actual, window = integral.rolling_maximum(width, affected)
                    status = "violated" if actual > maximum else "satisfied" if complete_work else "unknown"
                    checks.limit("rolling_work", status, actual=actual, maximum=maximum, intervals=witness_spans([window]), **common)
            minimum_rest = work_value(policy.minimum_rest)
            if minimum_rest is not None:
                ordered = sorted(relevant_duties, key=lambda x: (x.start_at, x.end_at, x.duty_id))
                for left, right in zip(ordered, ordered[1:]):
                    checks.budget.charge()
                    if clock_us(right.end_at) <= affected[0] or clock_us(left.start_at) >= affected[1]:
                        continue
                    gap = clock_us(right.start_at) - clock_us(left.end_at)
                    # Group membership is explicit. No case insertion can merge duties.
                    checks.limit(
                        "minimum_rest",
                        "violated" if gap < minimum_rest else "satisfied",
                        actual=gap,
                        minimum=minimum_rest,
                        intervals=[(clock_us(left.start_at), clock_us(left.end_at)), (clock_us(right.start_at), clock_us(right.end_at))],
                        **common,
                    )
            for window in policy.fixed_windows:
                checks.budget.charge()
                span = (clock_us(window.start_at), clock_us(window.end_at))
                actual = integral.within(*span)
                minimum, maximum = work_value(window.minimum_work), work_value(window.maximum_work)
                for limit in (window.minimum_work, window.maximum_work):
                    if limit.value is None and limit.absent_reason == "unknown":
                        checks.scope("work", "policy_unknown", "unknown", "unknown", resources=[person_id], refs=policy.ref_ids, bases=[policy.basis_hash])
                violation = maximum is not None and actual > maximum or minimum is not None and maximum is not None and minimum > maximum or complete_work and minimum is not None and actual < minimum
                checks.limit("work_window", "violated" if violation else "satisfied" if complete_work else "unknown", actual=actual, minimum=minimum, maximum=maximum, intervals=[span], **common)


def check_candidate(source, assignments, deferred, budget=None, graph="definite"):
    source = source if isinstance(source, SurgerySource) else SurgerySource.model_validate(source)
    assignments = [x if isinstance(x, Assignment) else Assignment.model_validate(x) for x in assignments]
    assignments.sort(key=lambda x: x.case_id)
    budget = budget or Budget()
    checks = Checks(budget)
    validate_assignment_domain(source, assignments, deferred, checks)
    source_scope_checks(source, checks)
    fixed_busy_checks(source, checks)
    uses = selected_uses(source, assignments, checks)
    monotone_checks(source, assignments, uses, checks)
    cases = {x.case_id: x for x in source.cases}
    for assignment in assignments:
        case = cases[assignment.case_id]
        checks.scope(
            "requirements",
            "requirements_unknown",
            "satisfied" if case.other_requirements.status in ("attested_not_required", "all_required_modeled") else "unknown",
            "incomplete",
            bases=[case.other_requirements.basis_hash],
            cases=[case.case_id],
            refs=case.ref_ids,
        )
    cost, exact_cost = separable_cost(source, assignments, deferred, checks)
    transition_cost, exact_transition = transition_checks(source, uses, checks, graph)
    work_checks(source, assignments, uses, checks, graph)
    cost += transition_cost
    exact_cost = exact_cost and exact_transition
    conditions = {cases[x.case_id].timing.semantics for x in assignments}
    condition = next(iter(conditions)) if len(conditions) == 1 else "mixed" if conditions and "unknown" not in conditions else "unknown"
    data = {
        "status": "feasible_under_declared_scope" if not checks.counts["violated"] and not checks.hard_unknown else "provisional_unknown",
        "assignments": [x.model_dump() for x in assignments],
        "deferred_case_ids": sorted(deferred),
        "scheduled_count": len(assignments),
        "optional_scheduled_count": sum(not cases[x.case_id].required for x in assignments),
        "exact_penalty_points": str(cost) if exact_cost else None,
        "penalty_lower_bound": str(cost),
        "duration_condition": condition,
        "occupancies": output_occupancies(uses, checks),
        "check_summary": checks.summary(),
        "violations": checks.violations,
        "unknowns": checks.unknowns,
    }
    data["candidate_digest"] = hash_content(data)
    if len(canonical_json(data).encode()) > MAX_BYTES:
        raise ValueError("Complete candidate proof exceeds byte capacity; no truncation")
    return Candidate.model_validate(data)


@dataclass(slots=True)
class PathNode:
    parent: object
    case_index: int
    step: int
    choice: int
    depth: int
    digest: str


@dataclass(slots=True)
class SearchNode:
    path: PathNode | None
    case_index: int
    step: int
    cursor: int
    bound: tuple
    serial: int


@dataclass(slots=True)
class CasePlan:
    case: object
    demands: tuple
    starts: tuple
    choices: tuple
    minimum_costs: tuple
    schedule_minimum: int | None


def charge_source(source, budget):
    stack = [source]
    while stack:
        budget.charge()
        value = stack.pop()
        if isinstance(value, BaseModel):
            stack.extend(getattr(value, name) for name in value.__class__.model_fields)
        elif isinstance(value, (list, tuple)):
            stack.extend(value)


def choice_key(choice):
    return choice.resource_id, choice.duty_binding.duty_id or "" if choice.duty_binding else ""


def prepare_plans(source, budget):
    plans = []
    for case in source.cases:
        budget.charge()
        demands = (case.room, *sorted(case.roles, key=lambda x: x.slot_id), *sorted(case.equipment, key=lambda x: x.slot_id))
        domains = tuple(tuple(sorted(demand.choices, key=choice_key)) for demand in demands)
        starts = tuple(sorted(case.starts, key=lambda x: x.start_at))
        minima = []
        for domain in (starts, *domains):
            minimum = None
            for value in domain:
                budget.charge()
                penalty = int(value.penalty.value) if value.penalty.value is not None else 0
                minimum = penalty if minimum is None else min(minimum, penalty)
            minima.append(minimum)
        schedule = None if any(value is None for value in minima) else sum(minima) + (int(case.penalty_if_scheduled.value) if case.penalty_if_scheduled.value is not None else 0)
        plans.append(CasePlan(case, demands, starts, domains, tuple(minima), schedule))

    def order(plan):
        cardinality = len(plan.starts)
        for values in plan.choices:
            cardinality *= len(values)
        return not plan.case.required, cardinality, plan.case.case_id

    return sorted(plans, key=order)


def path_values(path, budget):
    values = {}
    while path is not None:
        budget.charge()
        values[(path.case_index, path.step)] = path.choice
        path = path.parent
    return values


def penalty(amount):
    return int(amount.value) if amount.value is not None else 0


def lower_bound(plans, path, mode, budget):
    values = path_values(path, budget)
    total, optional_upper = 0, 0
    for index, plan in enumerate(plans):
        budget.charge()
        gate = values.get((index, 0))
        if gate == 1:
            total += penalty(plan.case.penalty_if_deferred)
            continue
        if not plan.case.required:
            optional_upper += 1
        if gate is None:
            schedule = plan.schedule_minimum
            if plan.case.required:
                if schedule is None:
                    return None
                total += schedule
            else:
                deferred = penalty(plan.case.penalty_if_deferred)
                total += min(schedule, deferred) if schedule is not None else deferred
            continue
        total += penalty(plan.case.penalty_if_scheduled)
        for step, domain in enumerate((plan.starts, *plan.choices), 1):
            budget.charge()
            selected = values.get((index, step))
            if selected is not None:
                total += penalty(domain[selected].penalty)
            elif plan.minimum_costs[step - 1] is None:
                return None
            else:
                total += plan.minimum_costs[step - 1]
    return (total,) if mode == "all_required_then_min_declared_cost" else (-optional_upper, total)


def objective_from_key(key, mode):
    if key is None:
        return None
    return {"optional_scheduled_count": None if mode == "all_required_then_min_declared_cost" else -key[0], "penalty_points": str(key[-1])}


def candidate_key(candidate, mode, optimistic=False):
    cost = candidate.penalty_lower_bound if optimistic else candidate.exact_penalty_points
    if cost is None:
        return None
    return (int(cost),) if mode == "all_required_then_min_declared_cost" else (-candidate.optional_scheduled_count, int(cost))


def decode_assignments(plans, path, budget, complete_only=True):
    values = path_values(path, budget)
    assignments, deferred = [], []
    for index, plan in enumerate(plans):
        budget.charge()
        gate = values.get((index, 0))
        if gate is None:
            continue
        if gate == 1:
            deferred.append(plan.case.case_id)
            continue
        if any((index, step) not in values for step in range(1, len(plan.demands) + 2)):
            if complete_only:
                continue
            raise ValueError("Incomplete factor assignment")
        start = plan.starts[values[(index, 1)]]
        roles, equipment = [], []
        room_id = None
        for offset, (demand, domain) in enumerate(zip(plan.demands, plan.choices, strict=True), 2):
            budget.charge()
            selected = domain[values[(index, offset)]]
            if offset == 2:
                room_id = selected.resource_id
            elif hasattr(demand, "role_kind"):
                roles.append({"slot_id": demand.slot_id, "person_id": selected.resource_id, "duty_id": selected.duty_binding.duty_id})
            else:
                equipment.append({"slot_id": demand.slot_id, "equipment_id": selected.resource_id})
        assignments.append(Assignment.model_validate({"case_id": plan.case.case_id, "start_at": start.start_at, "room_id": room_id, "roles": roles, "equipment": equipment}))
    return assignments, deferred


def domain_size(plan, step):
    if step == 0:
        return 1 if plan.case.required else 2
    return len(plan.starts) if step == 1 else len(plan.choices[step - 2])


def next_position(plans, node, selected):
    if node.step == 0 and selected == 1 or node.step == len(plans[node.case_index].demands) + 1:
        return node.case_index + 1, 0
    return node.case_index, node.step + 1


def heap_key(node):
    return node.bound, -(node.path.depth if node.path else 0), node.cursor != 0, node.serial


def frontier_hash(heap, mode):
    digest = hashlib.sha256(b"[")
    for index, (_, node) in enumerate(sorted(heap, key=lambda item: item[0])):
        if index:
            digest.update(b",")
        digest.update(
            canonical_json(
                {
                    "path_digest": node.path.digest if node.path else hash_content([]),
                    "case_index": node.case_index,
                    "step": node.step,
                    "next_choice_index": node.cursor,
                    "bound": objective_from_key(node.bound, mode),
                    "serial": node.serial,
                }
            ).encode()
        )
    digest.update(b"]")
    return digest.hexdigest()


def solve_graph(source, graph, limits=None):
    """Internal deterministic solver. Test limits are never exposed on the wire.

    Returns typed SearchProof/candidate plus internal exact lex keys. Limits use
    operation_limit, node_limit, frontier_limit; defaults are fixed in RECIPE.
    """
    if graph not in ("definite", "optimistic"):
        raise ValueError("Unknown constraint graph")
    source = source if isinstance(source, SurgerySource) else SurgerySource.model_validate(source)
    limits = {"operation_limit": OPERATION_LIMIT, "node_limit": NODE_LIMIT, "frontier_limit": FRONTIER_LIMIT} if limits is None else dict(limits)
    if set(limits) != {"operation_limit", "node_limit", "frontier_limit"} or any(type(value) is not int or value < 1 for value in limits.values()):
        raise ValueError("Strict positive internal search limits required")
    budget = Budget(limit=limits["operation_limit"])
    mode = source.objective_mode
    heap = []
    incumbent = best_feasible = provisional = None
    incumbent_key = None
    best_primary = None
    expanded = 0
    serial = 1
    complete_domain = False
    termination = "exhausted"
    # Even a preprocessing interruption retains an admissible whole-root bound.
    root_bound = (0,) if mode == "all_required_then_min_declared_cost" else (-sum(not x.required for x in source.cases), 0)
    root = SearchNode(None, 0, 0, 0, root_bound, 0)
    heapq.heappush(heap, (heap_key(root), root))
    try:
        charge_source(source, budget)
        complete_domain = source_scope_checks(source, Checks(budget, retain=False))
        plans = prepare_plans(source, budget)
        bound = lower_bound(plans, None, mode, budget)
        if bound is None:
            heap.clear()
        else:
            root.bound = bound
            heap[0] = (heap_key(root), root)
        while heap:
            if expanded >= limits["node_limit"]:
                termination = "node_limit"
                break
            _, node = heapq.heappop(heap)
            try:
                budget.charge()
                if incumbent_key is not None and node.bound >= incumbent_key:
                    expanded += 1
                    continue
                if node.case_index == len(plans):
                    assignments, deferred = decode_assignments(plans, node.path, budget)
                    candidate = check_candidate(source, assignments, deferred, budget=budget, graph=graph)
                    if candidate.violations:
                        expanded += 1
                        continue
                    if graph == "optimistic":
                        key = candidate_key(candidate, mode, optimistic=True)
                        if incumbent_key is None or key < incumbent_key:
                            incumbent, incumbent_key = candidate, key
                    elif candidate.status == "feasible_under_declared_scope":
                        best_primary = candidate.optional_scheduled_count if best_primary is None else max(best_primary, candidate.optional_scheduled_count)
                        key = candidate_key(candidate, mode)
                        if key is not None and (incumbent_key is None or key < incumbent_key):
                            incumbent, incumbent_key = candidate, key
                        if best_feasible is None or (-candidate.optional_scheduled_count, int(candidate.penalty_lower_bound), candidate.candidate_digest) < (
                            -best_feasible.optional_scheduled_count,
                            int(best_feasible.penalty_lower_bound),
                            best_feasible.candidate_digest,
                        ):
                            best_feasible = candidate
                    elif provisional is None or candidate_key(candidate, mode, optimistic=True) < candidate_key(provisional, mode, optimistic=True):
                        provisional = candidate
                    expanded += 1
                    continue
                plan = plans[node.case_index]
                size = domain_size(plan, node.step)
                if node.cursor >= size:
                    expanded += 1
                    continue
                selected = node.cursor
                depth = node.path.depth + 1 if node.path else 1
                path = PathNode(
                    node.path,
                    node.case_index,
                    node.step,
                    selected,
                    depth,
                    hash_content({"parent": node.path.digest if node.path else hash_content([]), "case_index": node.case_index, "step": node.step, "choice": selected}),
                )
                child_bound = lower_bound(plans, path, mode, budget)
                children = []
                if child_bound is not None and (incumbent_key is None or child_bound < incumbent_key):
                    case_index, step = next_position(plans, node, selected)
                    admissible = True
                    if case_index > node.case_index and not (node.step == 0 and selected == 1):
                        assignments, _ = decode_assignments(plans, path, budget)
                        admissible = check_partial_assignments(source, assignments, budget, new_case_id=plan.case.case_id)
                    if admissible:
                        children.append(SearchNode(path, case_index, step, 0, child_bound, serial))
                        serial += 1
                if selected + 1 < size:
                    children.append(SearchNode(node.path, node.case_index, node.step, selected + 1, node.bound, serial))
                    serial += 1
                if len(heap) + len(children) > limits["frontier_limit"]:
                    raise BudgetLimitError("frontier_limit")
                # Atomic coverage: no parent is closed before all disjoint children exist.
                for child in children:
                    heapq.heappush(heap, (heap_key(child), child))
                expanded += 1
            except BudgetLimitError:
                heapq.heappush(heap, (heap_key(node), node))
                raise
    except BudgetLimitError as exc:
        termination = exc.reason
    bound_key = min([node.bound for _, node in heap] + ([incumbent_key] if incumbent_key is not None else []), default=None)
    if incumbent_key is not None and bound_key == incumbent_key:
        termination = "bound_closed"
    if not complete_domain:
        termination = "input_unknown"
    proof = SearchProof.model_validate(
        {
            "graph": graph,
            "termination": termination,
            "expanded_nodes": expanded,
            "primitive_operations": budget.operations,
            "frontier_nodes": len(heap),
            "incumbent_objective": objective_from_key(incumbent_key, mode),
            "optimistic_bound": objective_from_key(bound_key, mode),
            "frontier_digest": frontier_hash(heap, mode),
            "incumbent_assignment_digest": incumbent.candidate_digest if incumbent is not None else None,
            "work_limits": limits,
        }
    )
    return {
        "proof": proof,
        "candidate": incumbent or best_feasible or provisional,
        "incumbent_key": incumbent_key,
        "bound_key": bound_key,
        "best_feasible_optional_count": best_primary,
        "domain_complete": complete_domain,
    }


def validate_runtime(runtime):
    values = SurgeryRuntime.model_validate(runtime.model_dump() if isinstance(runtime, SurgeryRuntime) else runtime).model_dump()
    if values["core_sha256"] != implementation_hashes() or values["recipe_digest"] != recipe_digest() or values["input_policy_digest"] != input_policy_digest():
        raise ValueError("Surgery runtime implementation or fixed recipe/input policy differs")
    if any(not re.fullmatch(r"\d+\.\d+\.\d+(?:[A-Za-z0-9.+_-]{0,50})?", value) for value in [values["python_version"], *values["engine_versions"].values()]):
        raise ValueError("Complete independent runtime package identity is required")
    identity = {key: value for key, value in values.items() if key not in {"runtime_digest", "model_version"}}
    digest = hash_content(identity)
    if values["runtime_digest"] != digest or values["model_version"] != "surgery:" + digest:
        raise ValueError("Actual runtime metadata and registered model identity differ")
    return values


def compute_surgery(source, instructions_digest, runtime):
    source = SurgerySource.model_validate(source.model_dump() if isinstance(source, SurgerySource) else source)
    runtime = validate_runtime(runtime)
    definite = solve_graph(source, "definite")
    optimistic = solve_graph(source, "optimistic")
    closed = definite["domain_complete"] and optimistic["domain_complete"]
    solution = definite["candidate"]
    feasible = solution is not None and solution.status == "feasible_under_declared_scope"
    exact = definite["incumbent_key"]
    bound = optimistic["bound_key"] if closed else None
    if not closed:
        status = "input_unknown"
    elif exact is not None and bound == exact:
        status = "optimal_proven"
    elif optimistic["proof"].termination == "exhausted" and optimistic["incumbent_key"] is None and optimistic["proof"].frontier_nodes == 0:
        status = "infeasible_proven"
    else:
        status = "feasible_not_proven" if feasible else "feasibility_unknown"
    optional_gap = None
    penalty_gap = None
    if bound is not None:
        if exact is not None and bound > exact:
            raise ValueError("Optimistic bound excludes a known feasible exact incumbent")
        if source.objective_mode == "max_optional_scheduled_then_min_declared_cost":
            if definite["best_feasible_optional_count"] is not None:
                optional_gap = -bound[0] - definite["best_feasible_optional_count"]
                if optional_gap < 0:
                    raise ValueError("Optimistic primary bound excludes a known feasible candidate")
            if optional_gap == 0 and exact is not None and exact[0] == bound[0]:
                penalty_gap = str(exact[-1] - bound[-1])
        elif exact is not None:
            penalty_gap = str(exact[-1] - bound[-1])
    input_checks = Checks(Budget())
    source_scope_checks(source, input_checks)
    result = SurgeryAnalysis.model_validate(
        {
            "schema_version": "surgery_analysis_v1",
            "source_binding": {
                "scenario_id": source.scenario_id,
                "source_id": source.source_id,
                "content_hash": source.content_hash,
                "governance_hash": source.governance_hash,
                "projection_hash": hash_content(source.model_dump()),
                "collection_digest": source.collection.collection_digest,
            },
            "instructions_digest": instructions_digest,
            "objective_mode": source.objective_mode,
            "scope_status": "closed_declared_problem" if closed else "incomplete_declared_problem",
            "solve_status": status,
            "solution": solution.model_dump() if solution else None,
            "feasible_incumbent_objective": objective_from_key(exact, source.objective_mode),
            "best_feasible_optional_count": definite["best_feasible_optional_count"],
            "optimistic_objective_bound": objective_from_key(bound, source.objective_mode),
            "optional_count_gap": optional_gap,
            "penalty_gap_when_count_bound_closed": penalty_gap,
            "definite_search": definite["proof"].model_dump(),
            "optimistic_search": optimistic["proof"].model_dump(),
            "input_issues": input_checks.unknowns,
            "local_runtime": runtime,
            "forecast_or_clinical_guarantee": "not_provided",
            "automatic_booking": False,
        }
    )
    if len(canonical_json(result.model_dump()).encode()) > MAX_BYTES:
        raise ValueError("Complete native surgery result exceeds UTF8 capacity; no truncation")
    return result


def validate_analysis_binding(analysis, source, instructions_digest, model_version):
    analysis = SurgeryAnalysis.model_validate(analysis.model_dump() if isinstance(analysis, SurgeryAnalysis) else analysis)
    if analysis.local_runtime.model_version != model_version:
        raise ValueError("Requested model differs from actual surgery runtime")
    expected = compute_surgery(source, instructions_digest, analysis.local_runtime)
    if analysis.model_dump() != expected.model_dump():
        raise ValueError("Entire source, assignments, constraints, search frontier, bounds and fixed statuses do not recompute")
    return analysis


def generation_result_for_analysis(analysis):
    analysis = SurgeryAnalysis.model_validate(analysis.model_dump() if isinstance(analysis, SurgeryAnalysis) else analysis)
    descriptions = {
        "optimal_proven": "已在完整声明域内证明所选目标的最优候选。",
        "feasible_not_proven": "已核对可行候选，尚未证明所选目标最优。",
        "infeasible_proven": "在完整声明域和已知硬约束下不存在可行排程。",
        "feasibility_unknown": "当前资料或搜索界不足以确认可行排程。",
        "input_unknown": "候选域完整性未确认，不能证明全域最优或不可行。",
    }
    return {
        "summary": descriptions[analysis.solve_status],
        "sections": [
            {
                "title": "声明阶段与共享资源",
                "content": "按明确开始域、患者在场、房间、自然人岗位、具体设备、审核班次与全部适用政策核对；数值、松弛、预算及证明界见结构化结果。",
                "source_ids": [analysis.source_binding.source_id],
            }
        ],
        "warnings": ["本结果仅为声明事实和时长条件下的候选；不提供临床时长保证，不自动预约或改变临床状态。"],
        "missing_data": ["实际临床和运营效果验证未提供。"] + (["存在未确认约束或未闭合搜索界，须人工核对。"] if analysis.solve_status not in ("optimal_proven", "infeasible_proven") else []),
    }
