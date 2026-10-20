"""Deterministic, standard-library-only registration record count forecasting.

The fixed point recipe averages four observed occurrences of the target weekday.
Benchmarks and metrics follow the rolling-origin principles in FPP3 chapter 5:
https://otexts.com/fpp3/toolbox.html . The absolute-error intervals below are a
specified engineering recipe, not a claim of guaranteed temporal coverage.
"""

import hashlib
import json
import math
from datetime import date, timedelta
from pathlib import Path

RECIPES = ("weekday_mean_4w", "seasonal_naive_7d", "rolling_mean_7d", "rolling_mean_28d")
RUNTIME_FILES = ("forecast_contract.py", "forecast_model.py", "forecast_config.py", "forecast_server.py")


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def implementation_hashes():
    return {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest() for name in RUNTIME_FILES}


def point_forecast(values, training_days, horizon_days, recipe="weekday_mean_4w"):
    """Use only the observed prefix; never feed a forecast back as an observation."""
    if recipe not in RECIPES or type(training_days) is not int or training_days < 28 or training_days > len(values) or type(horizon_days) is not int or not 1 <= horizon_days <= 14:
        raise ValueError("无效固定算法或历史窗口")
    if recipe == "weekday_mean_4w":
        return [sum(values[index] for index in range(training_days - 28, training_days) if index % 7 == (training_days + lead - 1) % 7) / 4.0 for lead in range(1, horizon_days + 1)]
    if recipe == "seasonal_naive_7d":
        return [float(values[training_days - 7 + (lead - 1) % 7]) for lead in range(1, horizon_days + 1)]
    window = 7 if recipe == "rolling_mean_7d" else 28
    return [sum(values[training_days - window : training_days]) / float(window)] * horizon_days


def _metrics(pairs):
    errors = [abs(pair["actual"] - pair["point"]) for pair in pairs]
    numerator = math.fsum(errors)
    denominator = sum(pair["actual"] for pair in pairs)
    zero_scales = sum(pair["scale"] == 0 for pair in pairs)
    return {
        "n": len(pairs),
        "mae": numerator / len(pairs),
        "rmse": math.sqrt(math.fsum(error * error for error in errors) / len(pairs)),
        "wape": numerator / denominator if denominator else None,
        "wape_numerator_abs_error": numerator,
        "wape_denominator_actual": denominator,
        "wape_undefined_reason": None if denominator else "zero_actual_sum",
        "mase": None if zero_scales else math.fsum(error / pair["scale"] for error, pair in zip(errors, pairs, strict=True)) / len(pairs),
        "mase_scaled_pairs": len(pairs) - zero_scales,
        "mase_zero_scale_pairs": zero_scales,
        "mase_undefined_reason": "zero_origin_scale" if zero_scales else None,
    }


def _interval_metrics(pairs):
    return {
        "covered_count": sum(pair["lower"] <= pair["actual"] <= pair["upper"] for pair in pairs),
        "evaluated_count": len(pairs),
        "empirical_coverage": sum(pair["lower"] <= pair["actual"] <= pair["upper"] for pair in pairs) / len(pairs),
        "unique_target_dates": len({pair["date"] for pair in pairs}),
        "mean_width": math.fsum(pair["upper"] - pair["lower"] for pair in pairs) / len(pairs),
        "calibration_n_min": min(pair["calibration_n"] for pair in pairs),
        "calibration_n_max": max(pair["calibration_n"] for pair in pairs),
    }


