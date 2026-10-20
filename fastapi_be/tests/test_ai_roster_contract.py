"""Actual public staffing contracts, without importing hospital configuration."""

import copy
import uuid
from datetime import date, timedelta

import pytest
from pydantic import ValidationError

from app.ai.roster_contract import MAX_POLICY_MINUTES, MAX_SAFE_INTEGER, ConstraintValue, MinuteConstraintValue, RosterSource, hash_content, input_policy_digest, recipe_digest


def identifier(value):
    return str(uuid.UUID(int=value))


def limit(value):
    return {"value": value, "absent_reason": None if value is not None else "unknown"}


def fact(kind, number):
    prefixes = {"qualification": "roster_qualification", "duty_interval": "roster_duty", "availability": "roster_availability", "work_rule_policy": "roster_work_policy"}
    digest = hash_content(["synthetic actual typed public source", kind, number])
    return {
        "kind": kind,
        "source_record_id": identifier(number),
        "source_id": f"{prefixes[kind]}:{identifier(number)}:{digest[:12]}",
        "content_hash": digest,
        "governance_hash": hash_content(["published", number]),
        "status": "published",
        "revision": 2,
        "recorded_at": "2026-01-01T00:00:00.000000Z",
    }


def complete_source():
    basis = hash_content("Only synthetic independently reviewed facts, no actual hospital records")
    problem, staff, session, option = (identifier(i) for i in (1, 2, 3, 4))
    policy_ref = fact("work_rule_policy", 10)
    digest = hash_content("Synthetic private complete original, not its public projection")
    return {
        "schema_version": "roster_source_v1",
        "problem_id": problem,
        "source_id": f"roster_problem:{problem}:{digest[:12]}",
        "content_hash": digest,
        "problem_governance_hash": basis,
        "scope_binding_hash": basis,
        "manifest_digest": basis,
        "rule_id": "roster_declared_constraints_v1",
        "recipe_digest": recipe_digest(),
        "input_policy_digest": input_policy_digest(),
        "objective_mode": "meet_targets_min_penalty",
        "planning_start_at": "2026-10-20T00:00:00.000000Z",
        "planning_end_at": "2026-10-27T00:00:00.000000Z",
        "business_timezone": "UTC",
        "business_dates": [str(date(2026, 10, 20) + timedelta(days=i)) for i in range(7)],
        "as_of": "2026-10-19T00:00:00.000000Z",
        "captured_at": "2026-10-19T00:00:00.000001Z",
        "capture_mode": "current_capture",
        "personnel_coverage": "attested_complete",
        "personnel_coverage_basis_hash": basis,
        "session_requirements_coverage": "attested_complete",
        "session_requirements_coverage_basis_hash": basis,
        "work_policies": [
            {
                "ref": policy_ref,
                "applicable_staff_ids": [staff],
                "effective_from_at": "2026-01-01T00:00:00.000000Z",
                "effective_until_at": "2027-01-01T00:00:00.000000Z",
                "effective_until_absent_reason": None,
                "max_single_duty_presence_minutes": limit(480),
                "max_work_minutes_rolling_24h": limit(480),
                "max_work_minutes_rolling_7d": limit(2400),
                "minimum_rest_minutes": limit(660),
                "fixed_work_windows": [],
                "basis_hash": basis,
                "policy_reference_hash": basis,
            }
        ],
        "staff": [
            {
                "staff_id": staff,
                "identity_binding_hash": basis,
                "qualifications": [
                    {
                        "ref": fact("qualification", 11),
                        "employment_status": "active",
                        "qualification_status": "verified",
                        "authorized_job_hashes": [basis],
                        "valid_from_at": "2026-01-01T00:00:00.000000Z",
                        "valid_until_at": "2027-01-01T00:00:00.000000Z",
                        "expiry_status": "known",
                        "basis_hash": basis,
                    }
                ],
                "duties": [],
                "availability": [
                    {
                        "ref": fact("availability", 12),
                        "start_at": "2026-10-20T00:00:00.000000Z",
                        "end_at": "2026-10-27T00:00:00.000000Z",
                        "availability": "available",
                        "basis_kind": "administrative_confirmation",
                        "basis_hash": basis,
                    }
                ],
                "all_locations_duty_coverage": {"start_at": "2025-01-01T00:00:00.000000Z", "end_at": "2027-01-01T00:00:00.000000Z", "status": "attested_complete", "basis_hash": basis},
            }
        ],
        "sessions": [
            {
                "session_id": session,
                "start_at": "2026-10-20T08:00:00.000000Z",
                "end_at": "2026-10-20T16:00:00.000000Z",
                "business_date": "2026-10-20",
                "required_job_hash": basis,
                "minimum_staff": 1,
                "maximum_staff": 1,
                "required_slots": limit(5),
                "facility_slot_ceiling": limit(10),
                "requirements_basis_hash": basis,
                "capacity_basis_hash": basis,
            }
        ],
        "options": [
            {
                "option_id": option,
                "staff_id": staff,
                "session_id": session,
                "cost_points": limit(2),
                "slot_capacity": limit(8),
                "breaks": [],
                "breaks_complete": True,
                "time_accounting_status": "verified",
                "basis_hash": basis,
            }
        ],
        "submitted_candidate": None,
    }


