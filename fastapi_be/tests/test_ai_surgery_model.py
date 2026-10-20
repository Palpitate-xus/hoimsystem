"""Exact boundary/constraint tests; all literal durations are synthetic units."""

import copy

import pytest

from app.ai.surgery_config import runtime_descriptor, runtime_from_descriptor
from app.ai.surgery_contract import SurgerySource, hash_content
from app.ai.surgery_model import Budget, WorkIntegral, check_candidate, clock_us, compute_surgery, solve_graph, validate_analysis_binding
from tests.test_ai_surgery_contract import END, PERSON, START, H, amount, source_dict, uid


def native(body):
    return compute_surgery(SurgerySource.model_validate(body), H, runtime_from_descriptor(runtime_descriptor()))


def assignment(case):
    return {
        "case_id": case["case_id"],
        "start_at": case["starts"][0]["start_at"],
        "room_id": case["room"]["choices"][0]["resource_id"],
        "roles": [{"slot_id": role["slot_id"], "person_id": role["choices"][0]["resource_id"], "duty_id": role["choices"][0]["duty_binding"]["duty_id"]} for role in case["roles"]],
        "equipment": [{"slot_id": item["slot_id"], "equipment_id": item["choices"][0]["resource_id"]} for item in case["equipment"]],
    }


def simple_case(body, *, number=0, start="2026-10-21T08:00:00.000000Z", width="1", required=True):
    case = copy.deepcopy(body["cases"][0])
    case.update(
        case_id=uid(1000 + number),
        patient_conflict_token=uid(2000 + number),
        starts=[{"start_at": start, "penalty": amount()}],
        roles=[],
        equipment=[],
        required=required,
        penalty_if_deferred=None if required else amount(),
    )
    case["timing"]["segments"][0]["end_offset_us"]["value"] = width
    return case


def limit(value=None, absent="not_applicable", unit="us"):
    return {"value": value, "unit": unit, "absent_reason": None if value is not None else absent}


def policy(body, **patch):
    item = {
        "policy_id": uid(700),
        "ref_ids": [uid(7)],
        "person_ids": [PERSON],
        "effective_from_at": "2026-10-01T00:00:00.000000Z",
        "effective_until": {"kind": "not_applicable", "basis_hash": H},
        "max_single_presence": limit(),
        "max_work_rolling_24h": limit(),
        "max_work_rolling_7d": limit(),
        "minimum_rest": limit(),
        "fixed_windows": [],
        "policy_reference_hash": H,
        "basis_hash": H,
    }
    item.update(patch)
    body["work_policies"] = [item]
    body["resources"][1]["work_policy_review"]["status"] = "reviewed_policies"
    return item


def test_actual_complete_compute_recomputes_whole_analysis_and_preserves_declared_condition():
    body = source_dict()
    result = native(body)
    assert result.solve_status == "optimal_proven"
    assert result.solution.exact_penalty_points == "0"
    assert result.solution.duration_condition == "declared_upper_bounds"
    assert len(result.solution.occupancies) == 4
    assert result.source_binding.projection_hash == hash_content(body)
    assert validate_analysis_binding(result, body, H, result.local_runtime.model_version) == result


def test_costs_above_js_safe_integer_are_strings_and_exact():
    body = source_dict()
    body["cases"][0]["penalty_if_scheduled"] = amount("90071992547409931234567890123456789012")
    body["cases"][0]["starts"][0]["penalty"] = amount("90071992547409931234567890123456789012")
    result = native(body)
    assert result.feasible_incumbent_objective.penalty_points == "180143985094819862469135780246913578024"
    assert result.solve_status == "optimal_proven"


@pytest.mark.parametrize("mode,scheduled,cost", [("all_required_then_min_declared_cost", 0, "0"), ("max_optional_scheduled_then_min_declared_cost", 1, "5")])
def test_two_objectives_have_different_real_optima(mode, scheduled, cost):
    body = source_dict()
    case = simple_case(body, required=False)
    case["penalty_if_scheduled"] = amount("5")
    body.update(cases=[case], objective_mode=mode)
    result = native(body)
    assert result.solve_status == "optimal_proven"
    assert result.solution.scheduled_count == scheduled
    assert result.solution.exact_penalty_points == cost
    assert result.optional_count_gap == (0 if mode.startswith("max_") else None)


def test_unknown_soft_cost_can_have_known_feasible_solution_without_exact_objective():
    body = source_dict()
    body["cases"][0]["penalty_if_scheduled"] = amount(None)
    result = native(body)
    assert result.solve_status == "feasible_not_proven"
    assert result.solution.status == "feasible_under_declared_scope"
    assert result.solution.exact_penalty_points is None
    assert result.feasible_incumbent_objective is None
    assert result.optimistic_objective_bound.penalty_points == "0"


