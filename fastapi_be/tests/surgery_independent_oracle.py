"""Independent exhaustive tiny-domain oracle, never a native-checker wrapper.

Only fully known synthetic facts are accepted here. Unknown-product tests compare
native bounds against separately completed known Sources, rather than copying
the native optimistic relaxation. All intervals/costs are artificial examples.
"""

import copy
import itertools
from datetime import UTC, datetime, timedelta

from tests.test_ai_surgery_contract import DUTY, END, EQUIPMENT, H, PERSON, ROOM, START, accounting, amount, demand, resource, source_dict, uid

EPOCH = datetime(2026, 10, 21, 8, tzinfo=UTC)
MODES = ("all_required_then_min_declared_cost", "max_optional_scheduled_then_min_declared_cost")


def clock(microseconds):
    return (EPOCH + timedelta(microseconds=microseconds)).isoformat(timespec="microseconds").replace("+00:00", "Z")


def micros(value):
    delta = datetime.fromisoformat(value.replace("Z", "+00:00")) - EPOCH
    return delta.days * 86400000000 + delta.seconds * 1000000 + delta.microseconds


def union(intervals):
    output = []
    for start, end in sorted(intervals):
        assert start <= end
        if start == end:
            continue
        if output and start <= output[-1][1]:
            output[-1] = output[-1][0], max(output[-1][1], end)
        else:
            output.append((start, end))
    return output


def overlap(left, right):
    return left[0] < right[1] and right[0] < left[1]


def span(intervals):
    return sum(end - start for start, end in union(intervals))


def cut(intervals, removed):
    result = union(intervals)
    for low, high in removed:
        next_result = []
        for start, end in result:
            if end <= low or high <= start:
                next_result.append((start, end))
            else:
                if start < low:
                    next_result.append((start, low))
                if high < end:
                    next_result.append((high, end))
        result = next_result
    return result


def literal(value):
    assert value["absent_reason"] is None and value["value"] is not None, "Oracle accepts known literals only"
    return int(value["value"])


def choice(resource_id, duty_id=None, cost=0):
    return {"resource_id": resource_id, "penalty": amount(str(cost)), "duty_binding": None if duty_id is None else {"duty_id": duty_id, "status": "verified", "basis_hash": H}}


def tiny_source(count=1, mode=MODES[0]):
    body = source_dict()
    body["objective_mode"] = mode
    for rid, kind in ((uid(110), "room"), (uid(111), "person"), (uid(112), "equipment")):
        body["resources"].append(resource(rid, kind))
    body["duties"].append({"duty_id": uid(113), "person_id": uid(111), "start_at": START, "end_at": END, "accounting": accounting(), "ref_ids": [uid(7)], "basis_hash": H})
    template = copy.deepcopy(body["cases"][0])
    body["cases"] = []
    for index in range(count):
        case = copy.deepcopy(template)
        case.update(case_id=uid(200 + index), patient_conflict_token=uid(300 + index))
        case["starts"] = [{"start_at": clock(3 * index), "penalty": amount()}]
        case["timing"]["segments"][0]["end_offset_us"] = amount("2")
        body["cases"].append(case)
    return body


def options(case):
    """Enumerate literal factors, including optional skip; no native imports."""
    demands = [case["room"], *case["roles"], *case["equipment"]]
    if not case["required"]:
        yield None
    for start in case["starts"]:
        for selected in itertools.product(*(item["choices"] for item in demands)):
            yield {"case": case, "start": start, "choices": selected}


def occupation(case, group, start):
    segments = {item["segment_id"]: item for item in case["timing"]["segments"]}
    intervals = []
    for key in group["segment_ids"]:
        item = segments[key]
        low, high = literal(item["start_offset_us"]), literal(item["end_offset_us"])
        if high < low:
            return None
        intervals.append((start + low, start + high))
    nonempty = union(intervals)
    if group["occupation_mode"] == "envelope" and nonempty:
        return [(nonempty[0][0], nonempty[-1][1])]
    return nonempty


def policy_limit(item):
    if item["value"] is None:
        assert item["absent_reason"] == "not_applicable"
        return None
    return int(item["value"]) * (60000000 if item["unit"] == "min" else 1)


def objective(mode, optional, penalty):
    return (penalty,) if mode == MODES[0] else (-optional, penalty)


