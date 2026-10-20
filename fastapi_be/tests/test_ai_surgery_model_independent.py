"""Actual typed Sources checked against a separate tiny-domain exhaustive oracle.

Native tests are intentionally real tests (no skip/xfailed placeholders). Run
them once the independently owned four-core implementation exists. Pure oracle
self-tests can run before that. No hospital data or clinical defaults appear.
"""

import copy
import itertools
import json

import pytest
from pydantic import ValidationError

from app.ai.surgery_contract import MAX_BYTES, SurgerySource, hash_content
from tests.surgery_independent_oracle import (
    MODES,
    assignment_for_option,
    choice,
    clock,
    evaluate,
    exhaustive,
    fixed_busy_transition_source,
    mandatory_cohort_work_source,
    objective_of_native_candidate,
    options,
    tiny_source,
    transition_source,
    work_policy,
)
from tests.test_ai_surgery_contract import DUTY, EQUIPMENT, PERSON, ROOM, H, accounting, amount, uid


def typed(body):
    return SurgerySource.model_validate(body)


def native(body):
    from app.ai.surgery_config import runtime_descriptor, runtime_from_descriptor
    from app.ai.surgery_model import compute_surgery

    return compute_surgery(typed(body), H, runtime_from_descriptor(runtime_descriptor())).model_dump(mode="json")


def key(mode, value):
    return (int(value["penalty_points"]),) if mode == MODES[0] else (-value["optional_scheduled_count"], int(value["penalty_points"]))


def assert_exact_native(body):
    expected = exhaustive(body)
    value = native(body)
    if expected["best"] is None:
        assert value["solve_status"] == "infeasible_proven"
        assert value["solution"] is None
    else:
        assert value["solve_status"] == "optimal_proven"
        assert value["solution"]["status"] == "feasible_under_declared_scope"
        assert objective_of_native_candidate(body, value["solution"]) == expected["best"]
        assert key(body["objective_mode"], value["feasible_incumbent_objective"]) == expected["best"]
        assert key(body["objective_mode"], value["optimistic_objective_bound"]) == expected["best"]
        assert int(value["solution"]["exact_penalty_points"]) == expected["best"][-1]
    assert value["automatic_booking"] is False
    assert value["forecast_or_clinical_guarantee"] == "not_provided"
    return value


def lattice_source(seed, mode):
    """1..3 cases, exactly two literal starts/rooms/people/assets per case."""
    body = tiny_source(1 + seed % 3, mode)
    for index, case in enumerate(body["cases"]):
        case["required"] = index == 0 or bool((seed + index) % 2)
        case["penalty_if_deferred"] = None if case["required"] else amount(str(seed % 3))
        case["penalty_if_scheduled"] = amount(str((seed + index) % 2))
        case["starts"] = [{"start_at": clock(t), "penalty": amount(str((seed + t) % 3))} for t in (0, 3)]
        case["room"]["choices"] = [choice(ROOM, cost=seed % 2), choice(uid(110), cost=(seed + 1) % 2)]
        case["roles"][0]["choices"] = [choice(PERSON, DUTY, seed % 3), choice(uid(111), uid(113), (seed + 1) % 3)]
        case["equipment"][0]["choices"] = [choice(EQUIPMENT), choice(uid(112), cost=(seed + index) % 2)]
    return body


def test_oracle_self_actual_typed_microsecond_and_factor_domains():
    body = lattice_source(2, MODES[0])
    assert typed(body).model_dump(mode="json") == body
    result = exhaustive(body)
    assert result["leaves"] == 16 * 17 * 16
    assert result["feasible"] > 0
    assert result["best"] is not None


@pytest.mark.parametrize("mode", MODES)
def test_oracle_self_actual_typed_three_sequence_counterexamples(mode):
    gap = transition_source(mode, gap=10)
    cost = transition_source(mode, direct_cost=100, optional_middle=True, alternate_room=True)
    typed(gap)
    typed(cost)
    assert exhaustive(gap)["best"][-1] == 2
    assert exhaustive(cost)["best"][-1] == 2
    removed = copy.deepcopy(gap)
    removed["cases"].pop()
    assert exhaustive(removed)["best"] is None
    removed = copy.deepcopy(cost)
    removed["cases"].pop()
    assert exhaustive(removed)["best"][-1] == 10


