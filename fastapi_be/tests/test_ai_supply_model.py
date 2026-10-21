"""Hand values and a separate literal recurrence oracle for recorded-quantity models."""

import copy
import random
from datetime import date, timedelta
from fractions import Fraction

import pytest

from app.ai.supply_config import runtime_descriptor, runtime_from_descriptor
from app.ai.supply_contract import MODELS, SupplyAnalysis, SupplySource, canonical_json, hash_content, rational
from app.ai.supply_model import Budget, compute_supply, forecast_target, generation_result_for_analysis, validate_analysis_binding
from tests.test_ai_supply_contract import make_source


def parameters(a=Fraction(1, 2), q=Fraction(1, 2), b=Fraction(1, 2)):
    return {"alpha_size": rational(a), "alpha_interval": rational(q), "beta_occurrence": rational(b)}


def dated(values):
    return [(date(2025, 1, 1) + timedelta(days=index)).isoformat() for index in range(len(values))]


def exact(value):
    return Fraction(int(value["numerator"]), int(value["denominator"]))


def oracle(values, model, a, q, b):
    """Independent event-list recurrence, intentionally no production helpers or budget."""
    data = list(map(Fraction, values))
    positive = [(i + 1, y) for i, y in enumerate(data) if y > 0]
    if model in ("croston", "sba", "tsb"):
        if len(positive) < 2:
            return None
        first, z = positive[0]
        interval = Fraction(first)
        for (previous, _), (current, value) in zip(positive, positive[1:]):
            z = (1 - a) * z + a * value
            interval = (1 - q) * interval + q * (current - previous)
        if model == "croston":
            return [z / interval]
        if model == "sba":
            return [(1 - q / 2) * z / interval]
        probability = Fraction(1, first)
        for value in data[first:]:
            probability = (1 - b) * probability + b * int(value > 0)
        return [probability * z]
    if model == "prefix_mean":
        return [sum(data) / len(data)]
    if model == "last28_mean":
        return [sum(data[-28:]) / 28]
    return data[-7:]


def analyze(value, horizon=7):
    descriptor = runtime_descriptor()
    return compute_supply(value, horizon, "a" * 64, runtime_from_descriptor(descriptor))


@pytest.mark.parametrize("horizon,pairs,distinct", [(7, 196, 34), (14, 392, 41)])
def test_constant_three_targets_exact_metrics_and_overlapping_denominators(horizon, pairs, distinct):
    analysis = analyze(make_source(), horizon)
    assert analysis.planned_pair_count == pairs and analysis.distinct_planned_target_dates == distinct
    assert analysis.selected_model is None
    for target in analysis.targets:
        assert target.status == "complete" and target.observed_sum.fraction() == 224
        for model in target.models:
            assert model.directly_comparable and model.eligible_origin_count == 28
            assert model.eligible_pair_count == pairs and model.distinct_target_dates == distinct
            expected = Fraction(19, 10) if model.model == "sba" else 2
            assert model.prediction.values[0].fraction() == expected
            assert model.metrics.me.fraction() == expected - 2
            assert model.metrics.mse.fraction() == (expected - 2) ** 2
            assert model.metrics.mase is None and model.metrics.mase_undefined_reason == "zero_origin_scale"
            assert model.cumulative_horizon_metrics.mase_undefined_reason == "not_applicable_to_cumulative"
            assert model.cumulative_horizon_metrics.mae.fraction() == horizon * abs(expected - 2)


def test_hand_computed_first_positive_elapsed_and_observed_zero_decay():
    values = ["0", "4", "0", "0", "8"] + ["0"] * 107
    result = forecast_target(values, dated(values), 14, parameters())
    assert exact(result[0]["prediction"]["values"][0]) == Fraction(12, 5)
    assert exact(result[1]["prediction"]["values"][0]) == Fraction(9, 5)
    assert exact(result[2]["prediction"]["values"][0]) == Fraction(27, 2**110)
    assert result[0]["terminal_state"]["first_positive_day"] == 2
    assert result[0]["terminal_state"]["last_positive_day"] == 5
    assert exact(result[0]["terminal_state"]["interval"]) == Fraction(5, 2)
    # Future days have not been observed: a single fixed rate is repeated, not decayed.
    assert exact(result[2]["horizon_forecast_sum"]) == 14 * Fraction(27, 2**110)


