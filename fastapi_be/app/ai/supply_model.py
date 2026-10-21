"""Exact recorded-quantity forecasts and prefix-only rolling evidence; no data access."""

import hashlib
from datetime import date, timedelta
from fractions import Fraction
from pathlib import Path

from app.ai.supply_contract import (
    MAX_BYTES,
    MAX_INTEGER_BITS,
    MAX_WORK_UNITS,
    MODELS,
    TARGETS,
    Parameters,
    SourceBinding,
    SupplyAnalysis,
    SupplyRuntime,
    SupplySource,
    canonical_json,
    hash_content,
    input_policy_digest,
    rational,
    recipe_digest,
)

RUNTIME_FILES = ("supply_contract", "supply_model", "supply_config", "supply_server")


def implementation_hashes():
    return {name: hashlib.sha256(Path(__file__).with_name(name + ".py").read_bytes()).hexdigest() for name in RUNTIME_FILES}


class Budget:
    """Charge actual rational operations before bounded cross-products, and emitted records."""

    def __init__(self, max_work=MAX_WORK_UNITS, max_bytes=MAX_BYTES):
        self.work = 0
        self.bytes = 0
        self.max_work = max_work
        self.max_bytes = max_bytes

    def tick(self, amount=1):
        self.work += amount
        if self.work > self.max_work:
            raise ValueError("Exact calculation exceeds deterministic work budget; no partial output")

    def operation(self, operation, a, b):
        a, b = Fraction(a), Fraction(b)
        bits = [abs(x).bit_length() for x in (a.numerator, a.denominator, b.numerator, b.denominator)]
        # Bound even unreduced cross-products before Fraction constructs them.
        if max(bits) > MAX_INTEGER_BITS or max(bits[0] + bits[3], bits[2] + bits[1], bits[1] + bits[3], bits[0] + bits[2]) + 1 > MAX_INTEGER_BITS:
            raise ValueError("Exact arithmetic intermediate exceeds integer bit budget")
        self.tick(1 + sum(bits) + (sum(bits) ** 2 // 4096))
        if operation == "add":
            result = a + b
        elif operation == "sub":
            result = a - b
        elif operation == "mul":
            result = a * b
        elif operation == "div":
            if not b:
                raise ValueError("Unreviewed zero denominator")
            result = a / b
        else:
            raise ValueError("Unknown exact arithmetic operation")
        if max(abs(result.numerator).bit_length(), result.denominator.bit_length()) > MAX_INTEGER_BITS:
            raise ValueError("Exact arithmetic result exceeds integer bit budget")
        return result

    def add(self, a, b):
        return self.operation("add", a, b)

    def sub(self, a, b):
        return self.operation("sub", a, b)

    def mul(self, a, b):
        return self.operation("mul", a, b)

    def div(self, a, b):
        return self.operation("div", a, b)

    def sum(self, values):
        total = Fraction()
        for value in values:
            total = self.add(total, value)
        return total

    def exact(self, value):
        value = Fraction(value)
        bits = abs(value.numerator).bit_length() + value.denominator.bit_length()
        self.tick(1 + bits + bits * bits // 4096)
        return rational(value)

    def record(self, value):
        self.tick()
        self.bytes += len(canonical_json(value).encode())
        if self.bytes > self.max_bytes:
            raise ValueError("Exact proof construction exceeds UTF8 budget; no truncation")
        return value


def validate_runtime(runtime):
    values = SupplyRuntime.model_validate(runtime.model_dump() if isinstance(runtime, SupplyRuntime) else runtime).model_dump()
    if values["core_sha256"] != implementation_hashes() or values["recipe_digest"] != recipe_digest() or values["input_policy_digest"] != input_policy_digest():
        raise ValueError("Supply runtime implementation or fixed policy differs")
    identity = {key: value for key, value in values.items() if key not in {"runtime_digest", "model_version"}}
    digest = hash_content(identity)
    if values["runtime_digest"] != digest or values["model_version"] != "supply:" + digest:
        raise ValueError("Registered supply model and complete runtime descriptor differ")
    return values


def _state(count, first, last, size, interval, probability, budget):
    return {
        "positive_count": count,
        "first_positive_day": first,
        "last_positive_day": last,
        "size": budget.exact(size) if size is not None else None,
        "interval": budget.exact(interval) if interval is not None else None,
        "occurrence_probability": budget.exact(probability) if probability is not None else None,
    }


def _prefixes(values, parameters, wanted, budget):
    alpha = parameters.alpha_size.fraction()
    interval_alpha = parameters.alpha_interval.fraction()
    beta = parameters.beta_occurrence.fraction()
    total, differences = [Fraction()], [Fraction()]
    count, first, last, size, interval, probability = 0, None, None, None, None, None
    states = {}
    for index, value in enumerate(values, start=1):
        budget.tick()
        total.append(budget.add(total[-1], value))
        differences.append(budget.add(differences[-1], abs(budget.sub(value, values[index - 2]))) if index > 1 else Fraction())
        if value > 0:
            count += 1
            if first is None:
                first = last = index
                size, interval, probability = value, Fraction(index), Fraction(1, index)
            else:
                size = budget.add(size, budget.mul(alpha, budget.sub(value, size)))
                interval = budget.add(interval, budget.mul(interval_alpha, budget.sub(index - last, interval)))
                probability = budget.add(probability, budget.mul(beta, budget.sub(1, probability)))
                last = index
        elif first is not None:
            probability = budget.add(probability, budget.mul(beta, -probability))
        if index in wanted:
            states[index] = (count, first, last, size, interval, probability)
    return total, differences, states


def _prediction(values, total, t, model, parameters, state, budget):
    if model in MODELS[:3] and state[0] < 2:
        return None
    if model == "croston":
        vector = [budget.div(state[3], state[4])]
    elif model == "sba":
        correction = budget.sub(1, budget.div(parameters.alpha_interval.fraction(), 2))
        vector = [budget.mul(correction, budget.div(state[3], state[4]))]
    elif model == "tsb":
        vector = [budget.mul(state[3], state[5])]
    elif model == "prefix_mean":
        vector = [budget.div(total[t], t)]
    elif model == "last28_mean":
        vector = [budget.div(budget.sub(total[t], total[t - 28]), 28)]
    elif model == "seasonal_naive7":
        vector = values[t - 7 : t]
    else:
        raise ValueError("Unknown fixed supply method")
    return {"representation": "repeat_last_week" if model == "seasonal_naive7" else "constant_rate", "values": [budget.exact(value) for value in vector]}, vector


def _metrics(rows, budget, cumulative=False):
    if not rows:
        return None
    errors = [row[0] for row in rows]
    error_sum = budget.sum(errors)
    absolute = budget.sum(abs(value) for value in errors)
    squared = budget.sum(budget.mul(value, value) for value in errors)
    actual = budget.sum(row[1] for row in rows)
    zero = sum(row[2] == 0 for row in rows)
    # Cumulative-horizon error has different aggregation; no mislabeled scaled score.
    mase = None if cumulative or zero else budget.div(budget.sum(budget.div(abs(row[0]), row[2]) for row in rows), len(rows))
    return budget.record(
        {
            "count": len(rows),
            "unique_target_dates": len({row[3] for row in rows}),
            "error_sum": budget.exact(error_sum),
            "absolute_error_sum": budget.exact(absolute),
            "squared_error_sum": budget.exact(squared),
            "actual_sum": budget.exact(actual),
            "me": budget.exact(budget.div(error_sum, len(rows))),
            "mae": budget.exact(budget.div(absolute, len(rows))),
            "mse": budget.exact(budget.div(squared, len(rows))),
            "wape": budget.exact(budget.div(absolute, actual)) if actual else None,
            "wape_undefined_reason": None if actual else "zero_actual_sum",
            "mase": budget.exact(mase) if mase is not None else None,
            "mase_undefined_reason": "not_applicable_to_cumulative" if cumulative else ("zero_origin_scale" if zero else None),
            "zero_scale_count": zero,
        }
    )


def forecast_target(values, dates, horizon, parameters, budget=None):
    """Exact six-model comparison. Values must be a complete calendar prefix, never compressed."""
    from app.ai.supply_contract import Quantity

    if type(horizon) is not int or horizon not in (7, 14) or not 112 <= len(values) <= 366 or len(dates) != len(values):
        raise ValueError("Complete fixed history and horizon required")
    parameters = Parameters.model_validate(parameters.model_dump() if isinstance(parameters, Parameters) else parameters)
    texts = [Quantity.model_validate({"value": value, "absent_reason": None}).value for value in values]
    observed = [Fraction(value) for value in texts]
    first_date = date.fromisoformat(dates[0])
    if any(day != (first_date + timedelta(days=index)).isoformat() for index, day in enumerate(dates)):
        raise ValueError("Forecast history must be contiguous actual dates")
    budget = budget or Budget()
    n = len(observed)
    origins = list(range(n - horizon - 27, n - horizon + 1))
    totals, differences, states = _prefixes(observed, parameters, {*origins, n}, budget)
    scales = {t: budget.div(differences[t], t - 1) for t in origins}
    forecasts = [(date.fromisoformat(dates[-1]) + timedelta(days=lead)).isoformat() for lead in range(1, horizon + 1)]
    results = []
    for model in MODELS:
        budget.tick()
        terminal = states[n] if model in MODELS[:3] else (*states[n][:3], None, None, None)
        predicted = _prediction(observed, totals, n, model, parameters, states[n], budget)
        prediction, vector = predicted if predicted is not None else (None, None)
        terminal_state = budget.record(_state(*terminal, budget=budget))
        if prediction is not None:
            budget.record(prediction)
        future_sum = budget.sum(vector[index % len(vector)] for index in range(horizon)) if vector is not None else None
        folds, rows, cumulative, by_lead = [], [], [], [[] for _ in range(horizon)]
        for t in origins:
            budget.tick()
            fitted = _prediction(observed, totals, t, model, parameters, states[t], budget)
            fold_prediction, fold_values = fitted if fitted is not None else (None, None)
            actual_sum = budget.sub(totals[t + horizon], totals[t])
            forecast_sum = None
            if fold_values is not None:
                forecast_sum = budget.sum(fold_values[index % len(fold_values)] for index in range(horizon))
                for lead in range(horizon):
                    error = budget.sub(fold_values[lead % len(fold_values)], observed[t + lead])
                    row = (error, observed[t + lead], scales[t], dates[t + lead])
                    rows.append(row)
                    by_lead[lead].append(row)
                cumulative.append((budget.sub(forecast_sum, actual_sum), actual_sum, scales[t], dates[t + horizon - 1]))
            fold_state = states[t] if model in MODELS[:3] else (*states[t][:3], None, None, None)
            folds.append(
                budget.record(
                    {
                        "origin_date": dates[t - 1],
                        "training_days": t,
                        "training_digest": hash_content({"dates": dates[:t], "original_values": texts[:t]}),
                        "status": "complete" if fitted is not None else "insufficient_positive_observations",
                        "state": _state(*fold_state, budget=budget),
                        "origin_scale": budget.exact(scales[t]),
                        "prediction": fold_prediction,
                        "horizon_actual_sum": budget.exact(actual_sum),
                        "horizon_forecast_sum": budget.exact(forecast_sum) if forecast_sum is not None else None,
                        "horizon_error": budget.exact(budget.sub(forecast_sum, actual_sum)) if forecast_sum is not None else None,
                    }
                )
            )
        eligible = sum(row["status"] == "complete" for row in folds)
        result = {
            "model": model,
            "status": "insufficient_positive_observations" if predicted is None else ("complete" if eligible == 28 else "partial_backtest"),
            "initialization": "first_positive_elapsed_v1" if model in MODELS[:3] else "not_applicable",
            "terminal_state": terminal_state,
            "prediction": prediction,
            "horizon_forecast_sum": budget.exact(future_sum) if future_sum is not None else None,
            "forecast_dates": forecasts if predicted is not None else [],
            "rolling_origins": folds,
            "eligible_origin_count": eligible,
            "eligible_pair_count": len(rows),
            "distinct_target_dates": len({row[3] for row in rows}),
            "directly_comparable": eligible == 28,
            "metrics": _metrics(rows, budget),
            "by_lead": [{"lead_days": lead + 1, "metrics": _metrics(items, budget)} for lead, items in enumerate(by_lead)],
            "cumulative_horizon_metrics": _metrics(cumulative, budget, cumulative=True),
            "uncertainty": "not_provided",
        }
        results.append(result)
    return results


def _unknown_model(model):
    return {
        "model": model,
        "status": "input_unknown",
        "initialization": "first_positive_elapsed_v1" if model in MODELS[:3] else "not_applicable",
        "terminal_state": None,
        "prediction": None,
        "horizon_forecast_sum": None,
        "forecast_dates": [],
        "rolling_origins": [],
        "eligible_origin_count": 0,
        "eligible_pair_count": 0,
        "distinct_target_dates": 0,
        "directly_comparable": False,
        "metrics": None,
        "by_lead": [],
        "cumulative_horizon_metrics": None,
        "uncertainty": "not_provided",
    }


def _target(source, target, horizon, budget):
    index = TARGETS.index(target)
    originals = {row.ref.source_id: row for row in source.observations}
    values, missing, latest, methods = [], [], None, set()
    constrained = stock_unknown = 0
    for day in source.days:
        budget.tick()
        selection = day.selections[index]
        original = originals.get(selection.source_id)
        reasons, value = [], None
        if original is None:
            reasons.append(selection.absent_reason)
        else:
            constrained += original.stock_constraint in ("partial", "full")
            stock_unknown += original.stock_constraint == "unknown"
            if original.quantity.value is None:
                reasons.append("not_recorded_quantity" if original.quantity.absent_reason == "not_recorded" else "unknown_quantity")
            if original.coverage != "attested_complete":
                reasons.append("coverage_unknown" if original.coverage == "unknown" else "coverage_incomplete")
            if original.unit_review != "confirmed" or original.unit_token is None:
                reasons.append("unit_not_confirmed")
            elif original.unit_token != source.unit_token:
                reasons.append("unit_mismatch")
            if not reasons:
                value = original.quantity.value
                methods.add(original.method)
                latest = {"date": day.date, "source_id": original.ref.source_id, "value": value, "unit_token": original.unit_token}
        values.append(value)
        if reasons:
            missing.append({"date": day.date, "source_id": selection.source_id, "reasons": reasons})
    gates = []
    coverage = source.target_coverage[index]
    for field, reason in (("same_scope_confirmed", "scope_not_confirmed"), ("same_definition_confirmed", "definition_not_confirmed"), ("same_method_confirmed", "method_not_confirmed")):
        if getattr(coverage, field) != "confirmed":
            gates.append(reason)
    if len(methods) > 1:
        gates.append("mixed_methods")
    complete = not gates and not missing
    known = [Fraction(value) for value in values if value is not None]
    known_sum = budget.exact(budget.sum(known)) if known else None
    trailing = None
    if complete:
        trailing = 0
        for value in reversed(known):
            if value != 0:
                break
            trailing += 1
    result = {
        "target": target,
        "status": "complete" if complete else "input_unknown",
        "target_gate_reasons": gates,
        "missing_days": missing,
        "eligible_day_count": len(known),
        "observed_sum": known_sum if complete else None,
        "known_observed_sum": known_sum,
        "last_day_value": values[-1] if not gates else None,
        "last_eligible_observation": latest,
        "positive_days": sum(value > 0 for value in known),
        "zero_days": sum(value == 0 for value in known),
        "trailing_zero_days": trailing,
        "stock_constrained_days": constrained,
        "stock_constraint_unknown_days": stock_unknown,
        "models": forecast_target(values, [day.date for day in source.days], horizon, source.parameters, budget) if complete else [_unknown_model(model) for model in MODELS],
    }
    if not complete:
        budget.record(result)
    return result


def compute_supply(source, horizon_days, instructions_digest, runtime):
    if type(horizon_days) is not int or horizon_days not in (7, 14):
        raise ValueError("Supply horizon must be actual integer 7 or 14")
    source = SupplySource.model_validate(source.model_dump() if isinstance(source, SupplySource) else source)
    runtime = validate_runtime(runtime)
    budget = Budget()
    binding = {key: getattr(source, key) for key in SourceBinding.model_fields if key != "projection_hash"}
    binding["projection_hash"] = hash_content(source.model_dump())
    targets = [_target(source, target, horizon_days, budget) for target in TARGETS]
    value = {
        "schema_version": "supply_analysis_v1",
        "source_binding": binding,
        "rule_id": source.rule_id,
        "recipe_digest": recipe_digest(),
        "input_policy_digest": input_policy_digest(),
        "instructions_digest": instructions_digest,
        "local_runtime": runtime,
        "horizon_days": horizon_days,
        "evaluation_basis": "current_snapshot_retrospective",
        "historical_as_of_replay": False,
        "planned_origin_count": 28,
        "planned_pair_count": 28 * horizon_days,
        "distinct_planned_target_dates": horizon_days + 27,
        "targets": targets,
        "selected_model": None,
        "forecast_only": True,
        "work_units": budget.work,
    }
    if len(canonical_json(value).encode()) > MAX_BYTES:
        raise ValueError("Whole exact supply analysis exceeds UTF8 bound; no truncation")
    return SupplyAnalysis.model_validate(value)


def validate_analysis_binding(analysis, source, horizon_days, instructions_digest, model_version):
    analysis = SupplyAnalysis.model_validate(analysis.model_dump() if isinstance(analysis, SupplyAnalysis) else analysis)
    if analysis.local_runtime.model_version != model_version:
        raise ValueError("Registered supply model differs from native analysis")
    # The configured model version pins the full external descriptor; host and
    # isolated container may have different Python/package identities. Actual core
    # hashes and the complete registered descriptor are checked in compute_supply.
    expected = compute_supply(source, horizon_days, instructions_digest, analysis.local_runtime)
    if analysis.model_dump() != expected.model_dump():
        raise ValueError("Complete original supply analysis, math, clocks or proof differs")
    return analysis


def generation_result_for_analysis(analysis):
    analysis = SupplyAnalysis.model_validate(analysis.model_dump() if isinstance(analysis, SupplyAnalysis) else analysis)
    complete = sum(row.status == "complete" for row in analysis.targets)
    return {
        "summary": f"已核对{complete}/3项完整的已记录数量序列；六种固定方法分别展示，不自动选择最优模型。",
        "sections": [
            {"title": "预测范围", "source_ids": [analysis.source_binding.source_id], "content": "仅预测已记录请求、毛实发和确认实耗；不推断潜在需求，不生成采购量或缺货概率。"},
            {
                "title": "回顾评价",
                "content": f"使用28个滚动原点与{analysis.horizon_days}日预测；完整时为{analysis.planned_pair_count}个重叠原点—步长误差，涉及{analysis.distinct_planned_target_dates}个不同目标日期。",
            },
        ],
        "warnings": ["这是当前原件的回顾评价，不保证当时已经可得；没有提供运营或临床效果验证。", "实发和实耗可能受历史供应约束；缺货期间实发零不能证明请求零或需求消失。"],
        "missing_data": [f"{row.target}:input_unknown" for row in analysis.targets if row.status != "complete"],
    }
