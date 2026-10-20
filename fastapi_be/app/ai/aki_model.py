"""Exact adult KDIGO 2012 supplied-data criteria, not an AKI exclusion test."""

import hashlib
import re
from datetime import datetime
from decimal import Decimal, localcontext
from fractions import Fraction
from pathlib import Path

from app.ai.aki_contract import ATTRIBUTION, CRITERION_KEYS, RECIPE, RULE_REFERENCES, AkiAnalysis, AkiCriterionEvidence, AkiRuntime, AkiSource, canonical_json, recipe_digest

RUNTIME_FILES = ("aki_contract.py", "aki_model.py", "aki_config.py", "aki_server.py")
HOUR_US = 3_600_000_000


def implementation_hashes():
    return {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest() for name in RUNTIME_FILES}


def _clock(value):
    return datetime.fromisoformat(value)


def _duration(start, end):
    value = _clock(end) - _clock(start)
    return (value.days * 86400 + value.seconds) * 1_000_000 + value.microseconds


def _number(value):
    return Fraction(Decimal(value))


def _decimal(value):
    # Only finite decimal inputs/sums/differences use this display function.
    # Rates and ratios stay exact numerator/denominator pairs, never rounded.
    with localcontext() as context:
        context.prec = 120
        text = format(Decimal(value.numerator) / Decimal(value.denominator), "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _criterion(key, reason="not_supplied", evidence=None, sources=None):
    return {
        "key": key,
        "status": "unknown",
        "stage": None,
        "reason_code": reason,
        "source_ids": list(dict.fromkeys(sources or [])),
        "evidence": AkiCriterionEvidence.model_validate(evidence or {}).model_dump(),
    }


def _evaluated(item, met, stage, reason):
    item.update(status="met" if met else "not_met_in_selected_data", stage=stage if met else None, reason_code=reason)
    return item


def _creatinine_problem(source, item):
    if item is None:
        return "creatinine_not_selected"
    if not source.creatinine_review.serum_creatinine_confirmed:
        return "serum_plasma_creatinine_not_clinically_confirmed"
    if item.conflict:
        return "same_time_identity_creatinine_conflict"
    if item.value is None or _number(item.value) <= 0:
        return "creatinine_numeric_positive_value_unavailable"
    if item.unit not in RECIPE["absolute_stage3"]["at_least"]:
        return "unsupported_native_unit_no_conversion"
    return None


def _creatinine_pair(source, reference, key):
    index = source.index_creatinine
    evidence = {
        "index_value": index.value if index else None,
        "reference_value": reference.value if reference else None,
        "unit": index.unit if index else None,
        "index_at": index.collected_at_utc if index else None,
        "reference_at": reference.collected_at_utc if reference else None,
    }
    item = _criterion(key, evidence=evidence, sources=[value.source_id for value in (index, reference) if value])
    for value in (index, reference):
        if problem := _creatinine_problem(source, value):
            item["reason_code"] = problem
            return item
    if index.unit != reference.unit or index.identity_hash != reference.identity_hash:
        item["reason_code"] = "creatinine_unit_or_reviewed_identity_mismatch"
        return item
    elapsed = _duration(reference.collected_at_utc, index.collected_at_utc)
    if elapsed <= 0:
        item["reason_code"] = "comparison_not_strictly_before_index"
        return item
    item["evidence"]["elapsed_microseconds"] = elapsed
    if key == "creatinine_48h":
        threshold = RECIPE["creatinine_48h"]["increase_at_least"][index.unit]
        delta = _number(index.value) - _number(reference.value)
        item["evidence"].update(absolute_change=_decimal(delta), threshold=threshold)
        if elapsed > 48 * HOUR_US:
            item["reason_code"] = "comparison_exceeds_48h"
            return item
        return _evaluated(item, delta >= _number(threshold), 1, "native_unit_48h_absolute_change")
    if source.baseline_mode == "observed_within_7d":
        if elapsed > 168 * HOUR_US:
            item["reason_code"] = "observed_baseline_exceeds_7d"
            return item
    elif source.baseline_mode == "presumed_within_7d":
        if source.baseline_review is None or not source.baseline_review.rise_within_7d_confirmed:
            item["reason_code"] = "older_baseline_requires_explicit_recent_rise_review"
            return item
    else:
        item["reason_code"] = "baseline_timing_mode_unknown"
        return item
    numerator, denominator = _number(index.value), _number(reference.value)
    stage = next((stage for threshold, stage in reversed(RECIPE["creatinine_ratio"]["stage_thresholds"]) if numerator >= _number(threshold) * denominator), None)
    item["evidence"].update(multiplier=next((threshold for threshold, band in RECIPE["creatinine_ratio"]["stage_thresholds"] if band == stage), "1.5"))
    return _evaluated(item, stage is not None, stage, "explicit_baseline_unrounded_ratio")


def _urine_criteria(source):
    intervals = sorted(source.urine_intervals, key=lambda value: (_clock(value.start_at), _clock(value.end_at), value.interval_id))
    keys = ("urine_6h", "urine_12h", "urine_24h", "anuria_12h")
    items = {key: _criterion(key, sources=[value.source_id for value in intervals]) for key in keys}
    if not intervals:
        return items
    issues = set(source.urine_coverage_issues)
    for index, value in enumerate(intervals):
        if value.collection_completeness != "complete":
            issues.add("partial_collection")
        if value.patient_total is not True:
            issues.add("not_patient_total")
        if value.volume_ml is None:
            issues.add("unknown_volume")
        if index:
            previous = intervals[index - 1]
            if _clock(value.start_at) < _clock(previous.end_at):
                issues.add("overlap")
            elif _clock(value.start_at) > _clock(previous.end_at):
                issues.add("gap")
    if issues:
        for item in items.values():
            item["reason_code"] = "urine_coverage_invalid"
            item["evidence"]["coverage_issues"] = sorted(issues)
        return items
    weight = source.weight
    weight_problem = (
        "weight_not_selected"
        if weight is None
        else "weight_conflict"
        if weight.conflict
        else "weight_not_positive"
        if weight.value is None or _number(weight.value) <= 0
        else "weight_not_attested_for_whole_period"
        if not source.weight_applicability_confirmed or source.weight_evidence_hash is None
        else "weight_measured_after_period_start"
        if _clock(weight.observed_at) > _clock(intervals[0].start_at)
        else None
    )
    candidates = []
    for first in range(len(intervals)):
        total = Fraction(0)
        for last in range(first, len(intervals)):
            total += _number(intervals[last].volume_ml)
            duration = _duration(intervals[first].start_at, intervals[last].end_at)
            candidates.append((duration, first, last, total))
    for key in keys:
        item = items[key]
        anuria = key == "anuria_12h"
        rule = {"at_least_hours": 12, "stage": 3} if anuria else next(value for value in RECIPE["urine"] if value["key"] == key)
        possible = [value for value in candidates if value[0] >= rule["at_least_hours"] * HOUR_US]
        if not possible:
            item["reason_code"] = "selected_whole_intervals_shorter_than_required_duration"
            continue
        if not anuria and weight_problem:
            item["reason_code"] = weight_problem
            continue

        def matches(candidate):
            duration, _, _, total = candidate
            return total == 0 if anuria else total * HOUR_US < _number(rule["below_ml_kg_h"]) * _number(weight.value) * duration

        matched = [value for value in possible if matches(value)]
        # Deterministic shortest positive whole-boundary witness; when negative,
        # show the full selected chain without claiming its hourly profile.
        candidate = min(matched, key=lambda value: (value[0], value[1], value[2])) if matched else candidates[len(intervals) - 1]
        duration, first, last, total = candidate
        selected = intervals[first : last + 1]
        evidence = {
            "interval_start_at": selected[0].start_at,
            "interval_end_at": selected[-1].end_at,
            "elapsed_microseconds": duration,
            "total_volume_ml": _decimal(total),
            "threshold": "0" if anuria else rule["below_ml_kg_h"],
            "unit": "mL" if anuria else "mL/kg/h",
            "weight_kg": None if anuria else weight.value,
            "interval_source_ids": [value.source_id for value in selected],
        }
        if not anuria:
            rate = total * HOUR_US / (_number(weight.value) * duration)
            evidence.update(rate_numerator=str(rate.numerator), rate_denominator=str(rate.denominator))
        item["evidence"] = AkiCriterionEvidence.model_validate(evidence).model_dump()
        if not anuria:
            item["source_ids"].append(weight.source_id)
        _evaluated(item, bool(matched), rule["stage"], "known_zero_whole_intervals" if anuria else "whole_original_interval_average_not_hourly_persistence")
    return items


def aki_values(source):
    """Evaluate exact supported criteria; absence of positives never excludes AKI."""
    source = AkiSource.model_validate(source)
    outside = source.age_at_evaluation_years < 18 or source.rrt.status == "maintenance"
    if outside:
        criteria = [_criterion(key, "under_18_or_maintenance_rrt") for key in CRITERION_KEYS]
        for item in criteria:
            item["status"] = "outside_scope"
    else:
        first = _creatinine_pair(source, source.comparison_48h, "creatinine_48h")
        ratio = _creatinine_pair(source, source.baseline_creatinine, "creatinine_ratio_7d")
        index = source.index_creatinine
        absolute = _criterion(
            "creatinine_absolute_stage3",
            sources=[index.source_id] if index else [],
            evidence={"index_value": index.value if index else None, "index_at": index.collected_at_utc if index else None, "unit": index.unit if index else None},
        )
        if problem := _creatinine_problem(source, index):
            absolute["reason_code"] = problem
        else:
            threshold = RECIPE["absolute_stage3"]["at_least"][index.unit]
            absolute["evidence"]["threshold"] = threshold
            if _number(index.value) < _number(threshold):
                _evaluated(absolute, False, 3, "index_below_native_absolute_stage3_threshold")
            elif any(item["status"] == "met" for item in (first, ratio)):
                absolute["source_ids"] = list(dict.fromkeys(absolute["source_ids"] + first["source_ids"] + ratio["source_ids"]))
                _evaluated(absolute, True, 3, "absolute_threshold_with_positive_creatinine_acute_change")
            elif any(item["status"] == "unknown" for item in (first, ratio)):
                absolute["reason_code"] = "absolute_threshold_requires_creatinine_based_acute_change"
            else:
                _evaluated(absolute, False, 3, "no_creatinine_based_acute_change_in_selected_data")
        urine = _urine_criteria(source)
        rrt = _criterion("acute_rrt", evidence={"index_at": source.rrt.started_at})
        if source.rrt.status == "not_initiated" and source.rrt.evidence_hash is not None:
            _evaluated(rrt, False, 3, "clinician_declared_not_initiated")
        elif source.rrt.status == "acute_initiated_for_aki" and source.rrt.started_at is not None and source.rrt.acute_aki_confirmed is True and source.rrt.evidence_hash is not None:
            _evaluated(rrt, True, 3, "clinician_confirmed_new_acute_rrt_for_aki")
        else:
            rrt["reason_code"] = "acute_rrt_status_or_aki_indication_not_confirmed"
        criteria = [first, ratio, absolute, *(urine[key] for key in ("urine_6h", "urine_12h", "urine_24h", "anuria_12h")), rrt]
    positive = [item["stage"] for item in criteria if item["status"] == "met"]
    minimum = max(positive) if positive else None
    unknown = [f"{item['key']}:{item['reason_code']}" for item in criteria if item["status"] == "unknown"]
    warnings = [
        "独立实现KDIGO 2012成人规则，未获KDIGO认证；工程一致性核对不证明本院临床有效性或原测量/人工声明真实。",
        "结果为明确选定资料中的规则符合情况与最低支持分期，不是未来风险概率、最终临床诊断、病因判断或治疗/启动透析指令。",
        "未符合所选资料中的判据不排除AKI；缺项、定性/非正肌酐、未知单位、相关冲突或覆盖问题不填0，也不选择自动最小/最近/估算基线。",
        "48小时及7日用于急性变化定义，不限制整个AKI病程分期；本结果不声称完整病程最高分期或当前仍持续AKI，旧肌酐时点不冒称与评估时刻同时。",
        "资料按冻结as_of可用截止回溯核对，允许截止前新登记的旧采样；这不是evaluation_at当时数据库可得资料的历史重放。",
        "肌酐只比较同原单位及同已审核身份；原表SI绝对3期采用353.6μmol/L，正文354为舍入写法，不暗中换算、舍入或更改26.5μmol/L的48小时界值。",
        "尿量采用本软件明确的原完整采集区间平均策略，枚举原边界连续子链；不裁剪、分摊或虚构逐小时记录，不能证明每一小时持续少尿。",
        "体重须明确选取测量值并人工核实适用于整个所选尿量期；未知体重不用于每公斤判据，但完整12小时零尿量可独立符合无尿判据。",
        "最低支持1/2期仍可能被未观察资料提高，标记为下界；3期达到本量表上界不代表病程资料完整。儿童eGFR、维持透析及2026草案规则不在本实现范围。",
    ]
    return {
        "rule_id": "kdigo_aki_2012",
        "calculation_status": "outside_scope" if outside else "insufficient_data" if unknown else "computed",
        "scope_status": "outside_scope" if outside else "within_declared_scope",
        "detection": "outside_scope" if outside else "met" if minimum is not None else "insufficient_data" if unknown else "not_met_in_selected_data",
        "criteria": criteria,
        "minimum_stage": minimum,
        "stage_is_lower_bound": minimum in (1, 2),
        "aki_excluded": False,
        "missing_data": ["outside_scope_under_18_or_maintenance_rrt"] if outside else unknown,
        "warnings": warnings,
        "attribution": ATTRIBUTION,
        "rule_references": RULE_REFERENCES,
        "independent_implementation": True,
        "clinical_validation": "not_provided",
    }


def validate_runtime(runtime) -> None:
    runtime = AkiRuntime.model_validate(runtime).model_dump()
    if runtime["implementation"] != implementation_hashes() or runtime["recipe_digest"] != recipe_digest():
        raise ValueError("AKI固定规则或实际运行源码不一致")
    if set(runtime["engine_versions"]) != {"fastapi", "pydantic"} or any(not re.fullmatch(r"\d+\.\d+\.\d+(?:[A-Za-z0-9.+_-]{0,50})?", value) for value in runtime["engine_versions"].values()):
        raise ValueError("AKI运行依赖声明无效")
    identity = {key: value for key, value in runtime.items() if key not in {"runtime_digest", "model_version"}}
    digest = hashlib.sha256(canonical_json(identity).encode()).hexdigest()
    if runtime["runtime_digest"] != digest or runtime["model_version"] != "aki:" + digest:
        raise ValueError("AKI实际运行模型版本不一致")


def validate_analysis_binding(analysis, source, instructions_digest: str, model_version: str) -> None:
    """Recompute all criteria, exact quantities, partial stages and provenance."""
    analysis, source = AkiAnalysis.model_validate(analysis), AkiSource.model_validate(source)
    validate_runtime(analysis.local_runtime)
    if analysis.local_runtime.model_version != model_version:
        raise ValueError("所请求AKI模型与实际运行版本不同")
    expected = {"schema_version": "1", "source_binding": source.model_dump(), **aki_values(source), "instructions_digest": instructions_digest}
    if canonical_json(analysis.model_dump(exclude={"local_runtime"})) != canonical_json(expected):
        raise ValueError("AKI来源、原值、判据、最低分期、缺项或Prompt绑定不一致")


def generation_result_for_analysis(analysis) -> dict:
    analysis = AkiAnalysis.model_validate(analysis)
    if analysis.scope_status == "outside_scope":
        summary = "所选资料超出本成人AKI规则实现范围，未提供判据分期；不能据此排除AKI。"
    elif analysis.minimum_stage is not None:
        summary = f"所选资料符合至少一项KDIGO 2012规则，最低支持{analysis.minimum_stage}期；仅供结合原资料与临床病程人工复核，不代表完整病程最高分期。"
    elif analysis.detection == "insufficient_data":
        summary = "所选资料存在未确定判据，未提供最低支持AKI分期；缺项不填0，不能排除AKI。"
    else:
        summary = "所选资料中未符合已核对的AKI判据；这不排除AKI，不代表正常肾功能或完整病程阴性。"
    source = analysis.source_binding
    source_ids = [source.source_id, source.rule_profile_source_id]
    return {
        "summary": summary,
        "sections": [
            {
                "title": "成人AKI原资料规则核对",
                "content": "逐判据状态、原量、时点、精确比较及最低支持分期见结构化核对表。尿量采用原完整区间平均，不证明逐小时持续；不提供概率或自动治疗指令。",
                "source_ids": list(dict.fromkeys(source_ids)),
            }
        ],
        "warnings": analysis.warnings,
        "missing_data": analysis.missing_data,
    }