@pytest.mark.parametrize("mode,seed", itertools.product(MODES, (0, 1)))
def test_actual_candidate_checker_matches_independent_every_tiny_leaf(mode, seed):
    from app.ai.surgery_model import check_candidate

    body = lattice_source(seed, mode)
    source = typed(body)
    for selected in itertools.product(*(list(options(case)) for case in body["cases"])):
        expected = evaluate(body, selected)
        assignments = [assignment_for_option(item) for item in selected if item is not None]
        deferred = [case["case_id"] for case, item in zip(body["cases"], selected, strict=True) if item is None]
        result = check_candidate(source, assignments, deferred).model_dump(mode="json")
        assert (result["status"] == "feasible_under_declared_scope") == (expected is not None)
        if expected is not None:
            assert int(result["exact_penalty_points"]) == expected[-1]
            assert objective_of_native_candidate(body, result) == expected


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("factory", (fixed_busy_transition_source, mandatory_cohort_work_source))
def test_actual_checker_cannot_escape_fixed_cohort_cost_or_minimum_by_deferring(mode, factory):
    from app.ai.surgery_model import check_candidate

    body = factory(mode)
    source = typed(body)
    assert exhaustive(body)["best"][-1] == (2 if factory == fixed_busy_transition_source else 9)
    for selected in itertools.product(*(list(options(case)) for case in body["cases"])):
        expected = evaluate(body, selected)
        result = check_candidate(
            source, [assignment_for_option(item) for item in selected if item is not None], [case["case_id"] for case, item in zip(body["cases"], selected, strict=True) if item is None]
        ).model_dump(mode="json")
        assert (result["status"] == "feasible_under_declared_scope") == (expected is not None), result
        if expected is not None:
            assert int(result["exact_penalty_points"]) == expected[-1], result


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("factory", (fixed_busy_transition_source, mandatory_cohort_work_source))
def test_native_fixed_cohort_transition_cost_and_work_minimum_survive_skip_and_reassignment(mode, factory):
    assert_exact_native(factory(mode))


@pytest.mark.parametrize("mode,seed", itertools.product(MODES, range(12)))
def test_native_two_objectives_match_independent_complete_lattice(mode, seed):
    assert_exact_native(lattice_source(seed, mode))


@pytest.mark.parametrize("mode", MODES)
def test_native_actual_typed_nonmonotone_sequence_gap_keeps_inserted_case(mode):
    assert_exact_native(transition_source(mode, gap=10))


@pytest.mark.parametrize("mode", MODES)
def test_native_actual_typed_nonmonotone_sequence_cost_keeps_optional_insertion(mode):
    assert_exact_native(transition_source(mode, direct_cost=100, optional_middle=True, alternate_room=True))


@pytest.mark.parametrize("mode,gap,direct_cost", itertools.product(MODES, (0, 10), (0, 100)))
def test_native_unknown_occupation_cannot_create_stricter_transition_graph(mode, gap, direct_cost):
    completed = transition_source(mode, gap=gap, direct_cost=direct_cost)
    expected = exhaustive(completed)
    assert expected["best"] is not None
    body = copy.deepcopy(completed)
    body["cases"][2]["timing"]["segments"][0]["end_offset_us"] = amount(None)
    typed(body)
    result = native(body)
    assert result["solve_status"] not in {"infeasible_proven", "optimal_proven"}
    assert key(mode, result["optimistic_objective_bound"]) <= expected["best"]
    assert result["solution"] is None or result["solution"]["status"] != "feasible_under_declared_scope"


@pytest.mark.parametrize("kind", ("roles", "equipment"))
def test_native_same_person_two_roles_and_same_asset_quantity_slots_not_unioned(kind):
    body = tiny_source()
    duplicate = copy.deepcopy(body["cases"][0][kind][0])
    duplicate["slot_id"] = "second_slot"
    if kind == "roles":
        duplicate["role_kind"] = "assistant"
    body["cases"][0][kind].append(duplicate)
    assert_exact_native(body)