def test_known_zero_candidate_closes_bound_despite_unknown_cost_alternative():
    body = source_dict()
    body["cases"][0]["starts"].append({"start_at": "2026-10-21T09:00:00.000001Z", "penalty": amount(None)})
    assert native(body).solve_status == "optimal_proven"


@pytest.mark.parametrize("status,expected", [("attested_complete", "infeasible_proven"), ("unknown", "input_unknown"), ("incomplete", "input_unknown")])
def test_empty_start_domain_only_proves_infeasible_if_closed(status, expected):
    body = source_dict()
    body["cases"][0].update(starts=[], start_domain_status=status)
    result = native(body)
    assert result.solve_status == expected
    assert result.optimistic_objective_bound is None


def test_same_patient_has_independent_presence_even_when_room_stages_do_not_overlap():
    body = source_dict()
    left = simple_case(body, number=0, width="1")
    right = simple_case(body, number=1, start="2026-10-21T08:00:00.000002Z", width="1")
    right["patient_conflict_token"] = left["patient_conflict_token"]
    for case in (left, right):
        case["timing"]["segments"].append({"segment_id": "patient_preparation", "start_offset_us": {"value": "-2", "absent_reason": None}, "end_offset_us": amount("1"), "ref_ids": [uid(3)]})
        case["patient_presence"]["segment_ids"] = ["patient_preparation"]
    body["cases"] = [left, right]
    result = native(body)
    assert result.solve_status == "infeasible_proven"


def test_half_open_adjacent_room_intervals_and_zero_nonroom_phase_are_preserved():
    body = source_dict()
    body["cases"] = [simple_case(body, number=0), simple_case(body, number=1, start="2026-10-21T08:00:00.000001Z")]
    result = native(body)
    assert result.solve_status == "optimal_proven"
    assert result.solution.scheduled_count == 2


def test_same_person_cannot_cover_two_simultaneous_role_quantity_slots():
    body = source_dict()
    duplicate = copy.deepcopy(body["cases"][0]["roles"][0])
    duplicate.update(slot_id="anesthesia", role_kind="anesthesia")
    body["cases"][0]["roles"].append(duplicate)
    assert native(body).solve_status == "infeasible_proven"


def test_empty_person_capability_requirements_do_not_authorize_surgeon_by_identity():
    body = source_dict()
    body["cases"][0]["roles"][0]["capability_hashes"] = []
    result = native(body)
    assert result.solve_status == "feasibility_unknown"
    assert any(w.code == "qualification" and w.status == "unknown" for w in result.solution.unknowns)


def test_required_person_capability_must_cover_every_microsecond_of_occupation():
    body = source_dict()
    body["resources"][1]["capability_facts"][0]["valid_until"] = {"kind": "known", "at": "2026-10-21T08:30:00.000000Z"}
    assert native(body).solve_status == "feasibility_unknown"


def test_same_equipment_cannot_cover_two_simultaneous_quantity_slots():
    body = source_dict()
    duplicate = copy.deepcopy(body["cases"][0]["equipment"][0])
    duplicate["slot_id"] = "asset_2"
    body["cases"][0]["equipment"].append(duplicate)
    assert native(body).solve_status == "infeasible_proven"


@pytest.mark.parametrize("patch", [{"method": "unknown"}, {"semantics": "unknown"}])
def test_unknown_timing_does_not_create_definite_occupancy_or_false_optimistic_conflict(patch):
    body = source_dict()
    body["cases"] = [simple_case(body, number=0), simple_case(body, number=1)]
    body["cases"][1]["timing"].update(patch)
    result = native(body)
    assert result.solve_status == "feasibility_unknown"
    assert result.solution is not None
    assert result.solution.status == "provisional_unknown"


def test_zero_main_room_is_known_violation_but_unknown_end_is_not_zero():
    body = source_dict()
    body["cases"][0]["timing"]["segments"][0]["end_offset_us"] = amount("0")
    assert native(body).solve_status == "infeasible_proven"
    body["cases"][0]["timing"]["segments"][0]["end_offset_us"] = amount(None)
    assert native(body).solve_status == "feasibility_unknown"


def test_continuous_rolling_integral_peak_between_business_day_totals():
    budget = Budget()
    integral = WorkIntegral([(0, 8), (10, 18)], budget)
    maximum, interval = integral.rolling_maximum(12, (8, 12))
    assert maximum == 10
    assert integral.within(*interval) == 10
    assert integral.within(4, 12) == 6


def test_original_duty_work_and_case_work_union_never_double_count():
    body = source_dict()
    policy(body, max_work_rolling_24h=limit("86400000000"))
    result = native(body)
    assert result.solve_status == "optimal_proven"
    assert not any(w.code == "rolling_work" and w.status == "violated" for w in result.solution.violations)