def test_complete_source_is_exact_original_and_two_objectives_are_explicit():
    source = complete_source()
    for mode in ("meet_targets_min_penalty", "max_slots_then_min_penalty"):
        source["objective_mode"] = mode
        assert RosterSource.model_validate(source).model_dump() == source


@pytest.mark.parametrize("value", [0, 1, 2147483647, None])
def test_original_known_zero_and_unknown_are_distinct(value):
    assert ConstraintValue.model_validate(limit(value)).value == value


@pytest.mark.parametrize("value", [False, True, "0", 0.0, -1, 2147483648])
def test_counts_never_coerce_bool_float_text_or_out_of_domain(value):
    with pytest.raises(ValidationError):
        ConstraintValue.model_validate({"value": value, "absent_reason": None})


def test_policy_minutes_exact_microseconds_fit_public_safe_integer_domain():
    assert MinuteConstraintValue.model_validate(limit(MAX_POLICY_MINUTES)).value * 60000000 <= MAX_SAFE_INTEGER
    assert (MAX_POLICY_MINUTES + 1) * 60000000 > MAX_SAFE_INTEGER
    assert ConstraintValue.model_validate(limit(2147483647)).value == 2147483647
    with pytest.raises(ValidationError):
        MinuteConstraintValue.model_validate(limit(MAX_POLICY_MINUTES + 1))


@pytest.mark.parametrize("field", ["max_single_duty_presence_minutes", "max_work_minutes_rolling_24h", "max_work_minutes_rolling_7d", "minimum_rest_minutes"])
def test_large_policy_minutes_are_rejected_at_source_boundary(field):
    source = complete_source()
    source["work_policies"][0][field] = limit(MAX_POLICY_MINUTES + 1)
    with pytest.raises(ValidationError):
        RosterSource.model_validate(source)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda s: s.update(recipe_digest="0" * 64),
        lambda s: s.update(input_policy_digest="0" * 64),
        lambda s: s.update(objective_mode="arbitrary_user_weight"),
        lambda s: s.update(planning_start_at="2026-02-30T00:00:00.000000Z"),
        lambda s: s.update(planning_start_at="2026-10-20T00:00:00Z"),
        lambda s: s.update(planning_end_at="2026-10-27T00:00:00.000000+00:00"),
        lambda s: s["business_dates"].__setitem__(1, "2026-10-22"),
        lambda s: s["staff"].append(copy.deepcopy(s["staff"][0])),
        lambda s: s["options"].append(copy.deepcopy(s["options"][0])),
        lambda s: s["options"][0].update(staff_id=identifier(999)),
        lambda s: s["sessions"][0].update(business_date="2026-10-21"),
        lambda s: s["work_policies"][0]["ref"].update(source_id="roster_duty:wrong-kind"),
        lambda s: s["work_policies"][0]["ref"].update(recorded_at="2026-10-19T00:00:00.000001Z"),
        lambda s: s["options"][0].update(breaks_complete=False),
        lambda s: s.update(question="Arbitrary private clinical prose is not public input"),
    ],
)
def test_wrong_identity_policy_scope_original_clocks_or_extra_prose_fail_closed(mutate):
    source = complete_source()
    mutate(source)
    with pytest.raises((ValidationError, ValueError)):
        RosterSource.model_validate(source)


