"""Synthetic pure public originals; no hospital ORM or settings imports."""

import uuid
from datetime import date, datetime, timedelta

import pytest
from pydantic import ValidationError

from app.ai.bed_contract import INPUT_POLICY, MAX_MEMBERS, RECIPE, TARGETS, BedSource, ExactFraction, Quantity, canonical_json, day_bounds, hash_content, input_policy_digest, recipe_digest


def make_source(n=112, timezone="UTC", start="2025-09-01", values=None, capacity=True):
    start = date.fromisoformat(start)
    days, census, flows, intervals, manifest = [], [], [], [], []
    coverage = [
        {
            "target": target,
            "definition": "occupied_physical_beds_at_boundary_v1" if index == 0 else "ward_physical_day_events_v1",
            "same_scope_confirmed": "confirmed",
            "same_definition_confirmed": "confirmed",
            "same_method_confirmed": "confirmed",
            "basis_hash": hash_content(["coverage", target]),
        }
        for index, target in enumerate(TARGETS)
    ]
    asof = day_bounds(start + timedelta(days=n - 1), timezone)[1]
    asof = (datetime.fromisoformat(asof.replace("Z", "+00:00")) + timedelta(hours=1)).isoformat(timespec="microseconds").replace("+00:00", "Z")

    def ref(kind, token):
        identifier = str(uuid.uuid5(uuid.NAMESPACE_URL, "synthetic-bed:" + token))
        digest = hash_content([kind, token])
        prefix = {"census": "bed_census", "flow_day": "bed_flow_day", "capacity_interval": "bed_capacity_interval"}[kind]
        result = {"source_record_id": identifier, "source_id": f"{prefix}:{identifier}:{digest[:12]}", "kind": kind, "content_hash": digest, "governance_hash": hash_content(["governance", token])}
        manifest.append({**result, "status": "published", "eligible": True, "selection": "confirmed", "selection_basis_hash": hash_content(["selection", token])})
        return result

    def quantity(value):
        return {"value": value, "absent_reason": None if value is not None else "unknown"}

    for index in range(n):
        day = start + timedelta(days=index)
        begin, end = day_bounds(day, timezone)
        common = {
            "business_date": day.isoformat(),
            "observed_at": end,
            "recorded_at": end,
            "published_at": end,
            "method": "direct_tally",
            "coverage": "attested_complete",
            "coverage_basis_hash": hash_content("complete"),
            "original_scope_hash": hash_content("same-private-ward"),
            "external_record_key_hash": None,
        }
        value = values[index] if values is not None else 12 + index % 7
        c = {
            **common,
            "ref": ref("census", "census:" + day.isoformat()),
            "census_at": end,
            "definition": "occupied_physical_beds_at_boundary_v1",
            "boundary_state_confirmed": "confirmed",
            "occupied_beds": quantity(value),
        }
        f = {
            **common,
            "ref": ref("flow_day", "flow:" + day.isoformat()),
            "day_start_at": begin,
            "day_end_at": end,
            "definition": "ward_physical_day_events_v1",
            **{key: quantity(value if key == "discharge_events" else index % 4) for key in ("admission_events", "discharge_events", "transfer_in_events", "transfer_out_events")},
        }
        census.append(c)
        flows.append(f)
        days.append(
            {
                "date": day.isoformat(),
                "day_start_at": begin,
                "day_end_at": end,
                "census_at": end,
                "census_source_id": c["ref"]["source_id"],
                "census_selection_reason": "confirmed",
                "flow_source_id": f["ref"]["source_id"],
                "flow_selection_reason": "confirmed",
                "selection_basis_hash": hash_content("review"),
            }
        )
        if capacity:
            intervals.append(
                {
                    "ref": ref("capacity_interval", "capacity:" + day.isoformat()),
                    "start_at": begin,
                    "end_at": end,
                    "basis_kind": "observed_operational_capacity",
                    "operational_total_beds": quantity(20),
                    "coverage": "attested_complete",
                    "staff_readiness": "confirmed",
                    "equipment_readiness": "confirmed",
                    "isolation_applicability": "confirmed",
                    "capacity_definition": "total_operational_physical_beds_v1",
                    "capacity_basis_hash": hash_content("capacity-reviewed"),
                    "observed_at": end,
                    "recorded_at": end,
                    "published_at": end,
                    "original_scope_hash": hash_content("same-private-ward"),
                }
            )
    if capacity:
        intervals.append(
            {
                **intervals[-1],
                "ref": ref("capacity_interval", "future"),
                "start_at": days[-1]["day_end_at"],
                "end_at": day_bounds(start + timedelta(days=n + 14), timezone)[1],
                "basis_kind": "reviewed_future_scenario",
                "observed_at": None,
                "recorded_at": asof,
                "published_at": asof,
            }
        )
    identifier = str(uuid.uuid5(uuid.NAMESPACE_URL, "synthetic-bed-series"))
    digest = hash_content("private-frozen-series")
    return {
        "schema_version": "bed_source_v1",
        "series_id": identifier,
        "source_id": f"bed_series:{identifier}:{digest[:12]}",
        "content_hash": digest,
        "governance_hash": hash_content("series-published"),
        "rule_id": "bed_physical_daily_v1",
        "recipe_digest": recipe_digest(),
        "input_policy_digest": input_policy_digest(),
        "scope": "single_ward",
        "scope_token": hash_content("private-ward-token"),
        "timezone": timezone,
        "target_definitions_digest": hash_content([{"target": item["target"], "definition": item["definition"]} for item in coverage]),
        "date_from": days[0]["date"],
        "date_to": days[-1]["date"],
        "as_of": asof,
        "captured_at": asof,
        "historical_collection_digest": hash_content("historical-collection"),
        "current_membership_digest": hash_content("stable-membership"),
        "future_scenario_collection_digest": hash_content("reviewed-scenarios"),
        "member_manifest_hash": hash_content(manifest),
        "target_coverage": coverage,
        "days": days,
        "member_manifest": manifest,
        "census_observations": census,
        "flow_observations": flows,
        "capacity_intervals": intervals,
    }


