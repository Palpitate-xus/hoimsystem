"""Independent exact physical-bed statistics and capacity proofs; no data access."""

import hashlib
import re
from datetime import date, datetime, timedelta
from fractions import Fraction
from pathlib import Path

from app.ai.bed_contract import MAX_BYTES, RECIPES, TARGETS, BedAnalysis, BedRuntime, BedSource, canonical_json, day_bounds, hash_content, input_policy_digest, rational, recipe_digest

RUNTIME_FILES = ("bed_contract", "bed_model", "bed_config", "bed_server")
FLOW_FIELDS = ("admission_events", "discharge_events", "transfer_in_events", "transfer_out_events")


def implementation_hashes():
    return {name: hashlib.sha256(Path(__file__).with_name(name + ".py").read_bytes()).hexdigest() for name in RUNTIME_FILES}


def validate_runtime(runtime):
    values = BedRuntime.model_validate(runtime.model_dump() if isinstance(runtime, BedRuntime) else runtime).model_dump()
    if values["core_sha256"] != implementation_hashes() or values["recipe_digest"] != recipe_digest() or values["input_policy_digest"] != input_policy_digest():
        raise ValueError("Bed runtime implementation or fixed recipe/input policy differs")
    versions = values["engine_versions"]
    if set(versions) != {"fastapi", "pydantic", "pydantic-settings", "uvicorn"} or any(
        not re.fullmatch(r"\d+\.\d+\.\d+(?:[A-Za-z0-9.+_-]{0,50})?", value) for value in [values["python_version"], *versions.values()]
    ):
        raise ValueError("Complete independent runtime package identity is required")
    identity = {key: value for key, value in values.items() if key not in {"runtime_digest", "model_version"}}
    digest = hash_content(identity)
    if values["runtime_digest"] != digest or values["model_version"] != "bed:" + digest:
        raise ValueError("Registered model, actual runtime metadata and timezone digest differ")
    return values


def point_forecast(values, t, horizon, recipe):
    if recipe not in RECIPES or type(t) is not int or not 28 <= t <= len(values) or type(horizon) is not int or horizon not in (7, 14):
        raise ValueError("Invalid fixed recipe, observed prefix or horizon")
    if recipe == "weekday_mean_4w":
        return [Fraction(sum(values[i] for i in range(t - 28, t) if i % 7 == (t + h - 1) % 7), 4) for h in range(1, horizon + 1)]
    if recipe == "seasonal_naive_7d":
        return [Fraction(values[t - 7 + (h - 1) % 7]) for h in range(1, horizon + 1)]
    window = 7 if recipe == "rolling_mean_7d" else 28
    return [Fraction(sum(values[t - window : t]), window)] * horizon


def _metric(pairs):
    errors = [abs(row["actual"] - row["point"]) for row in pairs]
    absolute = sum(errors, Fraction())
    squared = sum((error * error for error in errors), Fraction())
    actual = sum(row["actual"] for row in pairs)
    zero = sum(row["scale"] == 0 for row in pairs)
    return {
        "pair_count": len(pairs),
        "unique_target_dates": len({row["target_date"] for row in pairs}),
        "absolute_error_sum": rational(absolute),
        "squared_error_sum": rational(squared),
        "actual_sum": str(actual),
        "mae": rational(absolute / len(pairs)),
        "mse": rational(squared / len(pairs)),
        "wape": rational(absolute / actual) if actual else None,
        "wape_undefined_reason": None if actual else "zero_actual_sum",
        "mase": None if zero else rational(sum((error / row["scale"] for error, row in zip(errors, pairs, strict=True)), Fraction()) / len(pairs)),
        "mase_undefined_reason": "zero_origin_scale" if zero else None,
        "nonzero_scale_pairs": len(pairs) - zero,
        "zero_scale_pairs": zero,
    }


def _interval_metric(pairs):
    covered = sum(row["lower"] <= row["actual"] <= row["upper"] for row in pairs)
    return {
        "covered_count": covered,
        "evaluated_count": len(pairs),
        "empirical_coverage": rational(Fraction(covered, len(pairs))),
        "unique_target_dates": len({row["target_date"] for row in pairs}),
        "mean_width": rational(sum((row["upper"] - row["lower"] for row in pairs), Fraction()) / len(pairs)),
        "nominal_coverage": rational(Fraction(9, 10)),
        "coverage_guarantee": "not_provided",
    }


