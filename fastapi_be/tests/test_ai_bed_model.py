"""Independent hand-computable oracles for fixed physical-bed math and binding."""

import copy
import uuid
from datetime import date, datetime, timedelta
from fractions import Fraction

import pytest

from app.ai.bed_config import runtime_descriptor, runtime_from_descriptor
from app.ai.bed_contract import TARGETS, BedSource, canonical_json, hash_content, rational
from app.ai.bed_model import compute_bed, compute_boundary_pressure, compute_capacity_day, forecast_target, generation_result_for_analysis, validate_analysis_binding
from tests.test_ai_bed_contract import make_source, refresh_manifest


def runtime():
    return runtime_from_descriptor(runtime_descriptor())


def analyze(value, horizon=7):
    return compute_bed(value, horizon, "a" * 64, runtime())


def clone_capacity(value, index=0):
    item = copy.deepcopy(value["capacity_intervals"][index])
    identifier = str(uuid.uuid5(uuid.NAMESPACE_URL, "clone:" + item["ref"]["source_id"]))
    digest = hash_content([identifier, "clone"])
    item["ref"] = {**item["ref"], "source_record_id": identifier, "source_id": f"bed_capacity_interval:{identifier}:{digest[:12]}", "content_hash": digest}
    value["capacity_intervals"].append(item)
    value["member_manifest"].append({**item["ref"], "status": "published", "eligible": True, "selection": "confirmed", "selection_basis_hash": hash_content("clone-reviewed")})
    refresh_manifest(value)
    return item


@pytest.mark.parametrize("horizon,pairs,unique", [(7, 196, 34), (14, 392, 41)])
def test_weekly_constant_has_zero_error_but_undefined_seasonal_mase(horizon, pairs, unique):
    analysis = analyze(make_source(), horizon)
    target = analysis.targets[0]
    assert target.status == "complete"
    assert target.forecast[0].point.fraction() == 12
    assert target.forecast[7 if horizon == 14 else 0].point.fraction() == 12
    backtest = target.backtest
    assert backtest.forecast_pair_count == pairs and backtest.unique_target_dates == unique
    assert backtest.primary.metrics.mae.fraction() == 0
    assert backtest.primary.metrics.wape.fraction() == 0
    assert backtest.primary.metrics.mase is None and backtest.primary.metrics.zero_scale_pairs == pairs
    assert backtest.interval_metrics.empirical_coverage.fraction() == 1
    assert backtest.historical_as_of_replay is False
    for row in backtest.primary.pairs:
        assert row.calibration_last_target_date <= row.origin_date < row.target_date


def test_ramp_exact_manual_point_error_and_origin_scaled_metrics():
    values = list(range(112))
    dates = [(date(2025, 1, 1) + timedelta(days=i)).isoformat() for i in values]
    evidence = forecast_target(values, dates, 14, "UTC")
    points = evidence["forecast"]
    assert points[0]["point"] == rational(Fraction(189, 2))
    assert points[6]["point"] == rational(Fraction(201, 2))
    assert points[7]["point"] == points[0]["point"]
    assert points[0]["calibration_radius"] == rational(Fraction(35, 2))
    assert points[7]["calibration_radius"] == rational(Fraction(49, 2))
    metrics = evidence["backtest"]["primary"]["metrics"]
    assert metrics["mae"] == rational(21)
    assert metrics["mse"] == rational(Fraction(1813, 4))
    assert metrics["wape"] == rational(Fraction(3, 13))
    assert metrics["mase"] == rational(3)
    assert evidence["backtest"]["primary"]["by_lead"][0]["metrics"]["mae"] == rational(Fraction(35, 2))


def test_all_zero_denominators_are_null_and_actual_zero_is_preserved():
    value = make_source(values=[0] * 112)
    value["capacity_intervals"][-1]["operational_total_beds"]["value"] = 0
    analysis = analyze(value)
    target = analysis.targets[0]
    assert target.observed_sum == "0" and target.last_day_value == 0 and target.last_eligible_observation.value == 0
    assert target.backtest.primary.metrics.wape is None
    assert target.backtest.primary.metrics.wape_undefined_reason == "zero_actual_sum"
    assert target.backtest.primary.metrics.mase is None
    pressure = analysis.future_pressure[0]
    assert pressure.operational_total_beds == 0 and pressure.point_relation == "equal"
    assert pressure.point_minus_capacity.fraction() == 0 and pressure.point_to_capacity_ratio is None
    assert pressure.ratio_undefined_reason == "zero_capacity"


