"""Independent integer-measure witnesses and actual typed workforce checks."""

import copy

import pytest

from app.ai.roster_contract import RosterSource
from app.ai.roster_model import DAY, MINUTE, WorkIntegral, check_candidate, clock_text, clock_us, merge_intervals, subtract_intervals
from tests.test_ai_roster_contract import complete_source, fact, identifier, limit


def checked(source, selected=None):
    return check_candidate(RosterSource.model_validate(source), [source["options"][0]["option_id"]] if selected is None else selected)


def test_union_integral_does_not_double_count_and_subtracts_only_actual_cuts():
    assert merge_intervals([(8, 12), (1, 5), (3, 9), (12, 13)]) == [(1, 13)]
    assert subtract_intervals([(1, 13)], [(0, 3), (5, 7), (6, 9), (11, 15)]) == [(3, 5), (9, 11)]
    integral = WorkIntegral([(8, 12), (1, 5), (3, 9)])
    assert integral.between(0, 20) == 11
    assert integral.between(4, 10) == 6
    assert integral.between(12, 20) == 0


@pytest.mark.parametrize("width", [1, 2, 5, 7, 24])
def test_continuous_rolling_maximum_matches_exhaustive_integer_endpoints(width):
    # Coordinates are exact microseconds.  These noncalendar break endpoints
    # exercise both endpoint and endpoint-minus-window extrema.
    intervals = [(2, 8), (11, 13), (15, 23), (26, 29)]
    integral = WorkIntegral(intervals)
    actual, witness, count = integral.maximum_rolling(width, -5, 31)
    oracle = [(integral.between(t, t + width), t) for t in range(-5, 32)]
    expected = max(value for value, _ in oracle)
    assert actual == expected
    assert integral.between(witness, witness + width) == expected
    assert count >= 2


def test_microsecond_clock_round_trip_never_uses_float_timestamp():
    original = "2069-12-31T23:59:59.123457Z"
    assert clock_text(clock_us(original)) == original
    assert clock_us("2026-10-20T08:00:00.000001Z") - clock_us("2026-10-20T08:00:00.000000Z") == 1


def test_original_complete_candidate_preserves_required_slots_and_headroom():
    result = checked(complete_source())
    assert result.status == "feasible_under_declared_scope"
    assert result.cost_points == 2
    assert result.total_planned_slots == 5
    assert result.session_allocations[0].capacity_headroom == 3
    assert result.session_allocations[0].staff_slot_capacity == 8
    assert any(c.kind == "rolling_24h" and c.actual_microseconds == 480 * MINUTE for c in result.checks)


def test_max_slots_objective_changes_planned_slots_not_original_required_target():
    source = complete_source()
    source["objective_mode"] = "max_slots_then_min_penalty"
    result = checked(source)
    assert result.total_planned_slots == 8
    assert result.session_allocations[0].required_slots == 5


def test_known_zero_capacity_and_cost_are_not_unknown():
    source = complete_source()
    source["sessions"][0]["required_slots"] = limit(0)
    source["sessions"][0]["facility_slot_ceiling"] = limit(0)
    source["options"][0].update(cost_points=limit(0), slot_capacity=limit(0))
    result = checked(source)
    assert result.status == "feasible_under_declared_scope"
    assert result.cost_points == result.total_planned_slots == 0


@pytest.mark.parametrize("field", ["cost_points", "slot_capacity"])
def test_unknown_assignment_fact_never_becomes_zero(field):
    source = complete_source()
    source["options"][0][field] = limit(None)
    result = checked(source)
    assert result.status == "unknown"
    assert getattr(result, "cost_points" if field == "cost_points" else "total_planned_slots") is None


def test_break_is_nonwork_but_does_not_release_presence_or_shorten_single_duty():
    source = complete_source()
    source["options"][0]["breaks"] = [{"start_at": "2026-10-20T12:00:00.000000Z", "end_at": "2026-10-20T13:00:00.000000Z", "counted_as_work": False, "counted_as_work_absent_reason": None}]
    source["work_policies"][0]["max_single_duty_presence_minutes"] = limit(479)
    source["work_policies"][0]["max_work_minutes_rolling_24h"] = limit(420)
    result = checked(source)
    assert result.status == "violated"
    assert any(c.kind == "single_duty_presence" and c.actual_microseconds == 480 * MINUTE and c.status == "violated" for c in result.checks)
    assert any(c.kind == "rolling_24h" and c.actual_microseconds == 420 * MINUTE and c.status == "satisfied" for c in result.checks)


