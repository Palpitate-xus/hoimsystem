"""Explicit review/input boundaries, real IANA dates and concrete demand choices."""

import copy
from datetime import datetime

import pytest
from pydantic import ValidationError

from app.ai.surgery_scenario_input import DomainChoice, PeriodSelection, ScenarioCreate, period_for
from tests.test_ai_surgery_contract import H, source_dict, uid

BASIS = "合成独立复核说明用于核对明确原始范围与未推断的完整来源事实"


def declaration():
    source = source_dict()

    def coverage(item):
        return {key: value for key, value in item.items() if key != "basis_hash"} | {"basis_note": BASIS}

    def policy(item):
        return {"status": item["status"], "basis_note": BASIS}

    def ref(number):
        return {"source_record_id": uid(number), "expected_content_hash": H, "expected_governance_hash": H}

    def demand(item, person=False):
        return {
            "slot_id": item["slot_id"],
            "domain_status": item["domain_status"],
            "basis_note": BASIS,
            "choices": [
                {
                    "resource_id": choice["resource_id"],
                    "penalty": choice["penalty"],
                    "duty_source": ref(7) if person else None,
                    "duty_binding_status": "verified" if person else None,
                    "duty_basis_note": BASIS if person else None,
                }
                for choice in item["choices"]
            ],
        }

    case = source["cases"][0]
    return {
        "pool_id": uid(500),
        "period": {"business_timezone": "Etc/UTC", "date_from": "2026-10-21", "date_to": "2026-10-21", "as_of": source["as_of"]},
        "expected_capture_digest": H,
        "objective_mode": source["objective_mode"],
        "problem_coverage": {
            **{key: coverage(source["problem_coverage"][key]) for key in ("cases", "resources", "all_locations_busy", "policies")},
            "finite_domains_status": "attested_complete",
            "basis_note": BASIS,
        },
        "members": [{**ref(index + 1), "source_kind": item["kind"], "selection": "confirmed", "basis_note": BASIS} for index, item in enumerate(source["manifest"])],
        "person_partition": {"status": "unknown", "resource_ids": sorted(item["resource_id"] for item in source["resources"] if item["kind"] == "person"), "basis_note": BASIS},
        "cases": [
            {
                "application_id": uid(501),
                "requirements": ref(1),
                "duration_estimate": ref(3),
                "basis_note": BASIS,
                "start_domain_status": case["start_domain_status"],
                "starts": case["starts"],
                "room": demand(case["room"]),
                "roles": [demand(item, True) for item in case["roles"]],
                "equipment": [demand(item) for item in case["equipment"]],
                "penalty_if_scheduled": case["penalty_if_scheduled"],
                "penalty_if_deferred": case["penalty_if_deferred"],
            }
        ],
        "resources": [
            {
                "resource_id": item["resource_id"],
                "expected_resource_hash": H,
                "expected_membership_id": uid(600 + index),
                "expected_membership_hash": H,
                "expected_membership_governance_hash": H,
                "availability_coverage": coverage(item["availability_coverage"]),
                "all_locations_busy_coverage": coverage(item["all_locations_busy_coverage"]),
                "transition_class_status": item["transition_class_coverage"]["status"],
                "transition_policy_review": policy(item["transition_policy_review"]),
                "work_policy_review": policy(item["work_policy_review"]) if item["work_policy_review"] is not None else None,
                "all_locations_duty_coverage": coverage(item["all_locations_duty_coverage"]) if item["all_locations_duty_coverage"] is not None else None,
                "basis_note": BASIS,
            }
            for index, item in enumerate(source["resources"])
        ],
        "basis_note": BASIS,
    }


def test_exact_declared_choices_keep_original_zero_off_grid_microseconds_and_unknown():
    body = declaration()
    body["cases"][0]["roles"][0]["choices"][0].update(duty_source=None, duty_binding_status="unknown", duty_basis_note=BASIS)
    body["resources"][0]["availability_coverage"]["status"] = "unknown"
    value = ScenarioCreate.model_validate(body)
    assert value.model_dump() == body
    assert value.cases[0].starts[0].start_at.endswith("000001Z")
    assert value.cases[0].penalty_if_scheduled.value == "0"
    assert value.resources[0].availability_coverage.status == "unknown"
    assert value.cases[0].roles[0].choices[0].duty_source is None


@pytest.mark.parametrize("day,hours", [("2026-03-08", 23), ("2026-11-01", 25)])
def test_real_dst_business_days_have_actual_duration(day, hours):
    selected = PeriodSelection(business_timezone="America/New_York", date_from=day, date_to=day, as_of="2026-03-01T00:00:00.000000Z")
    period = period_for(selected)
    item = period.days[0]
    assert (datetime.fromisoformat(item.end_at) - datetime.fromisoformat(item.start_at)).total_seconds() == hours * 3600