def forecast_target(values, dates, horizon, timezone):
    """All point, calibration and evaluation prefixes use originals only."""
    n = len(values)
    if type(horizon) is not int or horizon not in (7, 14) or not 112 <= n <= 366 or len(dates) != n or any(type(value) is not int or not 0 <= value <= 2147483647 for value in values):
        raise ValueError("A complete original integer series and fixed horizon are required")
    cache = {recipe: {t: point_forecast(values, t, horizon, recipe) for t in range(28, n + 1)} for recipe in RECIPES}

    def interval(t, h):
        origins = list(range(max(28, t - h - 27), t - h + 1))
        errors = sorted(abs(values[r + h - 1] - cache[RECIPES[0]][r][h - 1]) for r in origins)
        order = (9 * (len(errors) + 1) + 9) // 10
        if len(errors) < 20 or order > len(errors):
            raise ValueError("Insufficient already-observed prior calibration targets")
        point, radius = cache[RECIPES[0]][t][h - 1], errors[order - 1]
        return {
            "lower": max(Fraction(), point - radius),
            "upper": point + radius,
            "calibration_n": len(errors),
            "calibration_order": order,
            "calibration_radius": radius,
            "calibration_last_target_date": dates[origins[-1] + h - 1],
            "calibration_first_origin_date": dates[origins[0] - 1],
        }

    origins = list(range(n - horizon - 27, n - horizon + 1))
    scales, scale_rows = {}, []
    for t in origins:
        total = sum(abs(values[i] - values[i - 7]) for i in range(7, t))
        scales[t] = Fraction(total, t - 7)
        scale_rows.append({"origin_date": dates[t - 1], "training_days": t, "lag_pair_count": t - 7, "absolute_difference_sum": str(total), "scale": rational(scales[t])})
    comparisons, primary = [], None
    for recipe in RECIPES:
        pairs, external = [], []
        for t in origins:
            for h in range(1, horizon + 1):
                row = {
                    "origin_date": dates[t - 1],
                    "training_days": t,
                    "lead_days": h,
                    "target_date": dates[t + h - 1],
                    "actual": values[t + h - 1],
                    "point": cache[recipe][t][h - 1],
                    "scale": scales[t],
                }
                calibrated = interval(t, h) if recipe == RECIPES[0] else None
                if calibrated:
                    row.update(calibrated)
                pairs.append(row)
                external.append(
                    {key: row[key] for key in ("origin_date", "training_days", "lead_days", "target_date", "actual")}
                    | {
                        "point": rational(row["point"]),
                        "origin_scale": rational(row["scale"]),
                        **{
                            key: (rational(calibrated[key]) if key in {"lower", "upper", "calibration_radius"} else calibrated[key]) if calibrated else None
                            for key in ("lower", "upper", "calibration_n", "calibration_order", "calibration_radius", "calibration_last_target_date")
                        },
                    }
                )
        comparisons.append(
            {
                "recipe": recipe,
                "metrics": _metric(pairs),
                "by_lead": [{"lead_days": h, "metrics": _metric([row for row in pairs if row["lead_days"] == h])} for h in range(1, horizon + 1)],
                "pairs": external,
            }
        )
        if recipe == RECIPES[0]:
            primary = pairs
    forecast = []
    last = date.fromisoformat(dates[-1])
    for h in range(1, horizon + 1):
        day = (last + timedelta(days=h)).isoformat()
        calibrated = interval(n, h)
        forecast.append(
            {
                "date": day,
                "lead_days": h,
                "census_at_or_day_end_at": day_bounds(day, timezone)[1],
                "point": rational(cache[RECIPES[0]][n][h - 1]),
                **{key: rational(value) if isinstance(value, Fraction) else value for key, value in calibrated.items()},
            }
        )
    return {
        "forecast": forecast,
        "backtest": {
            "data_basis": "current_snapshot_retrospective",
            "historical_as_of_replay": False,
            "origin_count": 28,
            "horizon_days": horizon,
            "forecast_pair_count": 28 * horizon,
            "unique_target_dates": horizon + 27,
            "overlapping_targets": True,
            "origin_from": dates[origins[0] - 1],
            "origin_to": dates[origins[-1] - 1],
            "primary": comparisons[0],
            "baselines": comparisons[1:],
            "interval_metrics": {**_interval_metric(primary), "by_lead": [{"lead_days": h, **_interval_metric([row for row in primary if row["lead_days"] == h])} for h in range(1, horizon + 1)]},
            "mase_scale": {"lag_days": 7, "method": "origin_prefix_mean_abs_lag7", "origins": scale_rows},
        },
    }


