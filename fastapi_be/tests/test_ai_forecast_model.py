"""Independent synthetic oracles prove the actual rolling-origin numeric recipe."""

import copy
import hashlib
import math
from datetime import date, timedelta

import pytest
from pydantic import ValidationError

from app.ai.forecast_config import runtime_descriptor, runtime_from_descriptor
from app.ai.forecast_contract import ForecastAnalysis, ForecastSource, canonical_json
from app.ai.forecast_model import forecast_values, point_forecast, validate_analysis_binding, validate_runtime
from tests.test_ai_forecast_contract import make_source


def analysis_for(source=None, horizon=14):
    source = ForecastSource.model_validate(source or make_source())
    descriptor = runtime_descriptor()
    digest = hashlib.sha256(b"synthetic-complete-system-and-feature-prompt").hexdigest()
    value = {
        "schema_version": "1",
        "source_binding": source.model_dump(exclude={"observations"}),
        **forecast_values([item.model_dump() for item in source.observations], horizon),
        "local_runtime": runtime_from_descriptor(descriptor),
        "instructions_digest": digest,
    }
    return value, source, digest, descriptor["model_version"]


@pytest.mark.parametrize("horizon", [7, 14])
def test_weekly_periodic_series_is_exact_but_zero_mase_scale_is_undefined(horizon):
    source = make_source(values=[index % 7 for index in range(112)])
    result = forecast_values(source["observations"], horizon)
    assert [row["point"] for row in result["forecast"]] == [float(index % 7) for index in range(112, 112 + horizon)]
    assert all(row["lower"] == row["point"] == row["upper"] and row["calibration_n"] == 28 and row["calibration_order"] == 27 for row in result["forecast"])
    metrics = result["backtest"]["primary_metrics"]
    assert metrics["mae"] == metrics["rmse"] == metrics["wape"] == 0.0
    assert metrics["mase"] is None and metrics["mase_scaled_pairs"] == 0 and metrics["mase_zero_scale_pairs"] == 28 * horizon
    assert result["backtest"]["intervals"]["empirical_coverage"] == 1.0
    assert result["backtest"]["forecast_pair_count"] == 28 * horizon
    assert result["backtest"]["unique_target_dates"] == horizon + 27
    assert result["backtest"]["overlapping_targets"] is True


def test_all_zero_series_reports_undefined_denominators_without_nan_or_invented_success():
    result = forecast_values(make_source(values=[0] * 112)["observations"], 14)
    for metrics in [result["backtest"]["primary_metrics"], *(item["metrics"] for item in result["backtest"]["baselines"])]:
        assert metrics["mae"] == metrics["rmse"] == 0.0
        assert metrics["wape"] is None and metrics["wape_denominator_actual"] == 0 and metrics["wape_undefined_reason"] == "zero_actual_sum"
        assert metrics["mase"] is None and metrics["mase_undefined_reason"] == "zero_origin_scale"
    assert "NaN" not in canonical_json(result)


def test_linear_series_closed_form_proves_lead_errors_intervals_scales_and_baselines():
    n, horizon = 112, 14
    observations = make_source(values=list(range(n)))["observations"]
    result = forecast_values(observations, horizon)
    # Four prior weekdays have offsets 7/14/21/28, hence mean target-17.5.
    assert [item["point"] for item in result["forecast"]] == [94.5 + (lead - 1) % 7 for lead in range(1, 15)]
    errors = [17.5 if lead <= 7 else 24.5 for lead in range(1, 15)]
    assert [item["calibration_quantile"] for item in result["forecast"]] == errors
    backtest = result["backtest"]
    assert backtest["origin_from"] == observations[70]["date"] and backtest["origin_to"] == observations[97]["date"]
    assert backtest["data_basis"] == "current_snapshot_retrospective"
    expected_numerator = 28 * sum(errors)
    expected_denominator = sum(sum(range(t, t + 14)) for t in range(71, 99))
    metrics = backtest["primary_metrics"]
    assert metrics["mae"] == 21.0
    assert metrics["rmse"] == math.sqrt(sum(error * error for error in errors) / 14)
    assert metrics["wape_numerator_abs_error"] == expected_numerator
    assert metrics["wape_denominator_actual"] == expected_denominator
    assert metrics["wape"] == expected_numerator / expected_denominator
    assert metrics["mase"] == 3.0 and metrics["mase_zero_scale_pairs"] == 0
    for scale in backtest["mase_scale"]["origins"]:
        assert scale["scale"] == 7.0 and scale["absolute_difference_sum"] == scale["lag_pair_count"] * 7
    assert [row["metrics"]["mae"] for row in backtest["baselines"]] == [10.5, 10.5, 21.0]
    for row in result["forecast"]:
        assert row["calibration_last_target_date"] == observations[-1]["date"]
        assert row["date"] == (date.fromisoformat(observations[-1]["date"]) + timedelta(days=row["lead_days"])).isoformat()


