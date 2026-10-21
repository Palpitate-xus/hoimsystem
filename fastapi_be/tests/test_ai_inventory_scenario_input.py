"""The scene declares choices and shared policy without inventing original quantities."""

import copy
import datetime

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.ai.inventory_scenario_input import CostConstraint, QuantityConstraint, ScenarioPeriodRequest, ScenarioRequest, validate_planning_period
from tests.test_ai_inventory_native_source_input import HASH, NOTE, cost, quantity


def identity(number):
    return f"00000000-0000-4000-8000-{number:012d}"


def ref(number):
    return {"source_record_id": identity(number), "expected_content_hash": HASH, "expected_governance_hash": "b" * 64}


def period():
    return {
        "item_kind": "pharmaceutical",
        "item_id": 67,
        "scope": "hospital_inventory",
        "timezone": "America/New_York",
        "date_from": "2026-11-01",
        "date_to": "2026-11-01",
        "as_of": "2026-10-21T12:00:00.123456Z",
    }


def request():
    return {
        **period(),
        "unit_definition_id": identity(66),
        "expected_unit_content_hash": HASH,
        "expected_unit_governance_hash": "b" * 64,
        "observation": ref(1),
        "future_quantity_scenario": ref(2),
        "candidates": [ref(3)],
        "member_reviews": [],
        "daily_constraints": [{"date": "2026-11-01", "minimum_end_usable": {"mode": "unknown", "amount": None}, "maximum_end_total": {"mode": "not_applicable", "amount": None}}],
        "shared_budget": {"mode": "known", "amount": cost("0.000000")},
        "cost_unit": {"currency_text": "原明确币种", "original_cost_unit_text": "原明确计价元", "review": "unknown", "basis_note": NOTE},
        "policy_review": "unknown",
        "policy_basis_note": NOTE,
        "assumptions": {"opening_carry_forward": "unknown", "no_other_inventory_changes": "unknown", "frozen_quantities_unchanged": "unknown", "basis_note": NOTE},
        "candidate_set_review": "unknown",
        "candidate_set_basis_note": NOTE,
    }


def test_complete_explicit_request_retains_decimal_lexemes_and_all_unknown_declarations():
    values = request()
    assert ScenarioRequest.model_validate(values).model_dump(mode="json") == values
    assert values["shared_budget"]["amount"]["value"] == "0.000000"
    assert values["daily_constraints"][0]["minimum_end_usable"]["amount"] is None


@pytest.mark.parametrize(
    "key,value",
    [
        ("item_id", True),
        ("item_id", "67"),
        ("date_from", "2026-10-21"),
        ("date_to", "2026-12-02"),
        ("timezone", "unknown/zone"),
        ("as_of", "2026-10-21T12:00:00Z"),
        ("as_of", "2026-02-30T12:00:00.000000Z"),
    ],
)
def test_strict_actual_sku_clocks_and_future_domain(key, value):
    values = period()
    values[key] = value
    with pytest.raises(ValidationError):
        ScenarioPeriodRequest.model_validate(values)


@pytest.mark.parametrize("field", ["daily_constraints", "shared_budget", "cost_unit", "policy_review", "assumptions", "member_reviews"])
def test_common_policy_and_whole_collection_declarations_have_no_defaults(field):
    values = request()
    del values[field]
    with pytest.raises(ValidationError):
        ScenarioRequest.model_validate(values)


@pytest.mark.parametrize("field,value", [("recipe", {}), ("input_policy", {}), ("profile_id", identity(1)), ("policy_version", "forged"), ("horizon_days", 7)])
def test_fixed_recipe_profile_and_unimplemented_horizon_cannot_be_request_injected(field, value):
    values = request()
    values[field] = value
    with pytest.raises(ValidationError):
        ScenarioRequest.model_validate(values)


@pytest.mark.parametrize("cls,builder", [(QuantityConstraint, quantity), (CostConstraint, cost)])
def test_unknown_is_not_unlimited_and_zero_requires_known_tag(cls, builder):
    assert cls.model_validate({"mode": "known", "amount": builder("0")}).amount.value == "0"
    for value in [{"mode": "known", "amount": None}, {"mode": "known", "amount": builder(None)}, {"mode": "unknown", "amount": builder("0")}, {"mode": "not_applicable", "amount": builder("0")}]:
        with pytest.raises(ValidationError):
            cls.model_validate(value)


@pytest.mark.parametrize("change", ["duplicate_candidate", "duplicate_role", "duplicate_member", "missing_day", "duplicate_day", "different_date"])
def test_whole_plan_roles_and_daily_constraints_never_repeat_or_silently_drop(change):
    values = request()
    if change == "duplicate_candidate":
        values["candidates"] *= 2
    elif change == "duplicate_role":
        values["future_quantity_scenario"] = copy.deepcopy(values["observation"])
    elif change == "duplicate_member":
        values["member_reviews"] = [{**ref(3), "source_kind": "purchase_candidate_plan", "use": "unknown", "basis_note": NOTE}] * 2
    elif change == "missing_day":
        values["daily_constraints"] = []
    elif change == "duplicate_day":
        values["daily_constraints"] *= 2
    else:
        values["daily_constraints"][0]["date"] = "2026-11-02"
    with pytest.raises(ValidationError):
        ScenarioRequest.model_validate(values)


def test_fresh_planning_gate_is_separate_from_unchanged_historical_request_validation():
    values = period()
    assert validate_planning_period(values, now=datetime.datetime(2026, 10, 21, 13))
    with pytest.raises(HTTPException) as caught:
        validate_planning_period(values, now=datetime.datetime(2026, 11, 1, 12))
    assert caught.value.status_code == 409
    assert ScenarioPeriodRequest.model_validate(values).as_of == values["as_of"]