def test_one_unknown_flow_axis_does_not_erase_other_four_complete_targets():
    value = make_source()
    value["flow_observations"][0]["discharge_events"] = {"value": None, "absent_reason": "unknown"}
    analysis = analyze(value)
    assert [item.status for item in analysis.targets] == ["complete", "complete", "input_unknown", "complete", "complete"]
    assert analysis.targets[2].forecast is None and analysis.targets[2].observed_sum is None
    assert len(analysis.targets[2].missing_days) == 1
    assert analysis.capacity_days[0].ratio_undefined_reason == "discharge_unknown"
    assert analysis.capacity_days[1].local_discharge_events_per_mean_operational_bed is not None


def test_last_unknown_census_keeps_previous_eligible_fact_and_actual_last_null():
    value = make_source()
    value["census_observations"][-1]["occupied_beds"] = {"value": None, "absent_reason": "not_recorded"}
    analysis = analyze(value)
    target = analysis.targets[0]
    assert target.last_day_value is None and target.forecast is None and target.observed_sum is None
    assert target.last_eligible_observation.date == value["days"][-2]["date"]
    assert target.last_eligible_observation.value == 17
    assert analysis.primary_census_status == "input_unknown" and analysis.targets[1].forecast is not None
    assert analysis.future_pressure[0].status == "forecast_unknown" and analysis.future_pressure[0].capacity_status == "known"


def test_global_gate_does_not_invent_missing_daily_originals():
    value = make_source()
    value["target_coverage"][0]["same_scope_confirmed"] = "unknown"
    target = analyze(value).targets[0]
    assert target.target_gate_reasons == ["scope_not_confirmed"]
    assert target.missing_days == [] and target.eligible_day_count == 112
    assert target.last_eligible_observation.value == 18 and target.last_day_value is None
    assert target.forecast is None


def test_mixed_methods_are_explicit_global_unknown_not_a_favourable_subseries():
    value = make_source()
    value["census_observations"][0]["method"] = "external_register"
    target = analyze(value).targets[0]
    assert target.target_gate_reasons == ["mixed_methods"] and target.eligible_day_count == 112
    assert target.forecast is None and target.method is None


def test_capacity_exact_microseconds_beyond_js_safe_integer_and_dst_day():
    source = BedSource.model_validate(make_source(start="2025-11-17", timezone="America/New_York", values=[12] * 112))
    value = source.model_dump()
    interval = value["capacity_intervals"][-2]
    interval["operational_total_beds"]["value"] = 2147483647
    source = BedSource.model_validate(value)
    day = source.days[-1]
    assert day.date == "2026-03-08"
    proof = compute_capacity_day(source, day, discharge=12)
    assert proof["day_duration_us"] == str(23 * 3600 * 1000000)
    assert proof["total_bed_microseconds"] == str(2147483647 * 23 * 3600 * 1000000)
    assert int(proof["total_bed_microseconds"]) > 9007199254740991
    assert proof["mean_operational_beds"] == rational(2147483647)
    assert proof["local_discharge_events_per_mean_operational_bed"] == rational(Fraction(12, 2147483647))


def test_partial_capacity_never_treats_missing_remainder_as_zero():
    value = make_source()
    value["capacity_intervals"][0]["end_at"] = "2025-09-01T12:00:00.000000Z"
    source = BedSource.model_validate(value)
    proof = compute_capacity_day(source, source.days[0], discharge=12)
    assert proof["status"] == "partial" and proof["known_bed_microseconds"] == str(20 * 12 * 3600 * 1000000)
    assert proof["unknown_duration_us"] == str(12 * 3600 * 1000000)
    assert proof["total_bed_microseconds"] is None and proof["local_discharge_events_per_mean_operational_bed"] is None


def test_two_adjacent_actual_capacity_segments_have_exact_weighted_mean():
    value = make_source()
    new = clone_capacity(value)
    value["capacity_intervals"][0]["end_at"] = new["start_at"] = "2025-09-01T12:00:00.000000Z"
    value["capacity_intervals"][0]["operational_total_beds"]["value"] = 10
    source = BedSource.model_validate(value)
    proof = compute_capacity_day(source, source.days[0], discharge=3)
    assert proof["status"] == "complete" and proof["mean_operational_beds"] == rational(15)
    assert proof["local_discharge_events_per_mean_operational_bed"] == rational(Fraction(1, 5))