def duty(source, start, end, number=30, status="committed"):
    return {
        "ref": fact("duty_interval", number),
        "start_at": start,
        "end_at": end,
        "breaks": [],
        "breaks_complete": True,
        "time_accounting_status": "verified",
        "commitment_status": status,
        "work_location": "external",
        "job_key_hash": None,
        "job_key_absent_reason": "unknown",
        "basis_hash": source["manifest_digest"],
    }


def test_existing_external_overlap_is_actual_hard_violation():
    source = complete_source()
    source["staff"][0]["duties"] = [duty(source, "2026-10-20T10:00:00.000000Z", "2026-10-20T11:00:00.000000Z")]
    result = checked(source)
    assert any(c.kind == "presence_overlap" and c.status == "violated" for c in result.checks)
    assert any(c.kind == "rolling_24h" and c.actual_microseconds == 480 * MINUTE for c in result.checks)


def test_prefix_and_suffix_rest_are_checked_across_planning_midnight():
    source = complete_source()
    source["staff"][0]["duties"] = [duty(source, "2026-10-19T18:00:00.000000Z", "2026-10-19T23:00:00.000000Z")]
    result = checked(source)
    assert any(c.kind == "minimum_rest" and c.status == "violated" and c.actual_microseconds == 540 * MINUTE for c in result.checks)
    coverage = next(c for c in result.checks if c.kind == "context_coverage")
    assert clock_us(coverage.witness_start_at) == clock_us(source["planning_start_at"]) - 7 * DAY
    assert clock_us(coverage.witness_end_at) == clock_us(source["planning_end_at"]) + 7 * DAY


def test_unknown_external_duty_does_not_prove_minimum_work_failure():
    source = complete_source()
    source["staff"][0]["duties"] = [duty(source, "2026-10-21T08:00:00.000000Z", "2026-10-21T16:00:00.000000Z", status="unknown")]
    source["work_policies"][0]["fixed_work_windows"] = [
        {"start_at": "2026-10-21T00:00:00.000000Z", "end_at": "2026-10-22T00:00:00.000000Z", "minimum_work_minutes": limit(480), "maximum_work_minutes": limit(600)}
    ]
    result = checked(source)
    assert result.status == "unknown"
    assert any(c.kind == "fixed_minimum_work" and c.status == "unknown" for c in result.checks)


def test_incomplete_inventory_cannot_make_empty_fixed_window_infeasible():
    source = complete_source()
    source["staff"][0]["all_locations_duty_coverage"]["status"] = "incomplete"
    source["work_policies"][0]["fixed_work_windows"] = [
        {"start_at": "2026-10-01T00:00:00.000000Z", "end_at": "2026-10-02T00:00:00.000000Z", "minimum_work_minutes": limit(480), "maximum_work_minutes": limit(None)}
    ]
    result = checked(source)
    assert result.status == "unknown"
    assert not any(c.kind == "fixed_minimum_work" and c.status == "violated" for c in result.checks)


def test_all_applicable_policies_conjoin_and_partial_validity_is_explicit_unknown():
    source = complete_source()
    stricter = copy.deepcopy(source["work_policies"][0])
    stricter["ref"] = fact("work_rule_policy", 31)
    stricter["max_work_minutes_rolling_24h"] = limit(479)
    source["work_policies"].append(stricter)
    assert checked(source).status == "violated"
    stricter["effective_from_at"] = "2026-10-21T00:00:00.000000Z"
    result = checked(source)
    assert result.status == "unknown"
    assert any(c.kind == "policy" and "policy_partial_validity_or_unknown_governance_not_silently_omitted" in c.reason_codes for c in result.checks)