@pytest.mark.parametrize(
    "body",
    [
        {"business_timezone": "Etc/UTC", "date_from": "9999-12-31", "date_to": "9999-12-31", "as_of": "9999-12-31T00:00:00.000000Z"},
        {"business_timezone": "Pacific/Apia", "date_from": "2011-12-30", "date_to": "2011-12-30", "as_of": "2011-12-01T00:00:00.000000Z"},
    ],
)
def test_calendar_overflow_and_actual_nonexistent_midnight_are_validation_errors(body):
    with pytest.raises(ValidationError):
        PeriodSelection.model_validate(body)


@pytest.mark.parametrize(
    "patch",
    [
        {"business_timezone": "Imaginary/Unknown"},
        {"date_from": "2026-02-30"},
        {"date_from": "2026-10-22"},
        {"date_to": "2026-11-21"},
        {"date_from": "2026-10-19"},
        {"date_from": "2027-10-22", "date_to": "2027-10-22"},
    ],
)
def test_unknown_timezone_invalid_reversed_long_or_outside_horizon_dates_are_rejected(patch):
    body = declaration()["period"] | patch
    with pytest.raises(ValidationError):
        PeriodSelection.model_validate(body)


@pytest.mark.parametrize(
    "change",
    [
        "repeated_case",
        "repeated_resource",
        "repeated_start",
        "unordered_start",
        "old_start",
        "foreign_resource",
        "same_demand",
        "patient_demand",
        "room_duty",
        "person_no_duty_declaration",
        "unknown_duty_without_basis",
        "verified_duty_without_original",
        "objective_default",
        "penalty_default",
        "weak_basis",
        "free_quantity_override",
    ],
)
def test_complete_declaration_rejects_ambiguous_or_forged_scope_and_implicit_defaults(change):
    body = declaration()
    case = body["cases"][0]
    role = case["roles"][0]
    if change == "repeated_case":
        body["cases"].append(copy.deepcopy(case))
    elif change == "repeated_resource":
        body["resources"].append(copy.deepcopy(body["resources"][0]))
    elif change == "repeated_start":
        case["starts"].append(copy.deepcopy(case["starts"][0]))
    elif change == "unordered_start":
        case["starts"].append({"start_at": "2026-10-21T07:00:00.000001Z", "penalty": {"value": "0", "absent_reason": None}})
    elif change == "old_start":
        case["starts"][0]["start_at"] = "2026-10-19T07:00:00.000001Z"
    elif change == "foreign_resource":
        role["choices"][0]["resource_id"] = uid(999)
    elif change == "same_demand":
        role["slot_id"] = case["room"]["slot_id"]
    elif change == "patient_demand":
        role["slot_id"] = "patient"
    elif change == "room_duty":
        case["room"]["choices"][0] = copy.deepcopy(role["choices"][0])
    elif change == "person_no_duty_declaration":
        role["choices"][0].update(duty_source=None, duty_binding_status=None, duty_basis_note=None)
    elif change == "unknown_duty_without_basis":
        role["choices"][0].update(duty_source=None, duty_binding_status="unknown", duty_basis_note=None)
    elif change == "verified_duty_without_original":
        role["choices"][0]["duty_source"] = None
    elif change == "objective_default":
        body.pop("objective_mode")
    elif change == "penalty_default":
        case.pop("penalty_if_scheduled")
    elif change == "weak_basis":
        body["basis_note"] = " " * 20
    else:
        case["room_capacity"] = 999
    with pytest.raises(ValidationError):
        ScenarioCreate.model_validate(body)


def test_choice_never_coerces_resource_identity_or_original_penalty():
    body = declaration()["cases"][0]["room"]["choices"][0]
    body["penalty"]["value"] = 0
    with pytest.raises(ValidationError):
        DomainChoice.model_validate(body)


@pytest.mark.parametrize("change", ["missing", "duplicate", "excluded", "unknown", "kind", "content", "governance"])
def test_selected_complete_original_cannot_bypass_its_whole_member_review(change):
    body = declaration()
    if change == "missing":
        body["members"].pop(0)
    elif change == "duplicate":
        body["members"].append(copy.deepcopy(body["members"][0]))
    elif change in {"excluded", "unknown"}:
        body["members"][0]["selection"] = change
    elif change == "kind":
        body["members"][0]["source_kind"] = "resource_occupation_policy"
    else:
        body["members"][0]["expected_" + change + "_hash"] = "0" * 64
    with pytest.raises(ValidationError):
        ScenarioCreate.model_validate(body)


@pytest.mark.parametrize("change", ["missing", "foreign", "duplicate"])
def test_distinct_accounts_never_implicitly_review_the_whole_person_partition(change):
    body = declaration()
    if change == "missing":
        body.pop("person_partition")
    elif change == "foreign":
        body["person_partition"]["resource_ids"].append(uid(999))
    else:
        body["person_partition"]["resource_ids"] *= 2
    with pytest.raises(ValidationError):
        ScenarioCreate.model_validate(body)
