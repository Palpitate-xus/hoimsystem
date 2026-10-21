"""Synthetic closed candidate-plan facts; no hospital fixtures, settings or database."""

import copy
import uuid
from datetime import date, timedelta

import pytest
from pydantic import ValidationError

from app.ai.inventory_contract import Amount, ExactFraction, InventorySource, canonical_json, day_bounds, hash_content, input_policy_digest, rational, recipe_digest


def uid(value):
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "inventory-synthetic:" + str(value)))


def amount(value="0", cost=False):
    return {
        "value": value,
        "absent_reason": None if value is not None else "unknown",
        "unit_token": hash_content("cost-unit" if cost else "quantity-unit"),
        "original_unit_hash": hash_content("synthetic original unit"),
        "unit_review": "confirmed",
    }


def date_value(value=None, reason="not_applicable"):
    return {"value": value, "absent_reason": reason if value is None else None}


def constraint(value=None, cost=False, mode="not_applicable"):
    return {"mode": "known" if value is not None else mode, "amount": amount(value, cost) if value is not None else None}


def fact(kind, name):
    identifier, digest = uid(name), hash_content([kind, name])
    return {
        "source_record_id": identifier,
        "source_id": f"inventory_fact:{identifier}:{digest[:12]}",
        "kind": kind,
        "content_hash": digest,
        "governance_hash": hash_content([name, "published"]),
        "recorded_at": "2026-10-20T10:00:00.000000Z",
        "published_at": "2026-10-20T11:00:00.000000Z",
    }


def lot(name, quantity="5", frozen="0", expiry="2026-10-25"):
    return {"lot_id": uid(name), "quantity": amount(quantity), "frozen_quantity": amount(frozen), "valid_through": date_value(expiry), "expiry_review": "confirmed", "frozen_review": "confirmed"}


def receipt(name="receipt", quantity="2", arrival="2026-10-22", expiry="2026-10-25", price="1.25"):
    return {**lot(name, quantity, "0", expiry), "arrival_date": date_value(arrival, "unknown"), "unit_price": amount(price, True), "price_basis_review": "confirmed"}


def refresh(value):
    value["declared_candidate_ids"] = [row["candidate_id"] for row in value["candidates"]]
    value["member_manifest"] = [value["observation"]["ref"], value["scenario"]["ref"], *[row["ref"] for row in value["candidates"]]]
    value["member_manifest_hash"] = hash_content(value["member_manifest"])
    return value


def candidate(name="buy", lines=None, fixed="0"):
    lines = [receipt()] if lines is None else lines
    return {
        "ref": fact("purchase_candidate_plan", name),
        "candidate_id": uid("candidate:" + name),
        "completeness": "attested_complete",
        "completeness_basis_hash": hash_content("complete plan"),
        "plan_fixed_fee": amount(fixed, True),
        "orders": [] if not lines else [{"order_id": uid("order:" + name), "order_fixed_fee": amount("0", True), "lines": lines}],
    }