def test_unavailable_subinterval_blocks_even_with_available_rest_of_session():
    source = complete_source()
    source["staff"][0]["availability"][0]["end_at"] = "2026-10-20T12:00:00.000000Z"
    other = copy.deepcopy(source["staff"][0]["availability"][0])
    other.update(ref=fact("availability", 32), start_at="2026-10-20T12:00:00.000000Z", end_at="2026-10-20T16:00:00.000000Z", availability="unavailable")
    source["staff"][0]["availability"].append(other)
    assert checked(source).status == "violated"


def test_conflicting_availability_does_not_choose_a_winner():
    source = complete_source()
    other = copy.deepcopy(source["staff"][0]["availability"][0])
    other.update(ref=fact("availability", 32), availability="unavailable")
    source["staff"][0]["availability"].append(other)
    assert checked(source).status == "unknown"


def test_empty_candidate_and_unknown_empty_cohort_are_not_auto_feasible():
    source = complete_source()
    assert checked(source, []).status == "violated"
    source.update(staff=[], sessions=[], options=[], work_policies=[], personnel_coverage="unknown")
    result = checked(source, [])
    assert result.status == "unknown"
    assert result.total_planned_slots == 0


def runtime():
    from app.ai.roster_contract import hash_content, input_policy_digest, recipe_digest

    digest = hash_content("synthetic independently identifiable runtime")
    return {
        "engine": "stdlib_roster_branch_and_bound",
        "model_version": "roster:" + digest,
        "runtime_digest": digest,
        "python_version": "synthetic-test-runtime",
        "engine_versions": {},
        "core_sha256": {},
        "recipe_digest": recipe_digest(),
        "input_policy_digest": input_policy_digest(),
        "timezone_database_digest": digest,
        "clinical_validation": "not_provided",
        "operational_validation": "not_provided",
        "prompt_handling": "provenance_only",
    }


def small_problem(seed, mode="meet_targets_min_penalty"):
    import random

    rng = random.Random(seed)
    source = complete_source()
    source["objective_mode"] = mode
    source["work_policies"][0]["minimum_rest_minutes"] = limit(0)
    source["work_policies"][0]["max_work_minutes_rolling_24h"] = limit(960)
    source["sessions"][0].update(minimum_staff=1, maximum_staff=2, required_slots=limit(rng.randrange(0, 8)))
    second = copy.deepcopy(source["sessions"][0])
    second.update(
        session_id=identifier(40),
        start_at="2026-10-20T12:00:00.000000Z" if seed % 2 else "2026-10-21T08:00:00.000000Z",
        end_at="2026-10-20T20:00:00.000000Z" if seed % 2 else "2026-10-21T16:00:00.000000Z",
        business_date="2026-10-20" if seed % 2 else "2026-10-21",
        required_slots=limit(rng.randrange(0, 8)),
    )
    source["sessions"].append(second)
    template = copy.deepcopy(source["staff"][0])
    for i in range(2):
        person = copy.deepcopy(template)
        person.update(staff_id=identifier(100 + i))
        person["qualifications"][0]["ref"] = fact("qualification", 200 + i)
        person["availability"][0]["ref"] = fact("availability", 210 + i)
        source["staff"].append(person)
    source["work_policies"][0]["applicable_staff_ids"] = [p["staff_id"] for p in source["staff"]]
    template = copy.deepcopy(source["options"][0])
    source["options"] = []
    for si, session in enumerate(source["sessions"]):
        for pi, person in enumerate(source["staff"]):
            option = copy.deepcopy(template)
            option.update(
                option_id=identifier(300 + si * 10 + pi),
                staff_id=person["staff_id"],
                session_id=session["session_id"],
                cost_points=limit(rng.randrange(0, 6)),
                slot_capacity=limit(rng.randrange(0, 7)),
            )
            source["options"].append(option)
    return source


def exhaustive_oracle(source):
    import itertools

    typed = RosterSource.model_validate(source)
    feasible = []
    for flags in itertools.product((False, True), repeat=len(typed.options)):
        candidate = check_candidate(typed, [o.option_id for o, selected in zip(typed.options, flags, strict=True) if selected])
        if candidate.status == "feasible_under_declared_scope":
            key = (candidate.cost_points,) if typed.objective_mode == "meet_targets_min_penalty" else (-candidate.total_planned_slots, candidate.cost_points)
            feasible.append(key)
    return min(feasible) if feasible else None