def test_break_false_unknown_and_raw_absent_reason_are_not_replaced():
    source = complete_source()
    option = source["options"][0]
    option["breaks"] = [{"start_at": "2026-10-20T12:00:00.000000Z", "end_at": "2026-10-20T12:30:00.000000Z", "counted_as_work": False, "counted_as_work_absent_reason": None}]
    assert RosterSource.model_validate(source).options[0].breaks[0].counted_as_work is False
    option["breaks"][0].update(counted_as_work=None, counted_as_work_absent_reason="unknown")
    option["time_accounting_status"] = "unknown"
    assert RosterSource.model_validate(source).model_dump()["options"][0]["breaks"][0] == option["breaks"][0]
    option["time_accounting_status"] = "verified"
    with pytest.raises(ValidationError):
        RosterSource.model_validate(source)


def test_512_original_staff_are_accepted_including_without_periodic_schedule():
    source = complete_source()
    for number in range(511):
        person = copy.deepcopy(source["staff"][0])
        person.update(staff_id=identifier(1000 + number), qualifications=[], duties=[], availability=[])
        source["staff"].append(person)
        option = copy.deepcopy(source["options"][0])
        option.update(option_id=identifier(10000 + number), staff_id=person["staff_id"])
        source["options"].append(option)
    assert len(RosterSource.model_validate(source).staff) == 512
    source["staff"].append({**source["staff"][-1], "staff_id": identifier(9999)})
    with pytest.raises(ValidationError):
        RosterSource.model_validate(source)


def test_business_dates_use_actual_dst_midnights_not_24_hour_multiplication():
    source = complete_source()
    source.update(
        planning_start_at="2026-03-07T05:00:00.000000Z",
        planning_end_at="2026-03-14T04:00:00.000000Z",
        business_timezone="America/New_York",
        business_dates=[str(date(2026, 3, 7) + timedelta(days=i)) for i in range(7)],
        as_of="2026-03-06T12:00:00.000000Z",
        captured_at="2026-03-06T12:00:00.000001Z",
    )
    source["sessions"][0].update(start_at="2026-03-07T13:00:00.000000Z", end_at="2026-03-07T21:00:00.000000Z", business_date="2026-03-07")
    source["staff"][0]["availability"][0].update(start_at=source["planning_start_at"], end_at=source["planning_end_at"])
    assert RosterSource.model_validate(source).planning_end_at == "2026-03-14T04:00:00.000000Z"
    source["planning_end_at"] = "2026-03-14T05:00:00.000000Z"
    with pytest.raises(ValidationError):
        RosterSource.model_validate(source)


def test_fixed_window_outside_plan_and_zero_bounds_keep_whole_original():
    source = complete_source()
    window = {
        "start_at": "2026-10-01T00:00:00.000000Z",
        "end_at": "2026-11-01T00:00:00.000000Z",
        "minimum_work_minutes": limit(0),
        "maximum_work_minutes": {"value": None, "absent_reason": "not_applicable"},
    }
    source["work_policies"][0]["fixed_work_windows"] = [window]
    assert RosterSource.model_validate(source).model_dump()["work_policies"][0]["fixed_work_windows"] == [window]