def test_irregular_sequence_matches_independent_prefix_only_interval_oracle():
    values = [(index * 37 + (index % 11) ** 3) % 113 for index in range(160)]
    observations = make_source(values=values)["observations"]
    result = forecast_values(observations, 14)
    for row in result["forecast"]:
        h = row["lead_days"]
        prior = range(160 - h - 27, 160 - h + 1)
        errors = []
        for prefix in prior:
            target = prefix + h - 1
            training = [(index, value) for index, value in enumerate(values[:prefix])][-28:]
            estimate = sum(value for index, value in training if index % 7 == target % 7) / 4
            errors.append(abs(values[target] - estimate))
        q = sorted(errors)[26]
        assert row["calibration_quantile"] == q
        assert row["lower"] == max(0, row["point"] - q)
        assert row["upper"] == row["point"] + q
    # Changing observations after a prefix cannot change any prefix forecast.
    changed = values[:90] + [2147483647] * 70
    for recipe in ("weekday_mean_4w", "seasonal_naive_7d", "rolling_mean_7d", "rolling_mean_28d"):
        assert point_forecast(changed, 90, 14, recipe) == point_forecast(values, 90, 14, recipe)


def test_zero_scale_at_any_origin_makes_aggregate_mase_null_instead_of_selecting_subset():
    values = [1] * 80 + [2] * 32
    result = forecast_values(make_source(values=values)["observations"], 14)
    metrics = result["backtest"]["primary_metrics"]
    assert 0 < metrics["mase_zero_scale_pairs"] < metrics["n"]
    assert metrics["mase_scaled_pairs"] + metrics["mase_zero_scale_pairs"] == metrics["n"]
    assert metrics["mase"] is None


@pytest.mark.parametrize("horizon", [True, "7", 7.0, 0, 1, 28])
def test_kernel_rejects_uncontracted_horizons(horizon):
    with pytest.raises(ValueError):
        forecast_values(make_source()["observations"], horizon)


def test_overflowing_forecast_dates_rejected_without_guessing_calendar():
    observations = make_source(start=date(9999, 9, 11))["observations"]
    with pytest.raises(ValueError, match="公历"):
        forecast_values(observations, 14)


def test_complete_analysis_recomputes_and_accepts_honest_foreign_python_dependency_versions():
    value, source, digest, _ = analysis_for()
    runtime = value["local_runtime"]
    runtime["python_version"] = "3.12.13"
    runtime["engine_versions"] = {"fastapi": "0.115.0", "pydantic": "2.10.0"}
    runtime["runtime_digest"] = hashlib.sha256(canonical_json({key: item for key, item in runtime.items() if key not in {"runtime_digest", "model_version"}}).encode()).hexdigest()
    runtime["model_version"] = "stat-forecast:" + runtime["runtime_digest"]
    validate_runtime(runtime)
    validate_analysis_binding(ForecastAnalysis.model_validate(value), source, 14, digest, runtime["model_version"])


@pytest.mark.parametrize("change", ["point", "interval", "denominator", "baseline", "scale", "coverage", "source", "clock", "date", "digest", "runtime", "recipe", "python", "model", "extra"])
def test_gateway_binding_rejects_plausible_fabrication_in_every_numeric_and_identity_layer(change):
    value, source, digest, model = analysis_for()
    value = copy.deepcopy(value)
    if change == "point":
        value["forecast"][0]["point"] += 0.01
    elif change == "interval":
        value["forecast"][0]["lower"] += 0.01
    elif change == "denominator":
        value["backtest"]["primary_metrics"]["wape_denominator_actual"] += 1
    elif change == "baseline":
        value["backtest"]["baselines"][0]["metrics"]["mae"] += 1
    elif change == "scale":
        value["backtest"]["mase_scale"]["origins"][0]["absolute_difference_sum"] += 1
    elif change == "coverage":
        value["backtest"]["intervals"]["covered_count"] -= 1
    elif change == "source":
        value["source_binding"]["registration_digest"] = "a" * 64
    elif change == "clock":
        value["source_binding"]["timezone"] = "UTC"
    elif change == "date":
        value["forecast"][0]["date"] = "2024-04-23"
    elif change == "digest":
        value["instructions_digest"] = "b" * 64
    elif change == "runtime":
        value["local_runtime"]["implementation"]["forecast_model.py"] = "c" * 64
    elif change == "recipe":
        value["local_runtime"]["recipe_digest"] = "d" * 64
    elif change == "python":
        value["local_runtime"]["python_version"] = "3.12.13"
    elif change == "model":
        model = "stat-forecast:" + "e" * 64
    else:
        value["forecast"][0]["probability"] = 0.9
    with pytest.raises((ValidationError, ValueError)):
        validate_analysis_binding(value, source, 14, digest, model)