def _day_values(source, target):
    index = TARGETS.index(target)
    originals = {item.ref.source_id: item for item in (source.census_observations if index == 0 else source.flow_observations)}
    values, missing, latest = [], [], None
    methods = set()
    for day in source.days:
        identifier = day.census_source_id if index == 0 else day.flow_source_id
        selection = day.census_selection_reason if index == 0 else day.flow_selection_reason
        original = originals.get(identifier)
        reasons = []
        value = None
        if original is None:
            reasons.append("unresolved_conflict" if selection == "unresolved_conflict" else "missing_selected_original")
        else:
            quantity = original.occupied_beds if index == 0 else getattr(original, FLOW_FIELDS[index - 1])
            if quantity.value is None:
                reasons.append("not_recorded_quantity" if quantity.absent_reason == "not_recorded" else "unknown_quantity")
            if original.coverage != "attested_complete":
                reasons.append("coverage_unknown" if original.coverage == "unknown" else "coverage_incomplete")
            if index == 0 and original.boundary_state_confirmed != "confirmed":
                reasons.append("boundary_not_confirmed")
            if not reasons:
                value = quantity.value
                methods.add(original.method)
                latest = {"date": day.date, "value": value, "source_id": identifier}
        values.append(value)
        if reasons:
            missing.append({"date": day.date, "source_id": identifier, "reasons": reasons})
    return values, missing, latest, methods


def _target(source, target, horizon):
    values, missing, latest, methods = _day_values(source, target)
    review = source.target_coverage[TARGETS.index(target)]
    gates = []
    for field, reason in (("same_scope_confirmed", "scope_not_confirmed"), ("same_definition_confirmed", "definition_not_confirmed"), ("same_method_confirmed", "method_not_confirmed")):
        if getattr(review, field) != "confirmed":
            gates.append(reason)
    if len(methods) > 1:
        gates.append("mixed_methods")
    complete = not missing and not gates
    result = {
        "target": target,
        "status": "complete" if complete else "input_unknown",
        "history_days": len(values),
        "eligible_day_count": sum(value is not None for value in values),
        "target_gate_reasons": gates,
        "missing_days": missing,
        "method": next(iter(methods)) if len(methods) == 1 else None,
        "observed_sum": str(sum(values)) if complete else None,
        "last_eligible_observation": latest,
        "last_day_value": values[-1] if not gates else None,
        "forecast": None,
        "backtest": None,
    }
    if complete:
        result.update(forecast_target(values, [day.date for day in source.days], horizon, source.timezone))
    return result


def _duration(start, end):
    delta = datetime.fromisoformat(end.replace("Z", "+00:00")) - datetime.fromisoformat(start.replace("Z", "+00:00"))
    return delta.days * 86400000000 + delta.seconds * 1000000 + delta.microseconds


def _capacity_reasons(items):
    if not items:
        return ["missing_capacity_interval"]
    if len(items) > 1:
        return ["unresolved_capacity_overlap"]
    item = items[0]
    reasons = []
    if item.operational_total_beds.value is None:
        reasons.append("not_recorded_quantity" if item.operational_total_beds.absent_reason == "not_recorded" else "unknown_quantity")
    if item.coverage != "attested_complete":
        reasons.append("coverage_unknown" if item.coverage == "unknown" else "coverage_incomplete")
    for field in ("staff_readiness", "equipment_readiness", "isolation_applicability"):
        if getattr(item, field) != "confirmed":
            reasons.append(field + "_not_confirmed")
    return reasons


