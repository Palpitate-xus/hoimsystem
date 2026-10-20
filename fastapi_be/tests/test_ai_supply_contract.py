"""Synthetic, isolated recorded-quantity contract checks; no hospital fixture imports."""

import copy
import uuid
from datetime import date, datetime, timedelta
from fractions import Fraction

import pytest
from pydantic import ValidationError

from app.ai.supply_contract import TARGETS, ExactFraction, Parameters, SupplySource, day_bounds, hash_content, input_policy_digest, integer_text, integer_value, rational, recipe_digest


def uid(value):
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "supply-synthetic:" + str(value)))


def refresh_manifest(value):
    value["member_manifest_hash"] = hash_content(value["member_manifest"])
    return value


def make_source(values=None, count=112, start="2026-01-01", timezone="UTC"):
    values = ["2"] * count if values is None else [str(item) for item in values]
    count = len(values)
    first = date.fromisoformat(start)
    digest = hash_content("synthetic private frozen source")
    unit = hash_content("actual reviewed inventory unit")
    days, observations, manifest = [], [], []
    for index, quantity in enumerate(values):
        day = (first + timedelta(days=index)).isoformat()
        clock_start, clock_end = day_bounds(day, timezone)
        selections = []
        for target in TARGETS:
            identifier = uid(target + day)
            content_hash = hash_content([identifier, quantity])
            ref = {
                "source_record_id": identifier,
                "source_id": f"supply_day:{identifier}:{content_hash[:12]}",
                "kind": "daily_quantity",
                "content_hash": content_hash,
                "governance_hash": hash_content([identifier, "published", 1]),
            }
            observations.append(
                {
                    "ref": ref,
                    "target": target,
                    "date": day,
                    "day_start_at": clock_start,
                    "day_end_at": clock_end,
                    "quantity": {"value": quantity, "absent_reason": None},
                    "unit_token": unit,
                    "original_unit_hash": hash_content("synthetic original unit"),
                    "unit_review": "confirmed",
                    "coverage": "attested_complete",
                    "coverage_basis_hash": hash_content("complete register review"),
                    "method": "direct_tally",
                    "original_scope_hash": hash_content("actual scope"),
                    "external_record_key_hash": None,
                    "stock_constraint": "unknown",
                    "stock_constraint_basis_hash": hash_content("not reviewed"),
                    "observed_at": clock_end,
                    "recorded_at": clock_end,
                    "published_at": clock_end,
                }
            )
            manifest.append({**ref, "status": "published", "eligible": True, "selection": "confirmed", "selection_basis_hash": hash_content("actual reviewed selection")})
            selections.append({"target": target, "source_id": ref["source_id"], "absent_reason": None})
        days.append({"date": day, "day_start_at": clock_start, "day_end_at": clock_end, "selections": selections})
    as_of = days[-1]["day_end_at"]
    return refresh_manifest(
        {
            "schema_version": "supply_source_v1",
            "series_id": uid("series"),
            "source_id": f"supply_series:{uid('series')}:{digest[:12]}",
            "content_hash": digest,
            "governance_hash": hash_content("series active rev1"),
            "profile_id": uid("profile"),
            "profile_content_hash": hash_content("published profile"),
            "profile_governance_hash": hash_content("profile rev1"),
            "rule_id": "supply_recorded_quantity_v1",
            "recipe_digest": recipe_digest(),
            "input_policy_digest": input_policy_digest(),
            "scope": "single_sku_single_scope_single_unit",
            "item_kind": "pharmaceutical",
            "item_token": hash_content("item"),
            "scope_token": hash_content("scope"),
            "unit_token": unit,
            "timezone": timezone,
            "date_from": days[0]["date"],
            "date_to": days[-1]["date"],
            "as_of": as_of,
            "captured_at": as_of,
            "historical_collection_digest": hash_content("whole historical collection"),
            "current_membership_digest": hash_content("current identity membership"),
            "member_manifest_hash": "a" * 64,
            "parameters": {"alpha_size": rational(Fraction(1, 10)), "alpha_interval": rational(Fraction(1, 10)), "beta_occurrence": rational(Fraction(1, 20))},
            "target_coverage": [
                {"target": target, "same_scope_confirmed": "confirmed", "same_definition_confirmed": "confirmed", "same_method_confirmed": "confirmed", "basis_hash": hash_content("review")}
                for target in TARGETS
            ],
            "days": days,
            "member_manifest": manifest,
            "observations": observations,
        }
    )