def evaluate(body, selected):
    """Independent concrete checker for the deliberately small fixture subset.

    Supports segmented/envelope patient and concrete resource occupancy, explicit
    availability/busy, capability validity, duty membership, sequence pairs,
    duty/break-work union, rolling/fixed limits and explicit-duty rest. Does not
    classify unknown facts; tests concretize those before calling this oracle.
    """
    resources = {r["resource_id"]: r for r in body["resources"]}
    duties = {d["duty_id"]: d for d in body["duties"]}
    used, patients, counted, penalty, optional = [], [], {}, 0, 0
    for case, item in zip(body["cases"], selected, strict=True):
        if item is None:
            if case["required"]:
                return None
            penalty += literal(case["penalty_if_deferred"])
            continue
        optional += int(not case["required"])
        anchor = micros(item["start"]["start_at"])
        penalty += literal(case["penalty_if_scheduled"]) + literal(item["start"]["penalty"])
        patient = occupation(case, case["patient_presence"], anchor)
        if patient is None:
            return None
        patients.extend((case["patient_conflict_token"], case["case_id"], interval) for interval in patient)
        demands = [case["room"], *case["roles"], *case["equipment"]]
        for index, (req, selected_resource) in enumerate(zip(demands, item["choices"], strict=True)):
            intervals = occupation(case, req["occupation"], anchor)
            if intervals is None or index == 0 and not intervals:
                return None
            rid = selected_resource["resource_id"]
            res = resources[rid]
            penalty += literal(selected_resource["penalty"])
            for interval in intervals:
                if case["release"]["kind"] == "known" and interval[0] < micros(case["release"]["at"]):
                    return None
                if case["deadline"]["kind"] == "known" and interval[1] > micros(case["deadline"]["at"]):
                    return None
                available = union((micros(a["start_at"]), micros(a["end_at"])) for a in res["availability"] if a["state"] == "available")
                if not any(a <= interval[0] and interval[1] <= b for a, b in available):
                    return None
                if any(a["state"] == "unavailable" and overlap(interval, (micros(a["start_at"]), micros(a["end_at"]))) for a in res["availability"]):
                    return None
                for capability in req["capability_hashes"]:
                    if not any(c["status"] == "verified" and capability in c["capability_hashes"] and micros(c["valid_from_at"]) <= interval[0] and (c["valid_until"]["kind"] == "not_applicable" or c["valid_until"]["kind"] == "known" and interval[1] <= micros(c["valid_until"]["at"])) for c in res["capability_facts"]):
                        return None
                if res["kind"] == "person":
                    binding = selected_resource["duty_binding"]
                    assert binding["status"] == "verified"
                    duty = duties[binding["duty_id"]]
                    if not micros(duty["start_at"]) <= interval[0] <= interval[1] <= micros(duty["end_at"]):
                        return None
                    if req["occupation"]["accounting"]["counted_as_work"]:
                        if any(not br["counted_as_work"] and overlap(interval, (micros(br["start_at"]), micros(br["end_at"]))) for br in duty["accounting"]["breaks"]):
                            return None
                        counted.setdefault(rid, []).append(interval)
                used.append((rid, case["case_id"], req["slot_id"], interval, req["occupation"]["transition_class_hash"]))
    # Same demand stages are already unioned; different demands never cancel.
    for a, b in itertools.combinations(used, 2):
        if a[0] == b[0] and overlap(a[3], b[3]):
            return None
    for a, b in itertools.combinations(patients, 2):
        if a[0] == b[0] and a[1] != b[1] and overlap(a[2], b[2]):
            return None
    for busy in body["busy_intervals"]:
        if busy["busy_status"] == "cancelled":
            continue
        assert busy["end_at"] is not None and busy["busy_status"] in {"committed", "completed"}
        interval = micros(busy["start_at"]), micros(busy["end_at"])
        target = busy["target"]
        if target["kind"] == "resource":
            if any(x[0] == target["resource_id"] and overlap(x[3], interval) for x in used):
                return None
            if busy["accounting"]["counted_as_work"]:
                counted.setdefault(target["resource_id"], []).append(interval)
        elif any(x[0] == target["patient_conflict_token"] and overlap(x[2], interval) for x in patients):
            return None
    # Tests using transitions have one continuous room occupation per case.
    for policy in body["transition_policies"]:
        pairs = {(p["from_class_hash"], p["to_class_hash"]): p for p in policy["pairs"]}
        for rid in policy["resource_ids"]:
            timeline = sorted((x for x in used if x[0] == rid), key=lambda x: (x[3], x[1], x[2]))
            for a, b in zip(timeline, timeline[1:]):
                if a[1] == b[1]:
                    continue
                pair = pairs[a[4], b[4]]
                if b[3][0] - a[3][1] < literal(pair["minimum_gap_us"]):
                    return None
                penalty += literal(pair["penalty"])
    # Union complete explicit baseline duty work with selected case work.
    for duty in body["duties"]:
        ac = duty["accounting"]
        if ac["counted_as_work"]:
            baseline = [(micros(duty["start_at"]), micros(duty["end_at"]))]
            baseline = cut(baseline, [(micros(br["start_at"]), micros(br["end_at"])) for br in ac["breaks"] if not br["counted_as_work"]])
            counted.setdefault(duty["person_id"], []).extend(baseline)
    for policy in body["work_policies"]:
        for rid in policy["person_ids"]:
            work = union(counted.get(rid, []))
            person_duties = sorted((micros(d["start_at"]), micros(d["end_at"])) for d in body["duties"] if d["person_id"] == rid)
            maximum = policy_limit(policy["max_single_presence"])
            if maximum is not None and any(b - a > maximum for a, b in person_duties):
                return None
            minimum = policy_limit(policy["minimum_rest"])
            if minimum is not None and any(b[0] - a[1] < minimum for a, b in zip(person_duties, person_duties[1:])):
                return None
            for name, width in (("max_work_rolling_24h", 86400000000), ("max_work_rolling_7d", 604800000000)):
                limit = policy_limit(policy[name])
                if limit is not None:
                    edges = {t for a, b in work for t in (a, b, a - width, b - width)}
                    if max((sum(max(0, min(b, t + width) - max(a, t)) for a, b in work) for t in edges), default=0) > limit:
                        return None
            for window in policy["fixed_windows"]:
                low, high = micros(window["start_at"]), micros(window["end_at"])
                actual = sum(max(0, min(b, high) - max(a, low)) for a, b in work)
                lower, upper = policy_limit(window["minimum_work"]), policy_limit(window["maximum_work"])
                if lower is not None and actual < lower or upper is not None and actual > upper:
                    return None
    return objective(body["objective_mode"], optional, penalty)