def refresh_manifest(value):
    value["member_manifest_hash"] = hash_content(value["member_manifest"])
    return value


@pytest.mark.parametrize("value", [0, 1, 2147483647, None])
def test_nullable_original_quantity_preserves_zero_and_unknown(value):
    quantity = {"value": value, "absent_reason": None if value is not None else "unknown"}
    assert Quantity.model_validate(quantity).model_dump() == quantity


@pytest.mark.parametrize("value", [False, True, "0", 0.0, -1, 2147483648])
def test_quantities_are_actual_nonnegative_integer_originals(value):
    with pytest.raises(ValidationError):
        Quantity.model_validate({"value": value, "absent_reason": None})


@pytest.mark.parametrize("numerator,denominator", [("0", "1"), ("-1", "4"), ("9007199254740993", "2")])
def test_exact_reduced_fraction_and_big_integer_strings(numerator, denominator):
    assert ExactFraction(numerator=numerator, denominator=denominator).numerator == numerator


@pytest.mark.parametrize("numerator,denominator", [("-0", "1"), ("01", "2"), ("2", "4"), ("0", "2"), ("1", "0"), (0, "1")])
def test_noncanonical_fraction_rejected(numerator, denominator):
    with pytest.raises(ValidationError):
        ExactFraction(numerator=numerator, denominator=denominator)


def test_complete_public_original_contract_has_no_registration_or_patient_fields():
    value = make_source()
    assert BedSource.model_validate(value).model_dump() == value
    encoded = canonical_json(value)
    assert "registration_record_count" not in encoded and "patient_id" not in encoded
    assert RECIPE["input_policy"] == INPUT_POLICY and MAX_MEMBERS == 4096


@pytest.mark.parametrize("mutation", ["manifest", "omitted", "wrong_kind", "future_observation", "naive", "invalid_calendar", "stale_asof", "noncontiguous", "missing_day", "extra"])
def test_original_binding_calendar_and_closed_domain_fail_closed(mutation):
    value = make_source()
    if mutation == "manifest":
        value["member_manifest"][0]["governance_hash"] = hash_content("forged")
    elif mutation == "omitted":
        value["census_observations"].pop()
    elif mutation == "wrong_kind":
        value["census_observations"][0]["ref"]["kind"] = "flow_day"
    elif mutation == "future_observation":
        value["flow_observations"][-1]["observed_at"] = value["days"][-1]["day_start_at"]
    elif mutation == "naive":
        value["census_observations"][0]["observed_at"] = "2025-09-02T00:00:00.000000"
    elif mutation == "invalid_calendar":
        value["days"][0]["date"] = "2025-02-30"
    elif mutation == "stale_asof":
        value["as_of"] = value["captured_at"] = "2026-01-01T12:00:00.000000Z"
    elif mutation == "noncontiguous":
        value["days"][1]["date"] = value["days"][0]["date"]
    elif mutation == "missing_day":
        value["days"].pop()
    else:
        value["private_notes"] = "Never transmit private free text"
    with pytest.raises((ValidationError, ValueError)):
        BedSource.model_validate(value)


def test_unknown_original_is_kept_in_substantive_whole_flow():
    value = make_source()
    value["flow_observations"][0]["discharge_events"] = {"value": None, "absent_reason": "unknown"}
    value["flow_observations"][0]["coverage"] = "unknown"
    assert BedSource.model_validate(value).flow_observations[0].admission_events.value == 0


def test_public_manifest_hash_is_not_private_full_manifest_hash():
    value = make_source()
    value["member_manifest_hash"] = value["content_hash"]
    with pytest.raises(ValidationError):
        BedSource.model_validate(value)


def test_dst_midnights_are_not_assumed_24_hours():
    start, end = day_bounds("2026-03-08", "America/New_York")
    assert start == "2026-03-08T05:00:00.000000Z" and end == "2026-03-09T04:00:00.000000Z"
    with pytest.raises(ValueError):
        day_bounds("2011-12-30", "Pacific/Apia")


def test_late_observation_clock_is_distinct_and_preserved():
    value = make_source()
    original = value["census_observations"][0]
    original["observed_at"] = original["recorded_at"] = original["published_at"] = value["as_of"]
    source = BedSource.model_validate(value)
    assert source.census_observations[0].observed_at != source.census_observations[0].census_at


@pytest.mark.parametrize("timezone,asof", [("Unknown/Invented", None), ("Pacific/Kiritimati", "9999-12-31T23:59:59.999999Z"), ("America/New_York", "1000-01-01T00:00:00.000000Z")])
def test_timezone_and_calendar_extremes_raise_validation_error(timezone, asof):
    value = make_source()
    value["timezone"] = timezone
    if asof is not None:
        value["as_of"] = value["captured_at"] = asof
    with pytest.raises(ValidationError):
        BedSource.model_validate(value)


def test_future_calendar_range_overflow_is_a_value_error():
    with pytest.raises(ValueError):
        day_bounds("9999-12-31", "UTC")