def make_source(days=3):
    first = date(2026, 10, 21)
    digest = hash_content("entire immutable synthetic private scenario")
    policy = {
        "event_order": "expire_then_receive_then_fefo_draw_then_check_v1",
        "expiry_semantics": "valid_through_inclusive",
        "allocation": "fefo_expiry_then_lot_id",
        "stockout": "all_reviewed_daily_quantities_must_be_met",
        "frozen_policy": "frozen_quantity_unavailable_until_expiry",
        "policy_review": "confirmed",
        "basis_hash": hash_content("actual professional policy review"),
    }
    return refresh(
        {
            "schema_version": "inventory_source_v1",
            "scenario_id": uid("scenario"),
            "source_id": f"inventory_scenario:{uid('scenario')}:{digest[:12]}",
            "content_hash": digest,
            "governance_hash": hash_content("original active governance"),
            "profile_id": uid("profile"),
            "profile_content_hash": hash_content("profile"),
            "profile_governance_hash": hash_content("published profile"),
            "rule_id": "inventory_declared_candidate_plans_v1",
            "recipe_digest": recipe_digest(),
            "input_policy_digest": input_policy_digest(),
            "scope": "single_sku_single_physical_scope_single_quantity_and_cost_unit",
            "item_kind": "pharmaceutical",
            "item_token": hash_content("actual sku"),
            "scope_token": hash_content("actual physical scope"),
            "quantity_unit_token": hash_content("quantity-unit"),
            "cost_unit_token": hash_content("cost-unit"),
            "timezone": "UTC",
            "as_of": "2026-10-20T12:00:00.000000Z",
            "captured_at": "2026-10-20T12:00:01.000000Z",
            "date_from": first.isoformat(),
            "date_to": (first + timedelta(days=days - 1)).isoformat(),
            "declared_candidate_ids": [],
            "candidate_set_review": "confirmed",
            "candidate_set_basis_hash": hash_content("explicit finite alternatives"),
            "member_manifest": [],
            "member_manifest_hash": "a" * 64,
            "observation": {
                "ref": fact("inventory_observation", "stock"),
                "observed_at": "2026-10-20T09:00:00.000000Z",
                "method": "independent_count",
                "professional_review": "confirmed",
                "scope_review": "confirmed",
                "coverage": "attested_complete",
                "coverage_basis_hash": hash_content("full stock count"),
                "lots": [lot("stock")],
                "declared_total_quantity": amount("5"),
                "physical_reconciliation": "confirmed",
                "reconciliation_basis_hash": hash_content("physical reconciliation"),
                "legacy_snapshot": {
                    "captured_at": "2026-10-20T09:30:00.000000Z",
                    "collection_digest": hash_content("all original stock batches ledger and open PO"),
                    "catalog_quantity": amount("5"),
                    "batch_quantity_sum": amount("5"),
                    "batch_applicability": "applicable",
                    "reconciliation": "confirmed",
                    "basis_hash": hash_content("all legacy parents and members reconciled"),
                },
            },
            "scenario": {
                "ref": fact("future_quantity_scenario", "future"),
                "basis": "reviewed_operational_scenario",
                "quantity_definition": "planned_physical_stock_drawdown",
                "scope_review": "confirmed",
                "coverage": "attested_complete",
                "days": [
                    {"date": (first + timedelta(days=i)).isoformat(), "required_quantity": amount("2"), "minimum_end_usable": constraint(), "maximum_end_total": constraint()} for i in range(days)
                ],
                "budget": constraint(),
                "policy": policy,
                "assumptions": {
                    "opening_carry_forward": "confirmed",
                    "no_other_inventory_changes": "confirmed",
                    "frozen_quantities_unchanged": "confirmed",
                    "basis_hash": hash_content("reviewed continuation assumptions"),
                },
            },
            "candidates": [candidate()],
        }
    )


def test_complete_original_numeric_text_roundtrip_without_coercion():
    value = make_source()
    value["observation"]["lots"][0]["quantity"]["value"] = "5.000000"
    assert InventorySource.model_validate(value).model_dump() == value
    assert len(canonical_json(value).encode()) < 15000


@pytest.mark.parametrize("value", [False, 0, 1.1, "-1", "01", "+1", "1e2", "NaN", "0.0000001", "1000000000000000000"])
def test_amount_explicit_decimal_domain(value):
    with pytest.raises(ValidationError):
        Amount.model_validate(amount(value))


@pytest.mark.parametrize("quantity", [{"value": "0", "absent_reason": "unknown"}, {"value": None, "absent_reason": None}])
def test_known_zero_and_absence_are_mutually_exclusive(quantity):
    with pytest.raises(ValidationError):
        Amount.model_validate({**amount(), **quantity})


def test_legacy_negative_and_raw_total_conflict_are_preserved_for_math_unknown():
    value = make_source()
    value["observation"]["legacy_snapshot"]["catalog_quantity"] = amount("-2")
    value["observation"]["legacy_snapshot"]["batch_quantity_sum"] = amount("7")
    value["observation"]["legacy_snapshot"]["reconciliation"] = "not_confirmed"
    value["observation"]["physical_reconciliation"] = "unknown"
    source = InventorySource.model_validate(value)
    assert source.observation.legacy_snapshot.catalog_quantity.value == "-2"
    assert source.observation.legacy_snapshot.batch_quantity_sum.value == "7"


def test_unbatched_consumable_has_no_invented_batch_zero():
    value = make_source()
    value["item_kind"] = "consumable"
    value["observation"]["legacy_snapshot"]["batch_applicability"] = "not_applicable"
    value["observation"]["legacy_snapshot"]["batch_quantity_sum"] = None
    assert InventorySource.model_validate(value).observation.legacy_snapshot.batch_quantity_sum is None