def test_same_value_overlap_remains_conflict_and_readiness_unknown_keeps_original():
    value = make_source()
    clone_capacity(value)
    source = BedSource.model_validate(value)
    proof = compute_capacity_day(source, source.days[0])
    assert proof["status"] == "unknown" and proof["segments"][0]["status"] == "conflict"
    assert proof["segments"][0]["reasons"] == ["unresolved_capacity_overlap"]
    value = make_source()
    value["capacity_intervals"][0]["staff_readiness"] = "unknown"
    source = BedSource.model_validate(value)
    assert source.capacity_intervals[0].operational_total_beds.value == 20
    proof = compute_capacity_day(source, source.days[0])
    assert proof["segments"][0]["reasons"] == ["staff_readiness_not_confirmed"]
    assert proof["total_bed_microseconds"] is None


def test_zero_historical_capacity_has_null_daily_ratio():
    value = make_source()
    value["capacity_intervals"][0]["operational_total_beds"]["value"] = 0
    source = BedSource.model_validate(value)
    proof = compute_capacity_day(source, source.days[0], discharge=0)
    assert proof["status"] == "complete" and proof["total_bed_microseconds"] == "0"
    assert proof["local_discharge_events_per_mean_operational_bed"] is None and proof["ratio_undefined_reason"] == "zero_capacity_integral"


def test_scenario_end_at_census_does_not_substitute_left_limit():
    value = make_source()
    first_forecast_end = (datetime.fromisoformat(value["days"][-1]["day_end_at"].replace("Z", "+00:00")) + timedelta(days=1)).isoformat(timespec="microseconds").replace("+00:00", "Z")
    value["capacity_intervals"][-1]["end_at"] = first_forecast_end
    analysis = analyze(value)
    assert analysis.future_pressure[0].status == "capacity_unknown"
    assert analysis.future_pressure[0].capacity_source_ids == []
    assert analysis.targets[0].forecast[0].point.fraction() == 12


def test_no_capacity_clamp_and_signed_negative_headroom():
    value = make_source()
    value["capacity_intervals"][-1]["operational_total_beds"]["value"] = 1
    analysis = analyze(value)
    assert analysis.targets[0].forecast[0].point.fraction() == 12
    assert analysis.future_pressure[0].point_minus_capacity.fraction() == 11
    assert analysis.future_pressure[0].point_relation == "above"
    value["capacity_intervals"][-1]["operational_total_beds"]["value"] = 30
    source = BedSource.model_validate(value)
    proof = compute_boundary_pressure(source, analysis.targets[0].forecast[0].model_dump(), analysis.targets[0].forecast[0].date, analysis.targets[0].forecast[0].census_at_or_day_end_at)
    assert proof["point_minus_capacity"] == rational(-18)


def test_full_recomputation_rejects_rehashed_or_shape_valid_number_tamper():
    value = make_source()
    analysis = analyze(value)
    native = analysis.model_dump()
    native["targets"][0]["forecast"][0]["point"] = rational(13)
    with pytest.raises(ValueError, match="recompute"):
        validate_analysis_binding(native, value, 7, "a" * 64, analysis.local_runtime.model_version)
    native = analysis.model_dump()
    native["source_binding"]["projection_hash"] = hash_content("forged-but-valid-shape")
    with pytest.raises(ValueError, match="recompute"):
        validate_analysis_binding(native, value, 7, "a" * 64, analysis.local_runtime.model_version)


def test_prompt_only_changes_provenance_and_runtime_is_registered():
    value = make_source()
    first = analyze(value)
    second = compute_bed(value, 7, "b" * 64, first.local_runtime)
    a, b = first.model_dump(), second.model_dump()
    a.pop("instructions_digest")
    b.pop("instructions_digest")
    assert a == b
    assert generation_result_for_analysis(first) == generation_result_for_analysis(second)
    forged = first.local_runtime.model_dump()
    forged["core_sha256"]["bed_model"] = "c" * 64
    identity = {key: item for key, item in forged.items() if key not in {"runtime_digest", "model_version"}}
    forged["runtime_digest"] = hash_content(identity)
    forged["model_version"] = "bed:" + forged["runtime_digest"]
    with pytest.raises(ValueError, match="implementation"):
        compute_bed(value, 7, "a" * 64, forged)