@pytest.mark.parametrize("value", [True, "1.2", float("nan"), float("inf")])
def test_numeric_schema_rejects_booleans_strings_and_nonfinite(value):
    analysis, _, _, _ = analysis_for()
    analysis["forecast"][0]["point"] = value
    with pytest.raises(ValidationError):
        ForecastAnalysis.model_validate(analysis)


def test_all_rolling_origins_match_independent_calendar_oracle_with_only_available_targets():
    values = [(index * 19 + index % 13 * 5) % 73 + index // 9 for index in range(143)]
    observations = make_source(values=values)["observations"]
    horizon = 14
    backtest = forecast_values(observations, horizon)["backtest"]
    recipes = ["weekday_mean_4w", "seasonal_naive_7d", "rolling_mean_7d", "rolling_mean_28d"]
    errors_by_recipe = {name: [] for name in recipes}
    actual_sum, covered, widths, scaled_errors = 0, 0, [], []

    def estimate(prefix, target_date, recipe):
        prior = observations[:prefix]
        if recipe == "weekday_mean_4w":
            weekdays = [row["value"] for row in prior[-28:] if date.fromisoformat(row["date"]).weekday() == target_date.weekday()]
            assert len(weekdays) == 4
            return sum(weekdays) / 4
        if recipe == "seasonal_naive_7d":
            return next(row["value"] for row in reversed(prior[-7:]) if date.fromisoformat(row["date"]).weekday() == target_date.weekday())
        width = 7 if recipe == "rolling_mean_7d" else 28
        return sum(row["value"] for row in prior[-width:]) / width

    for training_count in range(102, 130):
        origin_date = date.fromisoformat(observations[training_count - 1]["date"])
        scale = sum(abs(values[index] - values[index - 7]) for index in range(7, training_count)) / (training_count - 7)
        for lead in range(1, 15):
            target = origin_date + timedelta(days=lead)
            actual = values[training_count + lead - 1]
            actual_sum += actual
            for recipe in recipes:
                error = abs(actual - estimate(training_count, target, recipe))
                errors_by_recipe[recipe].append(error)
                if recipe == "weekday_mean_4w":
                    scaled_errors.append(error / scale)
            available = []
            for old_training in range(28, training_count):
                old_origin = date.fromisoformat(observations[old_training - 1]["date"])
                old_target = old_origin + timedelta(days=lead)
                if old_target <= origin_date:
                    old_actual = values[old_training + lead - 1]
                    available.append(abs(old_actual - estimate(old_training, old_target, "weekday_mean_4w")))
            assert len(available) >= 28
            q = sorted(available[-28:])[26]
            point = estimate(training_count, target, "weekday_mean_4w")
            low, high = max(0, point - q), point + q
            covered += low <= actual <= high
            widths.append(high - low)
    primary = backtest["primary_metrics"]
    for metrics, recipe in [(primary, recipes[0]), *((row["metrics"], row["recipe"]) for row in backtest["baselines"])]:
        errors = errors_by_recipe[recipe]
        assert metrics["n"] == 392
        assert metrics["mae"] == pytest.approx(sum(errors) / 392, abs=1e-12)
        assert metrics["rmse"] == pytest.approx(math.sqrt(sum(error**2 for error in errors) / 392), abs=1e-12)
        assert metrics["wape_denominator_actual"] == actual_sum
        assert metrics["wape"] == pytest.approx(sum(errors) / actual_sum, abs=1e-12)
    assert primary["mase"] == pytest.approx(sum(scaled_errors) / 392, abs=1e-12)
    intervals = backtest["intervals"]
    assert intervals["covered_count"] == covered
    assert intervals["empirical_coverage"] == covered / 392
    assert intervals["mean_width"] == pytest.approx(sum(widths) / 392, abs=1e-12)
    assert intervals["unique_target_dates"] == 41