@pytest.mark.parametrize(
    "mutation",
    [
        "source_id",
        "manifest",
        "omitted_plan",
        "duplicate_plan",
        "duplicate_ref",
        "missing_day",
        "day_order",
        "wrong_kind",
        "future_publication",
        "raw_question",
        "duplicate_lot",
        "lot_is_initial",
        "arrival_outside",
        "forged_observed",
        "missing_observed",
        "same_day",
        "invalid_tz",
        "nonexistent_midnight",
        "upper_date",
    ],
)
def test_whole_source_closed_membership_clocks_and_dates(mutation):
    value = make_source()
    if mutation == "source_id":
        value["source_id"] += "bad"
    elif mutation == "manifest":
        value["member_manifest_hash"] = "f" * 64
    elif mutation == "omitted_plan":
        value["declared_candidate_ids"] = []
    elif mutation == "duplicate_plan":
        value["candidates"].append(copy.deepcopy(value["candidates"][0]))
        refresh(value)
    elif mutation == "duplicate_ref":
        value["candidates"][0]["ref"] = copy.deepcopy(value["observation"]["ref"])
        refresh(value)
    elif mutation == "missing_day":
        value["scenario"]["days"].pop()
    elif mutation == "day_order":
        value["scenario"]["days"].reverse()
    elif mutation == "wrong_kind":
        value["scenario"]["ref"]["kind"] = "purchase_candidate_plan"
        refresh(value)
    elif mutation == "future_publication":
        value["observation"]["ref"]["published_at"] = "2026-10-21T00:00:00.000000Z"
        refresh(value)
    elif mutation == "raw_question":
        value["question"] = "private sentinel"
    elif mutation == "duplicate_lot":
        value["candidates"][0]["orders"][0]["lines"].append(copy.deepcopy(value["candidates"][0]["orders"][0]["lines"][0]))
    elif mutation == "lot_is_initial":
        value["candidates"][0]["orders"][0]["lines"][0]["lot_id"] = value["observation"]["lots"][0]["lot_id"]
    elif mutation == "arrival_outside":
        value["candidates"][0]["orders"][0]["lines"][0]["arrival_date"]["value"] = "2026-10-24"
    elif mutation == "forged_observed":
        value["observation"]["method"] = "legacy_current_capture"
    elif mutation == "missing_observed":
        value["observation"]["observed_at"] = None
    elif mutation == "same_day":
        value["date_from"] = "2026-10-20"
    elif mutation == "invalid_tz":
        value["timezone"] = "not/a-real-zone"
    elif mutation == "nonexistent_midnight":
        value["timezone"] = "Pacific/Apia"
        value["date_from"] = "2011-12-30"
        value["date_to"] = "2011-12-30"
        value["as_of"] = "2011-12-29T00:00:00.000000Z"
        value["captured_at"] = value["as_of"]
        value["scenario"]["days"] = [{**value["scenario"]["days"][0], "date": "2011-12-30"}]
    else:
        value["date_from"] = "9999-12-31"
        value["date_to"] = "9999-12-31"
        value["scenario"]["days"] = [{**value["scenario"]["days"][0], "date": "9999-12-31"}]
    with pytest.raises(ValidationError):
        InventorySource.model_validate(value)


def test_zero_order_alternative_is_a_complete_indivisible_candidate():
    value = make_source()
    value["candidates"].append(candidate("no-purchase", []))
    refresh(value)
    assert len(InventorySource.model_validate(value).candidates[1].orders) == 0


@pytest.mark.parametrize("fraction", [{"numerator": "2", "denominator": "4"}, {"numerator": "0", "denominator": "0"}, {"numerator": "-0", "denominator": "1"}, {"numerator": 0, "denominator": "1"}])
def test_fraction_outputs_are_exact_reduced_and_strict(fraction):
    with pytest.raises(ValidationError):
        ExactFraction.model_validate(fraction)


def test_dst_business_day_has_actual_23_hours_without_fixed_utc_day():
    start, end = day_bounds("2027-03-14", "America/New_York")
    assert (start, end) == ("2027-03-14T05:00:00.000000Z", "2027-03-15T04:00:00.000000Z")
    assert rational(0) == {"numerator": "0", "denominator": "1"}