def test_native_patient_presence_is_independent_of_room_and_staff():
    body = tiny_source(2)
    body["cases"][1]["patient_conflict_token"] = body["cases"][0]["patient_conflict_token"]
    body["cases"][0]["timing"]["segments"].append({"segment_id": "patient", "start_offset_us": amount(), "end_offset_us": amount("4"), "ref_ids": [uid(3)]})
    body["cases"][0]["patient_presence"]["segment_ids"] = ["patient"]
    assert_exact_native(body)


@pytest.mark.parametrize("envelope", (False, True))
def test_native_same_demand_phase_union_and_explicit_room_envelope(envelope):
    body = tiny_source(2)
    for case in body["cases"]:
        case["roles"], case["equipment"] = [], []
        case["timing"]["segments"][0]["end_offset_us"] = amount("1")
    first, second = body["cases"]
    first["timing"]["segments"].append({"segment_id": "tail", "start_offset_us": amount("3"), "end_offset_us": amount("4"), "ref_ids": [uid(3)]})
    first["room"]["occupation"].update(segment_ids=["operation", "tail"], occupation_mode="envelope" if envelope else "segments")
    second["starts"] = [{"start_at": clock(1), "penalty": amount()}]
    result = assert_exact_native(body)
    assert (result["solve_status"] == "infeasible_proven") == envelope


def test_native_explicit_same_duty_rest_and_no_work_doublecount():
    body = tiny_source(2)
    for index, case in enumerate(body["cases"]):
        case["starts"] = [{"start_at": clock(index * 7200000000), "penalty": amount()}]
        case["timing"]["segments"][0]["end_offset_us"] = amount("3600000000")
    body["duties"][0].update(start_at=clock(0), end_at=clock(28800000000))
    # Same one explicit eight-hour duty; case gap is NOT an inter-duty rest.
    work_policy(body, minimum_rest=10800000000, max_single_presence=28800000000, max_work_rolling_24h=28800000000, max_work_rolling_7d=28800000000)
    assert_exact_native(body)


def test_native_explicit_distinct_duty_rest_is_enforced():
    body = tiny_source()
    body["duties"][0].update(start_at=clock(0), end_at=clock(1))
    body["cases"][0]["timing"]["segments"][0]["end_offset_us"] = amount("1")
    extra = copy.deepcopy(body["duties"][0])
    extra.update(duty_id=uid(550), start_at=clock(2), end_at=clock(3))
    body["duties"].append(extra)
    work_policy(body, minimum_rest=2)
    assert_exact_native(body)


def test_native_minimum_work_failure_in_partial_prefix_can_be_repaired():
    body = tiny_source(2)
    body["duties"][0].update(start_at=clock(0), end_at=clock(10))
    body["duties"][0]["accounting"]["counted_as_work"] = False
    policy = work_policy(body)
    policy["fixed_windows"] = [
        {"start_at": clock(0), "end_at": clock(10), "minimum_work": {"value": "4", "unit": "us", "absent_reason": None}, "maximum_work": {"value": "4", "unit": "us", "absent_reason": None}}
    ]
    assert_exact_native(body)


@pytest.mark.parametrize("area", ("starts", "room", "cases", "resources"))
@pytest.mark.parametrize("state", ("unknown", "incomplete"))
def test_native_incomplete_underlying_domains_never_fake_global_proof(area, state):
    body = tiny_source()
    if area == "starts":
        body["cases"][0]["start_domain_status"] = state
    elif area == "room":
        body["cases"][0]["room"]["domain_status"] = state
    else:
        body["problem_coverage"][area]["status"] = state
    result = native(body)
    assert result["solve_status"] == "input_unknown"
    assert result["scope_status"] == "incomplete_declared_problem"


def test_native_unknown_cost_candidate_does_not_fabricate_exact_zero():
    body = tiny_source(mode=MODES[1])
    body["cases"][0].update(required=False, penalty_if_deferred=amount(None))
    body["cases"][0]["penalty_if_scheduled"] = amount(None)
    result = native(body)
    assert result["solve_status"] != "infeasible_proven"
    assert result["solution"] is not None and result["solution"]["status"] == "feasible_under_declared_scope"
    assert result["solution"]["exact_penalty_points"] is None
    assert result["feasible_incumbent_objective"] is None
    assert result["best_feasible_optional_count"] == 1
    assert result["penalty_gap_when_count_bound_closed"] is None


