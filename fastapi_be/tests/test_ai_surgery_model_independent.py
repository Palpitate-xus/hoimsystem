"""Actual typed Sources checked against a separate tiny-domain exhaustive oracle.

Native tests are intentionally real tests (no skip/xfailed placeholders). Run
them once the independently owned four-core implementation exists. Pure oracle
self-tests can run before that. No hospital data or clinical defaults appear.
"""

import copy
import itertools

import pytest

from app.ai.surgery_contract import SurgerySource
from tests.surgery_independent_oracle import MODES, assignment_for_option, choice, clock, evaluate, exhaustive, objective_of_native_candidate, options, tiny_source, transition_source, work_policy
from tests.test_ai_surgery_contract import DUTY, EQUIPMENT, PERSON, ROOM, H, amount, uid


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