def test_all_unknown_source_has_no_numeric_forecast_and_no_zero_imputation():
    value = make_source(capacity=False)
    value["member_manifest"] = value["census_observations"] = value["flow_observations"] = []
    refresh_manifest(value)
    for day in value["days"]:
        day["census_source_id"] = day["flow_source_id"] = None
        day["census_selection_reason"] = day["flow_selection_reason"] = "missing"
    analysis = analyze(value)
    assert analysis.summary_status == "no_complete_targets"
    assert all(item.forecast is None and item.observed_sum is None and item.last_day_value is None for item in analysis.targets)
    assert analysis.capacity_days[0].known_bed_microseconds is None
    assert all(item.status == "forecast_unknown" and item.capacity_status == "unknown" for item in analysis.future_pressure)


@pytest.mark.parametrize("horizon", [True, 7.0, "7", 1, 15])
def test_horizon_does_not_coerce(horizon):
    with pytest.raises(ValueError):
        compute_bed(make_source(), horizon, "a" * 64, runtime())


def test_complete_analysis_is_larger_than_legacy_text_and_has_exact_no_phi_source_binding():
    value = make_source()
    analysis = analyze(value)
    assert len(canonical_json(analysis.model_dump()).encode()) > 65535
    assert analysis.source_binding.projection_hash == hash_content(BedSource.model_validate(value).model_dump())
    assert set(type(analysis.source_binding).model_fields) < set(value) | {"projection_hash"}
    assert [item.target for item in analysis.targets] == list(TARGETS)


def make_max_source():
    """4096 actual typed roots, including 2998 distinct adjacent capacity parts."""
    values = [2147483647 - (i * 15485863) % 2147483647 for i in range(366)]
    value = make_source(n=366, values=values)
    for i, flow in enumerate(value["flow_observations"]):
        for j, key in enumerate(("admission_events", "discharge_events", "transfer_in_events", "transfer_out_events")):
            flow[key]["value"] = (i * 32452843 + (j + 1) * 49979687) % 2147483648
    for item in value["capacity_intervals"]:
        item["operational_total_beds"]["value"] = 2147483647
    original = value["capacity_intervals"].pop(0)
    value["member_manifest"] = [entry for entry in value["member_manifest"] if entry["source_id"] != original["ref"]["source_id"]]
    start = datetime.fromisoformat(original["start_at"].replace("Z", "+00:00"))
    parts = 2998
    for i in range(parts):
        item = copy.deepcopy(original)
        left = start + timedelta(microseconds=(86400000000 * i) // parts)
        right = start + timedelta(microseconds=(86400000000 * (i + 1)) // parts)
        item["start_at"] = left.isoformat(timespec="microseconds").replace("+00:00", "Z")
        item["end_at"] = right.isoformat(timespec="microseconds").replace("+00:00", "Z")
        identifier = str(uuid.uuid5(uuid.NAMESPACE_URL, "bed-capacity-max-fragment:" + str(i)))
        digest = hash_content(["fragment", i])
        item["ref"] = {
            **item["ref"],
            "source_record_id": identifier,
            "source_id": f"bed_capacity_interval:{identifier}:{digest[:12]}",
            "content_hash": digest,
            "governance_hash": hash_content(["fragment-governance", i]),
        }
        value["capacity_intervals"].append(item)
        value["member_manifest"].append({**item["ref"], "status": "published", "eligible": True, "selection": "confirmed", "selection_basis_hash": hash_content("fragment-reviewed")})
    return refresh_manifest(value)


def test_full_maximum_source_and_all_7840_backtest_pairs_fit_without_truncation():
    value = make_max_source()
    source = BedSource.model_validate(value)
    analysis = analyze(value, 14)
    assert len(source.member_manifest) == 4096 and len(source.capacity_intervals) == 3364
    assert sum(len(day.segments) for day in analysis.capacity_days) == 3363
    assert sum(len(target.backtest.primary.pairs) + sum(len(baseline.pairs) for baseline in target.backtest.baselines) for target in analysis.targets) == 7840
    assert 6000000 < len(canonical_json(source.model_dump()).encode()) < 8 * 1024 * 1024
    assert 4000000 < len(canonical_json(analysis.model_dump()).encode()) < 8 * 1024 * 1024
    assert analysis.summary_status == "all_targets_complete"


def test_pathological_repeated_overlap_proof_rejects_before_oversize_allocation():
    value = make_max_source()
    for item in value["capacity_intervals"]:
        if item["basis_kind"] == "observed_operational_capacity":
            item["start_at"] = value["days"][0]["day_start_at"]
            item["end_at"] = item["observed_at"] = item["recorded_at"] = item["published_at"] = value["days"][-1]["day_end_at"]
    with pytest.raises(ValueError, match="Complete native proof exceeds"):
        analyze(value, 14)