def test_native_empty_role_authorization_is_unknown_despite_verified_person_identity():
    body = tiny_source()
    assert body["resources"][1]["capability_facts"][0]["status"] == "verified"
    body["cases"][0]["roles"][0]["capability_hashes"] = []
    result = native(body)
    assert result["solve_status"] not in {"optimal_proven", "infeasible_proven"}
    assert result["solution"] is None or result["solution"]["status"] != "feasible_under_declared_scope"


def typed_capacity_bodies():
    narrow = tiny_source(256)
    wide = tiny_source(24)
    template = copy.deepcopy(wide["manifest"][0])
    for index in range(8192 - len(wide["manifest"])):
        wide["manifest"].append({**template, "fact_id": uid(1000 + index)})
    wide["collection"]["manifest_digest"] = hash_content(wide["manifest"])
    refs = sorted(ref["fact_id"] for ref in wide["manifest"])
    for case in wide["cases"]:
        case["ref_ids"] = refs.copy()
    return narrow, wide


def test_actual_typed_256_case_capacity_is_not_a_truncated_200_case_fixture():
    body, _ = typed_capacity_bodies()
    source = typed(body)
    assert len(source.cases) == 256
    assert source.model_dump(mode="json") == body
    assert len(json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()) < MAX_BYTES


def test_actual_typed_source_ref_expansion_rejects_whole_utf8_not_silent_subset():
    _, body = typed_capacity_bodies()
    assert len(body["manifest"]) == 8192
    assert all(len(case["ref_ids"]) == 8192 for case in body["cases"])
    size = len(json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode())
    assert size > MAX_BYTES
    with pytest.raises(ValidationError, match="Complete public source exceeds byte capacity"):
        typed(body)


@pytest.mark.parametrize("mode,graph", itertools.product(MODES, ("definite", "optimistic")))
@pytest.mark.parametrize(
    "limited",
    [{"operation_limit": n} for n in (1, 5, 20, 100, 300, 1000, 3000)] + [{"node_limit": n} for n in (1, 2, 3, 5, 10, 15)] + [{"frontier_limit": n} for n in (1, 2, 3)],
)
def test_actual_binary_cursor_budget_retains_complete_bound_and_unseen_siblings(mode, graph, limited):
    from app.ai.surgery_model import solve_graph

    body = tiny_source(mode=mode)
    case = body["cases"][0]
    case.update(required=False, penalty_if_deferred=amount("9"))
    case["room"]["choices"] = [choice(ROOM), choice(uid(110), cost=7)]
    body["busy_intervals"] = [
        {
            "interval_id": uid(650),
            "target": {"kind": "resource", "resource_id": ROOM},
            "ref_ids": [uid(6)],
            "start_at": clock(0),
            "end_at": clock(2),
            "end_absent_reason": None,
            "verified_until_at": None,
            "continuity_status": "confirmed",
            "busy_status": "committed",
            "transition_class_hash": None,
            "transition_class_absent_reason": "not_applicable",
            "accounting": accounting(),
            "basis_hash": H,
        }
    ]
    expected = exhaustive(body)
    assert expected["best"][-1] == 7
    limits = {"operation_limit": 20000000, "node_limit": 20000, "frontier_limit": 4096, **limited}
    result = solve_graph(typed(body), graph, limits)
    proof = result["proof"]
    assert result["bound_key"] is not None and tuple(result["bound_key"]) <= expected["best"]
    assert proof.primitive_operations <= limits["operation_limit"]
    assert proof.expanded_nodes <= limits["node_limit"]
    assert proof.frontier_nodes <= limits["frontier_limit"]
    if proof.termination not in {"exhausted", "bound_closed"}:
        assert proof.frontier_nodes > 0, "An unclassified parent/range must retain its unseen completion"
    if result["candidate"] is not None and result["candidate"].status == "feasible_under_declared_scope":
        candidate = result["candidate"].model_dump(mode="json")
        assert objective_of_native_candidate(body, candidate) is not None
    if proof.termination in {"exhausted", "bound_closed"}:
        assert result["incumbent_key"] is not None and tuple(result["incumbent_key"]) == expected["best"]