@pytest.mark.parametrize("seed,horizon", [(0, 7), (1, 14), (7, 7), (18, 14)])
def test_all_six_predictions_and_every_rolling_prefix_against_separate_oracle(seed, horizon):
    rng = random.Random(seed)
    values = [str(rng.randrange(1, 20)) if rng.random() < 0.3 else "0" for _ in range(112)]
    a, q, b = Fraction(1, 5), Fraction(1, 10), Fraction(1, 20)
    result = forecast_target(values, dated(values), horizon, parameters(a, q, b))
    for actual, model in zip(result, MODELS, strict=True):
        assert [exact(x) for x in actual["prediction"]["values"]] == oracle(values, model, a, q, b)
        errors, cumulative, scaled = [], [], []
        for fold in actual["rolling_origins"]:
            t = fold["training_days"]
            expected = oracle(values[:t], model, a, q, b)
            assert [exact(x) for x in fold["prediction"]["values"]] == expected
            assert fold["training_digest"] == hash_content({"dates": dated(values)[:t], "original_values": values[:t]})
            origin_errors = [expected[h % len(expected)] - Fraction(values[t + h]) for h in range(horizon)]
            scale = sum(abs(Fraction(values[i]) - Fraction(values[i - 1])) for i in range(1, t)) / (t - 1)
            assert exact(fold["origin_scale"]) == scale
            errors.extend(origin_errors)
            scaled.extend(abs(e) / scale for e in origin_errors)
            cumulative.append(sum(origin_errors))
        metrics = actual["metrics"]
        assert exact(metrics["me"]) == sum(errors) / len(errors)
        assert exact(metrics["mae"]) == sum(map(abs, errors)) / len(errors)
        assert exact(metrics["mse"]) == sum(e * e for e in errors) / len(errors)
        assert exact(metrics["mase"]) == sum(scaled) / len(scaled)
        assert exact(actual["cumulative_horizon_metrics"]["mse"]) == sum(e * e for e in cumulative) / 28


@pytest.mark.parametrize("count", [0, 1])
def test_all_zero_and_single_positive_keep_baseline_values_but_no_intermittent_fit(count):
    values = ["0.000000"] * 112
    if count:
        values[-1] = "3.125000"
    analysis = analyze(make_source(values=values))
    for target in analysis.targets:
        assert target.observed_sum.fraction() == (Fraction(25, 8) if count else 0)
        assert target.zero_days == 112 - count and target.positive_days == count
        for model in target.models[:3]:
            assert model.status == "insufficient_positive_observations" and model.prediction is None
            assert model.metrics is None and not model.directly_comparable
            assert len(model.rolling_origins) == 28 and model.eligible_origin_count == 0
        assert target.models[3].prediction.values[0].fraction() == (Fraction(25, 896) if count else 0)
        if not count:
            assert target.models[3].metrics.wape is None
            assert target.models[3].metrics.wape_undefined_reason == "zero_actual_sum"
            assert target.last_day_value == "0.000000"


def test_late_second_positive_is_usable_now_but_backtest_remains_partial_not_rankable():
    values = ["0"] * 112
    values[0], values[95] = "4", "8"
    result = forecast_target(values, dated(values), 7, parameters())
    for model in result[:3]:
        assert model["status"] == "partial_backtest" and not model["directly_comparable"]
        assert model["eligible_origin_count"] == 10 and model["eligible_pair_count"] == 70
        assert [fold["status"] for fold in model["rolling_origins"][:18]] == ["insufficient_positive_observations"] * 18
    assert result[3]["eligible_origin_count"] == 28


@pytest.mark.parametrize("change,reason", [("quantity", "unknown_quantity"), ("coverage", "coverage_unknown"), ("unit", "unit_mismatch"), ("unit_review", "unit_not_confirmed")])
def test_unknown_one_target_does_not_erase_other_targets_or_mix_units(change, reason):
    value = make_source()
    original = value["observations"][0]
    if change == "quantity":
        original["quantity"] = {"value": None, "absent_reason": "unknown"}
    elif change == "coverage":
        original["coverage"] = "unknown"
    elif change == "unit":
        original["unit_token"] = "f" * 64
        original["quantity"]["value"] = "999"
    else:
        original["unit_review"] = "unknown"
    analysis = analyze(value)
    assert [row.status for row in analysis.targets] == ["input_unknown", "complete", "complete"]
    target = analysis.targets[0]
    assert target.observed_sum is None and target.known_observed_sum.fraction() == 222
    assert target.last_day_value == "2" and target.last_eligible_observation.value == "2"
    assert target.missing_days[0].reasons == [reason]
    assert all(row.prediction is None and row.rolling_origins == [] for row in target.models)
    assert SupplySource.model_validate(value).observations[0].quantity.value == original["quantity"]["value"]