def exhaustive(body):
    best, feasible, leaves = None, 0, 0
    for selected in itertools.product(*(list(options(case)) for case in body["cases"])):
        leaves += 1
        value = evaluate(body, selected)
        if value is not None:
            feasible += 1
            if best is None or value < best:
                best = value
    return {"best": best, "feasible": feasible, "leaves": leaves}


def matches(assignment, option):
    case = option["case"]
    selected = option["choices"]
    return assignment["start_at"] == option["start"]["start_at"] and assignment["room_id"] == selected[0]["resource_id"] and assignment["roles"] == [
        {"slot_id": req["slot_id"], "person_id": c["resource_id"], "duty_id": c["duty_binding"]["duty_id"]}
        for req, c in zip(case["roles"], selected[1:1 + len(case["roles"])], strict=True)
    ] and assignment["equipment"] == [{"slot_id": req["slot_id"], "equipment_id": c["resource_id"]} for req, c in zip(case["equipment"], selected[1 + len(case["roles"]):], strict=True)]


def objective_of_native_candidate(body, candidate):
    assigned = {a["case_id"]: a for a in candidate["assignments"]}
    assert len(assigned) == len(candidate["assignments"])
    selected = []
    for case in body["cases"]:
        if case["case_id"] not in assigned:
            assert not case["required"] and case["case_id"] in candidate["deferred_case_ids"]
            selected.append(None)
            continue
        choices = [item for item in options(case) if item is not None and matches(assigned[case["case_id"]], item)]
        assert len(choices) == 1, "Native assignment must be a literal declared-domain member"
        selected.append(choices[0])
    assert set(assigned) <= {c["case_id"] for c in body["cases"]}
    return evaluate(body, selected)


def transition_source(mode=MODES[0], gap=0, direct_cost=0, optional_middle=False, alternate_room=False):
    body = tiny_source(3, mode)
    classes = [uid(400 + i).replace('-', '') * 2 for i in range(3)]
    for case, start, label in zip(body["cases"], (0, 4, 2), classes, strict=True):
        case["starts"] = [{"start_at": clock(start), "penalty": amount()}]
        case["timing"]["segments"][0]["end_offset_us"] = amount("1")
        case["roles"], case["equipment"] = [], []
        case["room"]["occupation"].update(transition_class_hash=label, transition_class_absent_reason=None)
    if optional_middle:
        body["cases"][2].update(required=False, penalty_if_deferred=amount())
    if alternate_room:
        for case in body["cases"]:
            case["room"]["choices"] = [choice(uid(110))]
        body["cases"][0]["room"]["choices"].insert(0, choice(ROOM, cost=10))
    transition_room = uid(110) if alternate_room else ROOM
    next(r for r in body["resources"] if r["resource_id"] == transition_room)["transition_policy_review"]["status"] = "reviewed_policies"
    pairs = []
    for left, right in itertools.product(classes, repeat=2):
        is_direct = (left, right) == (classes[0], classes[1])
        cost = direct_cost if is_direct else 1 if (left, right) in {(classes[0], classes[2]), (classes[2], classes[1])} else 0
        pairs.append({"from_class_hash": left, "to_class_hash": right, "minimum_gap_us": amount(str(gap if is_direct else 0)), "penalty": amount(str(cost)), "basis_hash": H})
    body["transition_policies"] = [{"policy_id": uid(450), "ref_ids": [uid(7)], "resource_ids": [transition_room], "effective_from_at": START, "effective_until": {"kind": "known", "at": END}, "pairs": pairs, "pair_coverage": "attested_complete", "basis_hash": H}]
    return body


def work_policy(body, **limits):
    unused = {"value": None, "unit": "us", "absent_reason": "not_applicable"}
    result = {"policy_id": uid(500), "ref_ids": [uid(7)], "person_ids": [PERSON], "effective_from_at": START, "effective_until": {"kind": "known", "at": END}, "fixed_windows": [], "policy_reference_hash": H, "basis_hash": H}
    for key in ("max_single_presence", "max_work_rolling_24h", "max_work_rolling_7d", "minimum_rest"):
        result[key] = {"value": str(limits[key]), "unit": "us", "absent_reason": None} if key in limits else copy.deepcopy(unused)
    body["resources"][1]["work_policy_review"]["status"] = "reviewed_policies"
    body["work_policies"] = [result]
    return result