@pytest.mark.parametrize("mode", ["meet_targets_min_penalty", "max_slots_then_min_penalty"])
@pytest.mark.parametrize("seed", range(8))
def test_real_branch_and_bound_matches_exhaustive_independent_subset_oracle(seed, mode):
    from app.ai.roster_model import compute_roster

    source = small_problem(seed, mode)
    oracle = exhaustive_oracle(source)
    analysis = compute_roster(source, "a" * 64, runtime())
    if oracle is None:
        assert analysis.solve_status == "infeasible_proven"
        assert analysis.infeasibility_proven
        assert analysis.solution is None
    else:
        assert analysis.solve_status == "optimal_proven"
        assert analysis.optimality_proven
        value = analysis.feasible_incumbent_objective
        actual = (value.penalty_points,) if mode == "meet_targets_min_penalty" else (-value.planned_slots, value.penalty_points)
        assert actual == oracle
        assert analysis.solution.status == "feasible_under_declared_scope"
        assert analysis.penalty_gap_when_slot_bound_closed == 0
        assert analysis.planned_slots_gap == (0 if mode == "max_slots_then_min_penalty" else None)


@pytest.mark.parametrize("field", ["cost_points", "slot_capacity"])
def test_optimistic_unknown_domain_is_explicit_and_cannot_become_real_solution(field):
    from app.ai.roster_model import compute_roster

    source = complete_source()
    source["options"][0][field] = limit(None)
    analysis = compute_roster(source, "a" * 64, runtime())
    assert analysis.solve_status == "feasibility_unknown"
    assert analysis.solution is None
    assert analysis.optimistic_search.incumbent_objective is not None
    assert any("domain" in r for r in analysis.optimistic_search.relaxations)
    assert not analysis.optimality_proven


def test_unknown_requirement_scope_cannot_turn_empty_tree_into_all_department_optimum():
    from app.ai.roster_model import compute_roster

    source = complete_source()
    source.update(staff=[], sessions=[], options=[], work_policies=[], session_requirements_coverage="unknown")
    analysis = compute_roster(source, "a" * 64, runtime())
    assert analysis.solve_status == "input_unknown"
    assert analysis.solution is None
    assert not analysis.infeasibility_proven
    assert not analysis.optimality_proven


@pytest.mark.parametrize("stop", ["node_limit_per_graph", "operation_limit_per_graph", "frontier_limit_per_graph"])
def test_budget_exhaustion_preserves_unexpanded_frontier_bound(monkeypatch, stop):
    from app.ai.roster_contract import RECIPE
    from app.ai.roster_model import compute_roster

    monkeypatch.setitem(RECIPE["search"], stop, 1)
    source = small_problem(0)
    oracle = exhaustive_oracle(source)
    analysis = compute_roster(source, "a" * 64, runtime())
    assert analysis.optimistic_search.termination in ("node_limit", "operation_limit", "frontier_limit")
    assert analysis.optimistic_search.frontier_nodes >= 1
    if oracle is not None:
        assert analysis.optimistic_objective_bound.penalty_points <= oracle[0]
    assert not analysis.infeasibility_proven
    assert not analysis.optimality_proven


def test_complete_recomputation_rejects_numeric_and_proof_tampering():
    from app.ai.roster_model import compute_roster, validate_analysis_binding

    source = complete_source()
    analysis = compute_roster(source, "a" * 64, runtime())
    validate_analysis_binding(analysis, source, "a" * 64, runtime()["model_version"])
    for path, replacement in (("solve_status", "feasible_not_proven"), ("instructions_digest", "b" * 64), ("planned_slots_gap", 0)):
        changed = analysis.model_copy(update={path: replacement})
        with pytest.raises(ValueError):
            validate_analysis_binding(changed, source, "a" * 64, runtime()["model_version"])
    changed = analysis.model_copy(deep=True)
    changed.optimistic_search.expanded_nodes += 1
    with pytest.raises(ValueError):
        validate_analysis_binding(changed, source, "a" * 64, runtime()["model_version"])