def test_real_three_target_day_domain_and_quantity_precision_survive():
    value = make_source(values=["0.000000"] * 112)
    source = SupplySource.model_validate(value)
    assert source.model_dump() == value
    assert source.observations[0].quantity.value == "0.000000"
    assert len(source.observations) == 336


@pytest.mark.parametrize("raw", [0, False, 1.25, "-1", "01", "+1", "1e2", "0.0000001", "1000000000000000000", "NaN"])
def test_quantity_rejects_coercion_extra_precision_and_unsupported_domain(raw):
    value = make_source()
    value["observations"][0]["quantity"]["value"] = raw
    with pytest.raises(ValidationError):
        SupplySource.model_validate(value)


@pytest.mark.parametrize(
    "parameter",
    [
        {"numerator": "0", "denominator": "1"},
        {"numerator": "2", "denominator": "1"},
        {"numerator": "2", "denominator": "4"},
        {"numerator": "1", "denominator": "1001"},
        {"numerator": 1, "denominator": "2"},
    ],
)
def test_explicit_reduced_parameters_have_no_hidden_defaults(parameter):
    with pytest.raises(ValidationError):
        Parameters.model_validate({key: parameter for key in ("alpha_size", "alpha_interval", "beta_occurrence")})


@pytest.mark.parametrize("case", ["identity", "manifest", "omitted", "duplicate", "wrong_target", "wrong_day", "calendar", "future_publish", "extra", "bool_eligible", "missing_param"])
def test_whole_original_and_current_manifest_are_closed(case):
    value = make_source()
    if case == "identity":
        value["observations"][0]["ref"]["source_id"] = "supply_day:wrong"
    elif case == "manifest":
        value["member_manifest"][0]["governance_hash"] = "f" * 64
        refresh_manifest(value)
    elif case == "omitted":
        value["observations"].pop()
    elif case == "duplicate":
        value["observations"].append(copy.deepcopy(value["observations"][0]))
    elif case == "wrong_target":
        value["observations"][0]["target"] = TARGETS[1]
    elif case == "wrong_day":
        value["days"][0]["selections"][0]["source_id"] = value["observations"][3]["ref"]["source_id"]
    elif case == "calendar":
        value["days"][0]["date"] = "2026-02-30"
    elif case == "future_publish":
        value["observations"][0]["published_at"] = "2028-01-01T00:00:00.000000Z"
    elif case == "extra":
        value["question"] = "private patient text"
    elif case == "bool_eligible":
        value["member_manifest"][0]["eligible"] = 1
        refresh_manifest(value)
    else:
        value["parameters"].pop("alpha_size")
    with pytest.raises(ValidationError):
        SupplySource.model_validate(value)


def test_unknown_quantity_and_unit_do_not_get_deleted_or_filled():
    value = make_source()
    value["observations"][0]["quantity"] = {"value": None, "absent_reason": "unknown"}
    value["observations"][0]["unit_token"] = None
    value["observations"][0]["unit_review"] = "unknown"
    assert SupplySource.model_validate(value).observations[0].quantity.value is None


@pytest.mark.parametrize("timezone", ["not/real", "../etc/passwd"])
def test_invalid_timezone_is_validation_error(timezone):
    value = make_source()
    value["timezone"] = timezone
    with pytest.raises(ValidationError):
        SupplySource.model_validate(value)


def test_iana_dst_days_use_actual_23_and_25_hour_bounds():
    for day, hours in [("2026-03-08", 23), ("2026-11-01", 25)]:
        start, end = day_bounds(day, "America/New_York")
        assert (datetime.fromisoformat(end.replace("Z", "+00:00")) - datetime.fromisoformat(start.replace("Z", "+00:00"))).total_seconds() == hours * 3600


def test_huge_exact_integers_do_not_change_global_python_string_limit():
    import sys

    original = sys.get_int_max_str_digits()
    value = 10**6000 + 1
    text = integer_text(value)
    assert len(text) == 6001 and integer_value(text) == value
    assert ExactFraction.model_validate({"numerator": text, "denominator": "2"}).fraction() == Fraction(value, 2)
    assert sys.get_int_max_str_digits() == original
    with pytest.raises(ValueError):
        integer_text(1 << 200001)