def test_duty_presence_is_full_span_including_breaks_and_explicit_zero_limit():
    body = source_dict()
    policy(body, max_single_presence=limit("0"))
    assert native(body).solve_status == "infeasible_proven"


def test_confirmed_nonwork_break_cannot_be_overwritten_by_counted_surgery():
    body = source_dict()
    policy(body)
    body["duties"][0]["accounting"]["breaks"] = [{"start_at": "2026-10-21T08:00:00.000000Z", "end_at": "2026-10-21T10:00:00.000000Z", "counted_as_work": False, "absent_reason": None}]
    assert native(body).solve_status == "infeasible_proven"


def test_unselected_person_fixed_minimum_work_still_applies():
    body = source_dict()
    body["cases"] = []
    body["duties"][0]["accounting"]["counted_as_work"] = False
    policy(body, fixed_windows=[{"start_at": START, "end_at": END, "minimum_work": limit("1"), "maximum_work": limit()}])
    assert native(body).solve_status == "infeasible_proven"


def test_multiple_work_policies_cannot_choose_only_the_looser_limit():
    body = source_dict()
    loose = policy(body, max_single_presence=limit("86400000000"))
    tight = copy.deepcopy(loose)
    tight.update(policy_id=uid(701), max_single_presence=limit("0"))
    body["work_policies"].append(tight)
    assert native(body).solve_status == "infeasible_proven"


def test_partial_effectivity_remains_unknown_instead_of_applying_whole_duty_limit():
    body = source_dict()
    policy(body, effective_from_at="2026-10-21T08:00:00.000000Z", max_single_presence=limit("0"))
    assert native(body).solve_status == "feasibility_unknown"


def test_missing_work_policy_not_unlimited_but_explicit_reviewed_not_required_can_be_complete():
    body = source_dict()
    body["resources"][1]["work_policy_review"]["status"] = "reviewed_policies"
    assert native(body).solve_status == "feasibility_unknown"
    body["resources"][1]["work_policy_review"]["status"] = "attested_not_required"
    assert native(body).solve_status == "optimal_proven"


def test_budget_interrupt_retains_admissible_root_and_all_unvisited_siblings():
    body = source_dict()
    body["cases"][0]["starts"] += [{"start_at": f"2026-10-21T{hour:02}:00:00.000001Z", "penalty": amount(str(hour))} for hour in range(9, 12)]
    source = SurgerySource.model_validate(body)
    for operations in (1, 10, 100, 500):
        result = solve_graph(source, "optimistic", {"operation_limit": operations, "node_limit": 200, "frontier_limit": 100})
        assert result["proof"].frontier_nodes >= 1 or result["incumbent_key"] is not None
        assert result["bound_key"] is not None and result["bound_key"] <= (0,)


def test_node_or_frontier_limits_cannot_report_exhaustion_without_covering_remaining_domain():
    body = source_dict()
    body["cases"][0]["starts"] += [{"start_at": "2026-10-21T09:00:00.000001Z", "penalty": amount("1")}]
    source = SurgerySource.model_validate(body)
    for limits in ({"operation_limit": 100000, "node_limit": 1, "frontier_limit": 100}, {"operation_limit": 100000, "node_limit": 100, "frontier_limit": 1}):
        result = solve_graph(source, "optimistic", limits)
        assert result["proof"].termination in ("node_limit", "frontier_limit")
        assert result["proof"].frontier_nodes == 1
        assert result["bound_key"] == (0,)


def test_analysis_tamper_prompt_model_source_proof_and_soft_cost_are_all_recomputed():
    body = source_dict()
    result = native(body)
    for section, key, value in [("solution", "exact_penalty_points", "1"), ("definite_search", "expanded_nodes", 0), ("source_binding", "projection_hash", "a" * 64)]:
        changed = result.model_dump()
        changed[section][key] = value
        with pytest.raises(ValueError):
            validate_analysis_binding(changed, body, H, result.local_runtime.model_version)
    with pytest.raises(ValueError):
        validate_analysis_binding(result, body, "a" * 64, result.local_runtime.model_version)
    with pytest.raises(ValueError):
        validate_analysis_binding(result, body, H, "surgery:" + "a" * 64)


def test_selected_stage_microseconds_are_exact_without_float_timestamp_rounding():
    body = source_dict()
    body["cases"][0]["timing"]["segments"][0]["end_offset_us"]["value"] = "1"
    item = check_candidate(body, [assignment(body["cases"][0])], [])
    assert clock_us(item.occupancies[0].end_at) - clock_us(item.occupancies[0].start_at) == 1
    assert item.occupancies[0].end_at.endswith("000002Z")