def forecast_values(observations, horizon_days):
    """Return the entire fixed numeric evidence, with no framework or data access."""
    if type(horizon_days) is not int or horizon_days not in (7, 14) or not isinstance(observations, list) or not 112 <= len(observations) <= 366:
        raise ValueError("须提供112至366个连续日，预测期限仅7或14日")
    dates, values = [], []
    for item in observations:
        if not isinstance(item, dict) or set(item) != {"date", "value"} or not isinstance(item["date"], str):
            raise ValueError("日序列结构无效")
        day = date.fromisoformat(item["date"])
        if day.isoformat() != item["date"] or type(item["value"]) is not int or not 0 <= item["value"] <= 2147483647 or (dates and day != dates[-1] + timedelta(days=1)):
            raise ValueError("日序列须规范、完整且为非负整数，不填补缺日")
        dates.append(day)
        values.append(item["value"])
    try:
        future_dates = [(dates[-1] + timedelta(days=lead)).isoformat() for lead in range(1, horizon_days + 1)]
    except OverflowError as exc:
        raise ValueError("预测日期超出有效公历范围") from exc
    count = len(values)
    # Every cached point sees its own prefix only, including calibration origins.
    cache = {recipe: {t: point_forecast(values, t, horizon_days, recipe) for t in range(28, count + 1)} for recipe in RECIPES}

    def interval(t, lead):
        # Prior prefix r's h-step target is known iff r+h<=t. In particular,
        # the most recent residual target is the current origin date, never later.
        origins = list(range(max(28, t - lead - 27), t - lead + 1))
        errors = sorted(abs(values[r + lead - 1] - cache["weekday_mean_4w"][r][lead - 1]) for r in origins)
        n = len(errors)
        order = math.ceil((n + 1) * 0.9)
        if n < 20 or order > n:
            raise ValueError("已发生目标的历史误差不足，不能伪造经验区间")
        point, radius = cache["weekday_mean_4w"][t][lead - 1], errors[order - 1]
        return {
            "lower": max(0.0, point - radius),
            "upper": point + radius,
            "calibration_n": n,
            "calibration_order": order,
            "calibration_quantile": radius,
            "calibration_last_target_date": dates[origins[-1] + lead - 1].isoformat(),
        }

    origins = list(range(count - horizon_days - 27, count - horizon_days + 1))
    scales, scale_by_origin = [], {}
    for t in origins:
        scale_sum = sum(abs(values[index] - values[index - 7]) for index in range(7, t))
        scale = scale_sum / float(t - 7)
        scales.append({"origin_date": dates[t - 1].isoformat(), "training_days": t, "lag_pair_count": t - 7, "absolute_difference_sum": scale_sum, "scale": scale})
        scale_by_origin[t] = scale
    all_pairs = {}
    for recipe in RECIPES:
        pairs = []
        for t in origins:
            for lead in range(1, horizon_days + 1):
                pair = {"date": dates[t + lead - 1].isoformat(), "lead_days": lead, "actual": values[t + lead - 1], "point": cache[recipe][t][lead - 1], "scale": scale_by_origin[t]}
                if recipe == "weekday_mean_4w":
                    pair.update(interval(t, lead))
                pairs.append(pair)
        all_pairs[recipe] = pairs
    primary = all_pairs["weekday_mean_4w"]

    def by_lead(pairs):
        return [{"lead_days": lead, "metrics": _metrics([pair for pair in pairs if pair["lead_days"] == lead])} for lead in range(1, horizon_days + 1)]

    return {
        "recipe": "weekday_mean_4w",
        "horizon_days": horizon_days,
        "history_days": count,
        "forecast": [{"date": future_dates[lead - 1], "lead_days": lead, "point": cache["weekday_mean_4w"][count][lead - 1], **interval(count, lead)} for lead in range(1, horizon_days + 1)],
        "backtest": {
            "data_basis": "current_snapshot_retrospective",
            "origin_count": 28,
            "origin_from": dates[origins[0] - 1].isoformat(),
            "origin_to": dates[origins[-1] - 1].isoformat(),
            "horizon_days": horizon_days,
            "forecast_pair_count": len(primary),
            "unique_target_dates": len({pair["date"] for pair in primary}),
            "overlapping_targets": True,
            "primary_metrics": _metrics(primary),
            "primary_by_lead": by_lead(primary),
            "baselines": [{"recipe": recipe, "metrics": _metrics(all_pairs[recipe]), "by_lead": by_lead(all_pairs[recipe])} for recipe in RECIPES[1:]],
            "intervals": {
                **_interval_metrics(primary),
                "nominal_coverage": 0.9,
                "coverage_guarantee": "not_provided",
                "by_lead": [{"lead_days": lead, **_interval_metrics([pair for pair in primary if pair["lead_days"] == lead])} for lead in range(1, horizon_days + 1)],
            },
            "mase_scale": {"lag_days": 7, "method": "origin_prefix_mean_abs_lag7", "origins": scales},
        },
    }


def validate_runtime(runtime) -> None:
    """Bind reviewed source and self-consistent reported deployment versions."""
    import re

    from app.ai.forecast_contract import RECIPE, ForecastRuntime, canonical_json

    runtime = ForecastRuntime.model_validate(runtime).model_dump()
    if runtime["implementation"] != implementation_hashes() or runtime["recipe_digest"] != hashlib.sha256(canonical_json(RECIPE).encode()).hexdigest():
        raise ValueError("统计算法实际源码或固定recipe不一致")
    if set(runtime["engine_versions"]) != {"fastapi", "pydantic"} or any(not re.fullmatch(r"\d+\.\d+\.\d+(?:[A-Za-z0-9.+_-]{0,50})?", item) for item in runtime["engine_versions"].values()):
        raise ValueError("统计服务运行依赖声明无效")
    identity = {key: value for key, value in runtime.items() if key not in {"runtime_digest", "model_version"}}
    digest = hashlib.sha256(canonical_json(identity).encode()).hexdigest()
    if runtime["runtime_digest"] != digest or runtime["model_version"] != "stat-forecast:" + digest:
        raise ValueError("统计服务运行版本绑定不一致")


def validate_analysis_binding(analysis, source, horizon_days: int, instructions_digest: str, model_version: str) -> None:
    """Recompute all fixed numbers; accept differing real deployment Python versions."""
    from app.ai.forecast_contract import ForecastAnalysis, ForecastSource, canonical_json

    analysis = ForecastAnalysis.model_validate(analysis)
    source = ForecastSource.model_validate(source)
    if type(horizon_days) is not int or horizon_days not in (7, 14):
        raise ValueError("预测期限不一致")
    validate_runtime(analysis.local_runtime)
    if analysis.local_runtime.model_version != model_version:
        raise ValueError("所请求模型与统计服务实际运行版本不一致")
    expected = {
        "schema_version": "1",
        "source_binding": source.model_dump(exclude={"observations"}),
        **forecast_values([item.model_dump() for item in source.observations], horizon_days),
        "instructions_digest": instructions_digest,
    }
    actual = analysis.model_dump(exclude={"local_runtime"})
    if canonical_json(actual) != canonical_json(expected):
        raise ValueError("固定统计预测、日期、来源、区间、回测或分母不一致")