def compute_capacity_day(source, day, basis_kind="observed_operational_capacity", discharge=None):
    start, end = day.day_start_at, day.day_end_at
    intervals = [item for item in source.capacity_intervals if item.basis_kind == basis_kind and item.start_at < end and item.end_at > start]
    starts, ends = {}, {}
    originals = {}
    for item in intervals:
        identifier = item.ref.source_id
        originals[identifier] = item
        starts.setdefault(max(start, item.start_at), set()).add(identifier)
        ends.setdefault(min(end, item.end_at), set()).add(identifier)
    boundaries = sorted({start, end, *starts, *ends})
    active, segments = set(), []
    construction_bytes = 0
    known_duration = unknown_duration = conflict_duration = integral = 0
    for left, right in zip(boundaries, boundaries[1:], strict=False):
        active.difference_update(ends.get(left, ()))
        active.update(starts.get(left, ()))
        duration = _duration(left, right)
        ids = sorted(active)
        reasons = _capacity_reasons([originals[identifier] for identifier in ids])
        known = not reasons
        value = originals[ids[0]].operational_total_beds.value if known else None
        status = "known" if known else "conflict" if len(ids) > 1 else "unknown"
        if known:
            known_duration += duration
            integral += value * duration
        elif status == "conflict":
            conflict_duration += duration
        else:
            unknown_duration += duration
        segment = {
            "start_at": left,
            "end_at": right,
            "duration_us": str(duration),
            "status": status,
            "reasons": reasons,
            "source_ids": ids,
            "operational_total_beds": value,
            "bed_microseconds": str(value * duration) if known else None,
        }
        # Repeated overlap memberships can be quadratic in the number of
        # endpoints. Bound EACH constructed segment immediately; waiting for
        # the whole day can allocate a huge proof before the global cap runs.
        construction_bytes += len(canonical_json(segment).encode()) + 1
        if construction_bytes > MAX_BYTES:
            raise ValueError(f"Capacity day construction exceeds {MAX_BYTES} UTF8 bytes (at least {construction_bytes}); no truncation allowed")
        segments.append(segment)
    total = _duration(start, end)
    complete = known_duration == total
    ratio = Fraction(discharge * total, integral) if complete and integral and discharge is not None else None
    reason = "capacity_unknown" if not complete else "zero_capacity_integral" if not integral else "discharge_unknown" if discharge is None else None
    return {
        "date": day.date,
        "day_start_at": start,
        "day_end_at": end,
        "day_duration_us": str(total),
        "basis_kind": basis_kind,
        "status": "complete" if complete else "partial" if known_duration else "unknown",
        "segments": segments,
        "known_duration_us": str(known_duration),
        "unknown_duration_us": str(unknown_duration),
        "conflict_duration_us": str(conflict_duration),
        "known_bed_microseconds": str(integral) if known_duration else None,
        "total_bed_microseconds": str(integral) if complete else None,
        "mean_operational_beds": rational(Fraction(integral, total)) if complete else None,
        "local_discharge_events_per_mean_operational_bed": rational(ratio) if ratio is not None else None,
        "ratio_undefined_reason": reason,
    }


def compute_boundary_pressure(source, point, day, clock):
    intervals = sorted((item for item in source.capacity_intervals if item.basis_kind == "reviewed_future_scenario" and item.start_at <= clock < item.end_at), key=lambda item: item.ref.source_id)
    reasons = _capacity_reasons(intervals)
    capacity = intervals[0].operational_total_beds.value if not reasons else None
    status = "forecast_unknown" if point is None else "capacity_conflict" if len(intervals) > 1 else "capacity_unknown" if capacity is None else "known"
    result = {
        "date": day,
        "census_at": clock,
        "status": status,
        "capacity_status": "known" if capacity is not None else "conflict" if len(intervals) > 1 else "unknown",
        "capacity_reasons": reasons,
        "capacity_source_ids": [item.ref.source_id for item in intervals],
        "operational_total_beds": capacity,
        "point_minus_capacity": None,
        "lower_minus_capacity": None,
        "upper_minus_capacity": None,
        "point_relation": None,
        "interval_relation": None,
        "point_to_capacity_ratio": None,
        "ratio_undefined_reason": status if status != "known" else "zero_capacity" if capacity == 0 else None,
    }
    if status == "known":
        values = {key: Fraction(int(point[key]["numerator"]), int(point[key]["denominator"])) for key in ("point", "lower", "upper")}
        result.update({key + "_minus_capacity": rational(value - capacity) for key, value in values.items()})
        result["point_relation"] = "below" if values["point"] < capacity else "above" if values["point"] > capacity else "equal"
        lower, upper = values["lower"], values["upper"]
        result["interval_relation"] = "entirely_below" if upper < capacity else "entirely_above" if lower > capacity else "straddles" if lower < capacity < upper else "touches"
        result["point_to_capacity_ratio"] = rational(values["point"] / capacity) if capacity else None
    return result