def test_unknown_last_unit_keeps_previous_actual_and_never_aggregates_foreign_quantity():
    value = make_source()
    value["observations"][-3]["unit_token"] = "e" * 64
    value["observations"][-3]["quantity"]["value"] = "123456"
    target = analyze(value).targets[0]
    assert target.last_day_value is None
    assert target.last_eligible_observation.date == value["days"][-2]["date"]
    assert target.known_observed_sum.fraction() == 222


def test_global_scope_gate_does_not_fabricate_daily_missing_originals():
    value = make_source()
    value["target_coverage"][0]["same_scope_confirmed"] = "unknown"
    target = analyze(value).targets[0]
    assert target.target_gate_reasons == ["scope_not_confirmed"] and target.missing_days == []
    assert target.eligible_day_count == 112 and target.last_day_value is None


def test_stock_constraint_is_separate_and_no_inventory_clamp_or_latent_demand_inference():
    value = make_source(values=["0"] * 112)
    for original in value["observations"]:
        original["stock_constraint"] = "full"
    result = analyze(value)
    assert all(row.status == "complete" and row.stock_constrained_days == 112 for row in result.targets)
    assert all(row.models[3].prediction.values[0].fraction() == 0 for row in result.targets)
    explanation = generation_result_for_analysis(result)
    assert "缺货期间实发零不能证明请求零" in "".join(explanation["warnings"])


def test_actual_known_sum_is_none_when_no_eligible_measurement_not_a_measured_zero():
    value = make_source()
    for original in value["observations"]:
        original["quantity"] = {"value": None, "absent_reason": "not_recorded"}
    result = analyze(value)
    assert all(row.known_observed_sum is None and row.observed_sum is None and row.last_eligible_observation is None for row in result.targets)


def test_real_work_and_incremental_proof_budgets_reject_without_partial_output():
    values = ["0", "1"] * 56
    with pytest.raises(ValueError, match="work budget"):
        forecast_target(values, dated(values), 14, parameters(), Budget(max_work=50))
    with pytest.raises(ValueError, match="proof construction"):
        forecast_target(values, dated(values), 14, parameters(), Budget(max_bytes=1024))
    budget = Budget()
    with pytest.raises(ValueError, match="intermediate"):
        budget.mul(Fraction(1 << 150000), Fraction(1 << 150000))
    assert budget.work == 0


@pytest.mark.parametrize("path", ["forecast", "metrics", "fold", "scope", "runtime", "prompt", "horizon"])
def test_full_recomputation_rejects_tampered_math_and_provenance(path):
    source = make_source()
    result = analyze(source)
    altered = copy.deepcopy(result.model_dump())
    model = altered["targets"][0]["models"][0]
    if path == "forecast":
        model["prediction"]["values"][0] = rational(99)
    elif path == "metrics":
        model["metrics"]["mse"] = rational(1)
    elif path == "fold":
        model["rolling_origins"][0]["training_digest"] = "f" * 64
    elif path == "scope":
        altered["source_binding"]["current_membership_digest"] = "e" * 64
    elif path == "runtime":
        altered["local_runtime"]["engine_versions"]["pydantic"] = "1.0.0"
    elif path == "prompt":
        altered["instructions_digest"] = "c" * 64
    else:
        altered["horizon_days"] = 14
    with pytest.raises(ValueError):
        validate_analysis_binding(altered, source, 7, "a" * 64, result.local_runtime.model_version)


def test_valid_full_binding_and_prompt_changes_only_provenance():
    source = make_source()
    first = analyze(source)
    assert validate_analysis_binding(first, source, 7, "a" * 64, first.local_runtime.model_version) == first
    second = compute_supply(source, 7, "b" * 64, first.local_runtime)
    a, b = first.model_dump(), second.model_dump()
    a.pop("instructions_digest")
    b.pop("instructions_digest")
    assert a == b
    assert SupplyAnalysis.model_validate(first.model_dump()) == first
    assert len(canonical_json(first.model_dump()).encode()) < 8 * 1024 * 1024


def test_seasonal_naive_second_week_repeats_observed_last_week():
    values = list(map(str, range(112)))
    result = forecast_target(values, dated(values), 14, parameters())[-1]
    assert [exact(x) for x in result["prediction"]["values"]] == list(map(Fraction, range(105, 112)))
    assert exact(result["horizon_forecast_sum"]) == 2 * sum(range(105, 112))