def compute_bed(source, horizon_days, instructions_digest, local_runtime):
    source = BedSource.model_validate(source.model_dump() if isinstance(source, BedSource) else source)
    if type(horizon_days) is not int or horizon_days not in (7, 14):
        raise ValueError("Fixed horizon must be actual integer seven or fourteen")
    runtime = validate_runtime(local_runtime)
    binding = {
        key: getattr(source, key)
        for key in (
            "series_id",
            "source_id",
            "content_hash",
            "governance_hash",
            "rule_id",
            "recipe_digest",
            "input_policy_digest",
            "member_manifest_hash",
            "historical_collection_digest",
            "current_membership_digest",
            "future_scenario_collection_digest",
        )
    }
    binding["projection_hash"] = hash_content(source.model_dump())
    targets, capacities, pressure = [], [], []
    budget = 0

    def append_bounded(collection, value):
        nonlocal budget
        budget += len(canonical_json(value).encode()) + 1
        if budget > MAX_BYTES:
            raise ValueError(f"Complete native proof exceeds {MAX_BYTES} UTF8 bytes (at least {budget}); no truncation allowed")
        collection.append(value)

    for target in TARGETS:
        append_bounded(targets, _target(source, target, horizon_days))
    discharge_values = _day_values(source, TARGETS[2])[0]
    discharge_gates = targets[2]["target_gate_reasons"]
    for day, discharge in zip(source.days, discharge_values, strict=True):
        append_bounded(capacities, compute_capacity_day(source, day, discharge=None if discharge_gates else discharge))
    forecast = targets[0]["forecast"]
    for index in range(horizon_days):
        future = (date.fromisoformat(source.date_to) + timedelta(days=index + 1)).isoformat()
        append_bounded(pressure, compute_boundary_pressure(source, forecast[index] if forecast else None, future, day_bounds(future, source.timezone)[1]))
    complete = sum(item["status"] == "complete" for item in targets)
    result = BedAnalysis.model_validate(
        {
            "schema_version": "bed_analysis_v1",
            "source_binding": binding,
            "rule_id": source.rule_id,
            "horizon_days": horizon_days,
            "history_days": len(source.days),
            "primary_census_status": targets[0]["status"],
            "targets": targets,
            "capacity_days": capacities,
            "future_pressure": pressure,
            "summary_status": "all_targets_complete" if complete == 5 else "partial_targets" if complete else "no_complete_targets",
            "instructions_digest": instructions_digest,
            "local_runtime": runtime,
        }
    )
    if len(canonical_json(result.model_dump()).encode()) > MAX_BYTES:
        raise ValueError("Complete native result exceeds UTF8 cap; no truncation allowed")
    return result


def validate_analysis_binding(analysis, source, horizon_days, instructions_digest, model_version):
    analysis = BedAnalysis.model_validate(analysis.model_dump() if isinstance(analysis, BedAnalysis) else analysis)
    if analysis.local_runtime.model_version != model_version:
        raise ValueError("Requested model differs from actual bed runtime")
    expected = compute_bed(source, horizon_days, instructions_digest, analysis.local_runtime)
    if analysis.model_dump() != expected.model_dump():
        raise ValueError("Entire source, forecasts, original prefixes, metrics, capacity and fixed statuses do not recompute")
    return analysis


def generation_result_for_analysis(analysis):
    analysis = BedAnalysis.model_validate(analysis.model_dump() if isinstance(analysis, BedAnalysis) else analysis)
    descriptions = {
        "all_targets_complete": "已分别计算实测占床与四项独立日事件预测。",
        "partial_targets": "仅对历史完整的独立目标计算预测；其余目标保留未知。",
        "no_complete_targets": "没有满足完整历史要求的目标，未生成数值预测。",
    }
    unknown = [item.target for item in analysis.targets if item.status != "complete"]
    return {
        "summary": descriptions[analysis.summary_status],
        "sections": [
            {
                "title": "单病区实测占床与独立事件",
                "content": "固定同星期原量均值、回顾性滚动回测及原误差区间见结构化结果。容量为明确审核场景，边界压力与整日容量积分分开；预测未按容量截断。",
                "source_ids": [analysis.source_binding.source_id],
            }
        ],
        "warnings": [
            "实测占床不等于未满足床位需求；经验区间不提供覆盖保证。",
            "日出院数与整日可运营容量的比值仅为本地定义，不是标准周转率。",
            "原资料按当前冻结件回顾性评估；不宣称历史时点已经可用或实际运营验证。",
        ],
        "missing_data": unknown + (["future_boundary_capacity_or_census_forecast"] if any(item.status != "known" for item in analysis.future_pressure) else []),
    }
