"""Exact six-axis local SOFA-1 arithmetic over the complete typed evidence set."""

import hashlib
import re
from datetime import datetime, timedelta
from fractions import Fraction
from pathlib import Path

from app.ai.sofa_contract import ATTRIBUTION, AXES, RECIPE, RULE_ID, RULE_REFERENCES, SofaAnalysis, SofaRuntime, SofaSource, SourceBinding, canonical_json, hash_content, policy_digest, recipe_digest

RUNTIME_FILES = ("sofa_contract.py", "sofa_model.py", "sofa_config.py", "sofa_server.py")
HOUR_US = 3_600_000_000
WARNINGS = [
    "本结果为独立软件按完整24小时原资料计算的本地SOFA-1六轴规则，未提供本院临床有效性验证、脓毒症诊断、个体概率或自动治疗建议。",
    "mg/dL与SI、mmHg与kPa采用各自固定原单位连续边界；打印小数间隙、SI边界与持续一小时档位均为显式本地政策，不宣称官方勘误，不与SOFA-2混用，不作近似单位换算。",
    "已知分项小计、数学上下界、数值已确定与完整协议总分分别列出；缺测、NT、未决冲突或范围不明不补0，低小计不能排除器官功能障碍或脓毒症。",
    "临床判读为当前医生对原时段的回顾性核实，可能晚于原可用截止；不是当时已知声明或历史预测。",
    "升压药仅按原实际剂量、明确静脉持续给药、可解释质量口径和适用实测体重计算；零剂量不触发阳性档位，不合并不同药物为等效剂量。",
    "尿量只接受完整原24小时患者总量区段平铺；不分摊、外推或按体重折算，不把肾脏替代治疗自动记为SOFA-1肾脏4分。",
    "GCS仅用同一原检查的完整实测E/V/M及医生明确排除干扰影响的判读；不把NT当1，不补15，不使用AVPU或虚拟镇静前分数。",
]


def implementation_hashes():
    return {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest() for name in RUNTIME_FILES}


def _time(value):
    return datetime.fromisoformat(value)


def _stamp(value):
    return value.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _us(delta):
    return delta.days * 86_400_000_000 + delta.seconds * 1_000_000 + delta.microseconds


def _rational(value, unit="1"):
    value = Fraction(value)
    return {"numerator": str(value.numerator), "denominator": str(value.denominator), "unit": unit}


def _quantity_calc(value, ids, unit="1", operation="original_native_quantity"):
    return {"kind": "quantity", "operation": operation, "source_ids": sorted(set(ids)), "exact": _rational(value, unit)}


def _candidate(cid, ids, branch, score=None, lower=0, upper=4, reasons=(), calculations=(), status=None):
    return {
        "candidate_id": cid,
        "source_ids": sorted(set(ids)),
        "branch_id": branch,
        "status": status or ("scored" if score is not None else "bounded" if lower else "unknown"),
        "score": score,
        "lower_bound": score if score is not None else lower,
        "upper_bound": score if score is not None else upper,
        "reason_codes": sorted(set(reasons)),
        "calculations": list(calculations),
    }


def _excluded(cid, ids, branch):
    return _candidate(cid, ids, branch, lower=0, upper=0, reasons=["review_excluded"], status="excluded")


def _state(source, item, extra_ids=()):
    ids = {item.source_id, *extra_ids}
    if item.review.status == "excluded":
        return "excluded"
    for group in source.conflict_groups:
        if ids & set(group.member_source_ids):
            if group.status == "unresolved":
                return "unresolved_conflict"
            if ids & set(group.excluded_source_ids):
                return "excluded"
    if item.review.status != "confirmed":
        return "review_unknown"
    return None


def _in_period(source, observed):
    return source.start_at <= observed < source.end_at


def _native_score(value, bands):
    number = Fraction(value)
    for lower, upper, lower_inclusive, upper_inclusive, score in bands:
        lo_ok = lower is None or (number >= Fraction(lower) if lower_inclusive else number > Fraction(lower))
        hi_ok = upper is None or (number <= Fraction(upper) if upper_inclusive else number < Fraction(upper))
        if lo_ok and hi_ok:
            return score
    raise ValueError("固定native边界未覆盖原非负量")


def _lab_candidate(source, item, branch):
    cid, ids = item.source_id, [item.source_id]
    state = _state(source, item)
    if state == "excluded":
        return _excluded(cid, ids, branch)
    if state:
        return _candidate(cid, ids, branch, reasons=[state])
    if not _in_period(source, item.collected_at_utc):
        return _candidate(cid, ids, branch, reasons=["outside_period"], upper=0, status="outside_scope")
    quantity = item.quantity
    if quantity.value is not None and Fraction(quantity.value) < 0:
        return _candidate(cid, ids, branch, reasons=["unsupported_value"])
    if quantity.value is None:
        return _candidate(cid, ids, branch, reasons=["unknown_quantity"])
    if branch == "platelets":
        bands = RECIPE["coagulation"]["bands"] if quantity.unit in RECIPE["coagulation"]["native_units"] else None
    elif branch == "bilirubin":
        bands = RECIPE["liver"]["bands"].get(quantity.unit)
    else:
        bands = RECIPE["renal"]["creatinine_bands"].get(quantity.unit)
    if bands is None:
        return _candidate(cid, ids, branch, reasons=["unsupported_unit"])
    return _candidate(cid, ids, branch, score=_native_score(quantity.value, bands), calculations=[_quantity_calc(quantity.value, ids)])


def _map_candidate(source, item):
    cid, ids, branch = item.source_id, [item.source_id], "map"
    state = _state(source, item)
    if state == "excluded":
        return _excluded(cid, ids, branch)
    if state:
        return _candidate(cid, ids, branch, upper=1, reasons=[state])
    if not _in_period(source, item.observed_at):
        return _candidate(cid, ids, branch, upper=0, reasons=["outside_period"], status="outside_scope")
    if item.quantity.value is None:
        return _candidate(cid, ids, branch, upper=1, reasons=["unknown_quantity"])
    if item.quantity.unit != "mm[Hg]":
        return _candidate(cid, ids, branch, upper=1, reasons=["unsupported_unit"])
    score = int(Fraction(item.quantity.value) < 70)
    return _candidate(cid, ids, branch, score=score, calculations=[_quantity_calc(item.quantity.value, ids, "mm[Hg]")])


def _gcs_candidate(source, item):
    cid, ids, branch = item.source_id, [item.source_id], "gcs"
    if item.anchor:
        ids.append(item.anchor.source_id)
    state = _state(source, item)
    if state == "excluded":
        return _excluded(cid, ids, branch)
    if state:
        return _candidate(cid, ids, branch, reasons=[state])
    if not _in_period(source, item.observed_at):
        return _candidate(cid, ids, branch, upper=0, reasons=["outside_period"], status="outside_scope")
    if not item.anchor_current:
        return _candidate(cid, ids, branch, reasons=["gcs_anchor_invalid"])
    if item.interpretable != "confirmed":
        return _candidate(cid, ids, branch, reasons=["gcs_not_interpretable"])
    if item.sedation_confounding_status != "excluded" or item.other_confounding_status != "excluded":
        return _candidate(cid, ids, branch, reasons=["gcs_confounding_not_excluded"])
    components = [item.components.eye, item.components.verbal, item.components.motor]
    if any(component.score is None for component in components):
        return _candidate(cid, ids, branch, reasons=["gcs_not_testable" if any(component.absent_reason == "not_testable" for component in components) else "gcs_incomplete"])
    total = sum(component.score for component in components)
    score = next(score for lower, upper, score in RECIPE["cns"]["bands"] if lower <= total <= upper)
    return _candidate(cid, ids, branch, score=score, calculations=[_quantity_calc(total, ids, operation="gcs_actual_sum")])


def _resp_candidate(source, item):
    ids = [item.pao2.source_id]
    for part in (item.pair, item.fio2, item.support):
        if part:
            ids.append(part.source_id)
    cid, branch = item.candidate_id, "pao2_fio2"
    if item.review.status == "excluded":
        return _excluded(cid, ids, branch)
    state = _state(source, item.pao2, [item.pair.source_id] if item.pair else [])
    if state == "excluded":
        return _excluded(cid, ids, branch)
    if state or item.review.status != "confirmed":
        return _candidate(cid, ids, branch, reasons=[state or "review_unknown"])
    if not _in_period(source, item.pao2.collected_at_utc):
        return _candidate(cid, ids, branch, upper=0, reasons=["outside_period"], status="outside_scope")
    if item.pair is None or item.fio2 is None or item.support is None:
        return _candidate(cid, ids, branch, reasons=["missing_pair"])
    if not all((item.arterial_sample_confirmed, item.same_sampling_state_confirmed, item.fio2_applicability_confirmed)):
        return _candidate(cid, ids, branch, reasons=["pair_not_confirmed"])
    support_state = _state(source, item.support)
    if support_state or not item.support.continuity_confirmed:
        return _candidate(cid, ids, branch, reasons=["continuity_not_confirmed" if not support_state else "pair_not_confirmed"])
    sample = item.pao2.collected_at_utc
    support = item.support
    if sample < support.start_at or sample > support.verified_until_at or (support.ended_at is not None and sample == support.ended_at):
        return _candidate(cid, ids, branch, reasons=["pair_not_confirmed"])
    pao2, fio2 = item.pao2.quantity, item.fio2.quantity
    if pao2.value is not None and Fraction(pao2.value) < 0:
        return _candidate(cid, ids, branch, reasons=["unsupported_value"])
    if pao2.value is None or fio2.value is None:
        return _candidate(cid, ids, branch, reasons=["unknown_quantity"])
    if pao2.unit not in {"mm[Hg]", "kPa"} or fio2.unit != "%":
        return _candidate(cid, ids, branch, reasons=["unsupported_unit"])
    if not 0 < Fraction(fio2.value) <= 100:
        return _candidate(cid, ids, branch, reasons=["pair_not_confirmed"])
    ratio = Fraction(pao2.value) * 100 / Fraction(fio2.value)
    thresholds = [Fraction(value) for value in RECIPE["respiratory"]["thresholds_mmhg" if pao2.unit == "mm[Hg]" else "thresholds_kpa"]]
    calc = {
        "kind": "pf_ratio",
        "source_ids": sorted(set(ids)),
        "native_pao2_unit": pao2.unit,
        "exact": _rational(ratio, pao2.unit),
        "qualifying_respiratory_support": item.qualifying_respiratory_support,
    }
    if ratio >= thresholds[0]:
        return _candidate(cid, ids, branch, score=0, calculations=[calc])
    if ratio >= thresholds[1]:
        return _candidate(cid, ids, branch, score=1, calculations=[calc])
    if ratio >= thresholds[2] or item.qualifying_respiratory_support == "no":
        return _candidate(cid, ids, branch, score=2, calculations=[calc])
    high = 3 if ratio >= thresholds[3] else 4
    if item.qualifying_respiratory_support == "yes":
        return _candidate(cid, ids, branch, score=high, calculations=[calc])
    return _candidate(cid, ids, branch, lower=2, upper=high, reasons=["support_qualification_unknown"], calculations=[calc])


def _normalized_rate(source, item):
    """Return exact rate or reason, never infer native quantities/route/mass semantics."""
    state = _state(source, item)
    if state:
        return None, state
    if item.continuous_iv != "confirmed":
        return None, "continuous_iv_not_confirmed"
    if not item.continuity_confirmed:
        return None, "continuity_not_confirmed"
    if not item.mass_basis_compatible_confirmed or item.mapping.active_moiety_basis != "base":
        return None, "mass_basis_not_confirmed"
    dose = item.dose_input
    rates = [dose.concentration, dose.pump_rate] if dose.mode == "pump" else [dose.rate]
    if any(rate.value is None for rate in rates):
        return None, "unknown_quantity"
    if dose.mode == "weight_normalized":
        return (Fraction(dose.rate.value), None) if dose.rate.unit == "ug/kg/min" else (None, "unsupported_unit")
    if item.weight is None:
        return None, "weight_missing"
    weight = item.weight
    if _state(source, weight) or not item.weight_applicability_confirmed or not item.weight_use_confirmed or weight.observed_at > item.start_at:
        return None, "weight_not_applicable"
    if weight.quantity.value is None:
        return None, "weight_missing"
    if weight.quantity.unit != "kg":
        return None, "unsupported_unit"
    kg = Fraction(weight.quantity.value)
    if kg <= 0:
        return None, "weight_nonpositive"
    if dose.mode == "absolute":
        if dose.rate.unit == "ug/min":
            return Fraction(dose.rate.value) / kg, None
        if dose.rate.unit == "mg/h":
            return Fraction(dose.rate.value) * 1000 / (60 * kg), None
        return None, "unsupported_unit"
    if dose.pump_rate.unit != "mL/h" or dose.concentration.unit not in {"ug/mL", "mg/mL"}:
        return None, "unsupported_unit"
    factor = 1000 if dose.concentration.unit == "mg/mL" else 1
    return Fraction(dose.concentration.value) * Fraction(dose.pump_rate.value) * factor / (60 * kg), None


def _tier(rate, drug):
    if rate <= 0:
        return 0
    if drug == "dopamine":
        return 4 if rate > 15 else 3 if rate > 5 else 2
    if drug == "dobutamine":
        return 2
    if drug in {"epinephrine", "norepinephrine"}:
        return 4 if rate > Fraction("0.1") else 3
    return None


def _vaso_candidate(source, group):
    ids = [item.source_id for item in group.intervals]
    branch, cid = "vasoactive", "vasoactive_group:" + group.drug_key
    accepted = [item for item in group.intervals if _state(source, item) != "excluded"]
    if not accepted:
        return _excluded(cid, ids, branch)
    start, end = _time(source.start_at), _time(source.end_at)
    prefix = start - timedelta(hours=1)
    facts, reasons, calculations = [], [], []
    relation_valid = group.relation_confirmed and group.dose_basis_consistency_confirmed and group.relation != "unresolved"
    if not relation_valid:
        reasons.append("stream_relation_unresolved")
    for item in accepted:
        left, right = max(_time(item.start_at), prefix), min(_time(item.verified_until_at), end)
        if left >= right:
            continue
        rate, reason = _normalized_rate(source, item)
        if reason:
            reasons.append(reason)
        if group.relation == "agent_total":
            scope_valid = item.rate_scope == "agent_total"
        else:
            scope_valid = item.rate_scope == "stream_rate"
        if not scope_valid:
            reasons.append("rate_scope_unknown")
        if not relation_valid or not scope_valid:
            rate = None
        facts.append((left, right, item.stream_key, item.source_id, rate))
        if rate is not None:
            calculations.append({"kind": "dose_rate", "source_ids": [item.source_id], "mode": item.dose_input.mode, "exact": _rational(rate, "ug/kg/min")})
    if not facts:
        return _candidate(cid, ids, branch, upper=0, reasons=["outside_period"], status="outside_scope")
    if not any(fact[1] > start for fact in facts):
        return _candidate(cid, ids, branch, score=0, reasons=["outside_period"], calculations=calculations)
    if group.relation == "single_stream" and len({fact[2] for fact in facts}) != 1:
        relation_valid = False
        reasons.append("stream_relation_unresolved")
    boundaries = sorted({point for fact in facts for point in fact[:2]})
    pieces = []
    unknown = not relation_valid or group.drug_key == "other"
    if group.drug_key == "other":
        reasons.append("unrepresented_drug_exposure")
    for left, right in zip(boundaries, boundaries[1:]):
        active = [fact for fact in facts if fact[0] <= left < fact[1]]
        if not active:
            pieces.append((left, right, None, []))
            continue
        member_ids = sorted({fact[3] for fact in active})
        same_stream_overlap = len({fact[2] for fact in active}) != len(active)
        bad_total = group.relation == "agent_total" and len(active) != 1
        bad_parallel = len(active) > 1 and group.relation != "distinct_parallel_streams"
        invalid = not relation_valid or same_stream_overlap or bad_total or bad_parallel or any(fact[4] is None for fact in active) or group.drug_key == "other"
        if invalid:
            unknown = True
            if same_stream_overlap:
                reasons.append("overlapping_same_stream")
            pieces.append((left, right, None, member_ids))
            continue
        rate = sum((fact[4] for fact in active), Fraction(0))
        pieces.append((left, right, rate, member_ids))
        if len(active) > 1:
            calculations.append({"kind": "dose_rate", "source_ids": member_ids, "mode": "parallel_sum", "exact": _rational(rate, "ug/kg/min")})
    highest = 0
    positive = False
    for tier in (2, 3, 4):
        run_start, run_end, run_ids = None, None, set()

        def finish():
            nonlocal highest
            if run_start is None:
                return
            duration = _us(run_end - run_start)
            qualifies = duration >= HOUR_US and start < run_end <= end and run_end > max(start, run_start)
            calculations.append(
                {
                    "kind": "continuous_tier",
                    "drug_key": group.drug_key,
                    "tier": tier,
                    "start_at": _stamp(run_start),
                    "end_at": _stamp(run_end),
                    "source_ids": sorted(run_ids),
                    "duration_microseconds": duration,
                    "meets_minimum": qualifies,
                }
            )
            if qualifies:
                highest = max(highest, tier)

        for left, right, rate, member_ids in pieces:
            score = _tier(rate, group.drug_key) if rate is not None else None
            met = score is not None and score >= tier
            positive = positive or (rate is not None and rate > 0 and right > start)
            if met:
                if run_start is None:
                    run_start = left
                elif run_end != left:
                    finish()
                    run_start, run_ids = left, set()
                run_end = right
                run_ids.update(member_ids)
            else:
                finish()
                run_start, run_end, run_ids = None, None, set()
        finish()
    if positive and highest == 0:
        reasons.append("duration_not_satisfied")
    if not positive and not unknown:
        reasons.append("zero_rate_no_positive_exposure")
    return _candidate(cid, ids, branch, score=None if unknown else highest, lower=highest, upper=4 if unknown else highest, reasons=reasons, calculations=calculations)


def _urine_candidate(source):
    branch, cid = "urine", "urine_complete_24h"
    selected, excluded, reasons = [], [], []
    for item in source.urine_intervals:
        state = _state(source, item)
        if state == "excluded":
            excluded.append(item.source_id)
            continue
        selected.append(item)
        if state:
            reasons.append(state)
        if item.start_at < source.start_at or item.end_at > source.end_at:
            reasons.append("urine_crosses_period")
        if item.volume_ml is None:
            reasons.append("unknown_quantity")
        if item.collection_completeness != "complete":
            reasons.append("urine_collection_incomplete")
        if item.patient_total is not True:
            reasons.append("urine_patient_total_unknown")
    ids = [item.source_id for item in selected]
    if not selected:
        return _candidate(cid, ids or excluded, branch, reasons=["missing_branch"])
    ordered = sorted(selected, key=lambda item: (item.start_at, item.end_at, item.source_id))
    cursor = source.start_at
    for item in ordered:
        if item.start_at > cursor:
            reasons.append("urine_gap")
        elif item.start_at < cursor:
            reasons.append("urine_overlap")
        cursor = max(cursor, item.end_at)
    if cursor != source.end_at:
        reasons.append("urine_gap" if cursor < source.end_at else "urine_crosses_period")
    if reasons:
        return _candidate(cid, ids, branch, reasons=reasons)
    volume = sum((Fraction(item.volume_ml) for item in ordered), Fraction(0))
    score = 4 if volume < 200 else 3 if volume < 500 else 0
    return _candidate(cid, ids, branch, score=score, calculations=[_quantity_calc(volume, ids, "mL/24h", "urine_full_period_sum")])


def _domain(source, axis, candidates, required_branches):
    coverage = getattr(source.coverage, axis)
    issues = []
    if coverage.source_inventory != "complete":
        issues.append("inventory_incomplete" if coverage.source_inventory == "incomplete" else "inventory_unknown")
    if coverage.clinical_protocol != "adequate":
        issues.append("protocol_incomplete" if coverage.clinical_protocol == "incomplete" else "protocol_unknown")
    issues.extend(item.code for item in source.member_issues if item.axis == axis)
    active = [item for item in candidates if item["status"] not in {"excluded", "outside_scope"}]
    for branch, maximum in required_branches:
        if not any(item["branch_id"] == branch for item in active):
            candidates.append(_candidate("missing:" + branch, [], branch, upper=maximum, reasons=["missing_branch"]))
    active = [item for item in candidates if item["status"] not in {"excluded", "outside_scope"}]
    lower = max((item["lower_bound"] for item in active), default=0)
    upper = max((item["upper_bound"] for item in active), default=4)
    if issues:
        upper = 4
    observed = [item["score"] for item in active if item["score"] is not None]
    protocol_complete = not issues and bool(active) and all(item["score"] is not None for item in active)
    reasons = sorted(set(issues + [reason for item in active if item["score"] is None for reason in item["reason_codes"]]))
    deciding = sorted({sid for item in active if item["lower_bound"] == lower and (item["score"] is not None or lower > 0) for sid in item["source_ids"]})
    return {
        "axis": axis,
        "candidates": candidates,
        "observed_max_score": max(observed) if observed else None,
        "lower_bound": lower,
        "upper_bound": max(lower, upper),
        "exact_numeric_score": lower if lower == upper else None,
        "protocol_complete": protocol_complete,
        "coverage_issues": reasons,
        "deciding_source_ids": deciding,
    }


def source_binding(source):
    values = {name: getattr(source, name) for name in SourceBinding.model_fields if name != "projection_hash"}
    return {**values, "projection_hash": hash_content(source.model_dump())}


def sofa_values(source):
    source = SofaSource.model_validate(source)
    groups = {axis: [] for axis in AXES}
    for item in source.lab_observations:
        axis, branch = {"platelet_count": ("coagulation", "platelets"), "total_bilirubin": ("liver", "bilirubin"), "creatinine": ("renal", "creatinine")}[item.analyte]
        groups[axis].append(_lab_candidate(source, item, branch))
    groups["respiratory"] = [_resp_candidate(source, item) for item in source.respiratory_observations]
    groups["cns"] = [_gcs_candidate(source, item) for item in source.gcs_observations]
    groups["renal"].append(_urine_candidate(source))
    groups["cardiovascular"] = [_map_candidate(source, item) for item in source.map_observations] + [_vaso_candidate(source, group) for group in source.vasoactive_groups]
    circulation = source.circulation_review
    if (
        circulation.drug_exposure == "none"
        and circulation.no_other_unrepresented_exposure_confirmed
        and not any(group.intervals and any(_state(source, item) != "excluded" for item in group.intervals) for group in source.vasoactive_groups)
    ):
        groups["cardiovascular"].append(_candidate("explicit_no_drug_exposure", [], "vasoactive", score=0))
    elif circulation.drug_exposure == "unknown" or not circulation.no_other_unrepresented_exposure_confirmed:
        groups["cardiovascular"].append(_candidate("unrepresented_drug_exposure", [], "vasoactive", reasons=["unrepresented_drug_exposure"]))
    required = {
        "respiratory": [("pao2_fio2", 4)],
        "coagulation": [("platelets", 4)],
        "liver": [("bilirubin", 4)],
        "cardiovascular": [("map", 1), ("vasoactive", 4)],
        "cns": [("gcs", 4)],
        "renal": [("creatinine", 4), ("urine", 4)],
    }
    domains = [_domain(source, axis, groups[axis], required[axis]) for axis in AXES]
    population = source.population
    outside = population.adult == "no" or (population.age_at_period_years is not None and population.age_at_period_years < 18)
    within = (
        not outside
        and population.adult == "yes"
        and population.age_at_period_years is not None
        and population.age_at_period_years >= 18
        and population.care_setting != "unknown"
        and population.applicability_confirmed
    )
    scope = "outside_scope" if outside else "within_declared_scope" if within else "unknown"
    if not within:
        reason = "outside_scope" if outside else "scope_unknown"
        for domain in domains:
            domain.update(observed_max_score=None, lower_bound=0, upper_bound=4, exact_numeric_score=None, protocol_complete=False, coverage_issues=[reason], deciding_source_ids=[])
            for candidate in domain["candidates"]:
                if candidate["status"] != "excluded":
                    candidate.update(status="outside_scope" if outside else "unknown", score=None, lower_bound=0, upper_bound=4, reason_codes=[reason])
    observed = [domain["observed_max_score"] for domain in domains if domain["observed_max_score"] is not None]
    lower, upper = sum(domain["lower_bound"] for domain in domains), sum(domain["upper_bound"] for domain in domains)
    complete_count = sum(domain["protocol_complete"] for domain in domains)
    complete = within and complete_count == 6
    return {
        "rule_id": RULE_ID,
        "recipe_digest": recipe_digest(),
        "policy_digest": policy_digest(),
        "calculation_status": "outside_scope" if outside else "computed" if complete else "partial",
        "scope_status": scope,
        "domains": domains,
        "known_subtotal": sum(observed) if observed else None,
        "observed_scored_domain_count": len(observed),
        "protocol_complete_domain_count": complete_count,
        "lower_bound": lower,
        "upper_bound": upper,
        "exact_numeric_total": lower if lower == upper else None,
        "complete_total_score": lower if complete else None,
        "warnings": WARNINGS,
        "missing_data": [f"{domain['axis']}:{reason}" for domain in domains for reason in domain["coverage_issues"]],
        "diagnosis_provided": False,
        "probability_provided": False,
        "treatment_provided": False,
        "historical_prediction": False,
        "clinical_validation": "not_provided",
        "independent_implementation": True,
        "attribution": ATTRIBUTION,
        "rule_references": RULE_REFERENCES,
    }


def validate_runtime(runtime):
    runtime = SofaRuntime.model_validate(runtime).model_dump()
    if runtime["core_sha256"] != implementation_hashes() or runtime["recipe_digest"] != recipe_digest() or runtime["policy_digest"] != policy_digest():
        raise ValueError("SOFA固定规则或实际运行源码不一致")
    for key in ("python_version", "fastapi_version", "pydantic_version"):
        if not re.fullmatch(r"\d+\.\d+\.\d+(?:[A-Za-z0-9.+_-]{0,50})?", runtime[key]):
            raise ValueError("SOFA运行依赖版本格式无效")
    identity = {key: value for key, value in runtime.items() if key not in {"runtime_digest", "model_version"}}
    digest = hash_content(identity)
    if runtime["runtime_digest"] != digest or runtime["model_version"] != "sofa1:" + digest:
        raise ValueError("SOFA运行model版本不一致")


def compute_sofa(source, instructions_digest, runtime):
    source = SofaSource.model_validate(source)
    validate_runtime(runtime)
    return SofaAnalysis.model_validate(
        {
            "schema_version": "1",
            "source_binding": source_binding(source),
            **sofa_values(source),
            "instructions_digest": instructions_digest,
            "local_runtime": SofaRuntime.model_validate(runtime).model_dump(),
        }
    )


def validate_analysis_binding(analysis, source, instructions_digest, model_version):
    """Recompute every candidate, native rational, stream, interval, bound and explanation."""
    analysis = SofaAnalysis.model_validate(analysis)
    if analysis.local_runtime.model_version != model_version:
        raise ValueError("所请求SOFA模型与实际运行版本不同")
    expected = compute_sofa(source, instructions_digest, analysis.local_runtime)
    if canonical_json(expected.model_dump()) != canonical_json(analysis.model_dump()):
        raise ValueError("SOFA完整原件、数学、阈值、证据、范围或固定解释绑定不一致")


def generation_result_for_analysis(analysis):
    analysis = SofaAnalysis.model_validate(analysis)
    if analysis.complete_total_score is not None:
        summary = f"所选完整24小时原资料SOFA-1六轴总分为{analysis.complete_total_score}/24。"
    elif analysis.scope_status != "within_declared_scope":
        summary = "当前成人适用范围未知或不符合本实现声明，未提供完整SOFA-1总分。"
    else:
        subtotal = "无可明确计分域" if analysis.known_subtotal is None else f"明确计分域小计{analysis.known_subtotal}"
        summary = f"SOFA-1有{analysis.observed_scored_domain_count}/6域存在明确分项；{subtotal}，范围{analysis.lower_bound}至{analysis.upper_bound}，完整总分为空。"
    summary += "本地原单位与持续时间政策见结构化分项；本结果不是脓毒症诊断、概率或自动治疗依据。"
    return {
        "summary": summary,
        "sections": [
            {
                "title": "SOFA-1完整24小时六轴核对",
                "content": "六轴全部原候选、精确有理数、持续给药证据、尿量平铺、已知小计、上下界与协议完整性见结构化结果；未知项未补0。",
                "source_ids": [analysis.source_binding.source_id, analysis.source_binding.rule_profile_source_id],
            }
        ],
        "warnings": analysis.warnings,
        "missing_data": analysis.missing_data,
    }


def change_source_binding(source):
    observed = source.baseline.source if source.baseline.mode == "observed" else None
    return {
        "change_assessment_id": source.change_assessment_id,
        "source_id": source.source_id,
        "content_hash": source.content_hash,
        "assessment_governance_hash": source.assessment_governance_hash,
        "projection_hash": hash_content(source.model_dump()),
        "current_assessment_id": source.current.assessment_id,
        "current_content_hash": source.current.content_hash,
        "current_projection_hash": hash_content(source.current.model_dump()),
        "baseline_mode": source.baseline.mode,
        "baseline_assessment_id": observed.assessment_id if observed else None,
        "baseline_content_hash": observed.content_hash if observed else None,
        "baseline_projection_hash": hash_content(observed.model_dump()) if observed else None,
        "infection_source_id": source.infection.source_id,
        "infection_content_hash": source.infection.content_hash,
        "infection_governance_hash": source.infection.governance_hash,
        "rule_id": RULE_ID,
        "recipe_digest": recipe_digest(),
        "policy_digest": policy_digest(),
    }


def compute_change(source, instructions_digest, runtime):
    """Recompute actual daily evidence twice; never subtract incomplete subtotals."""
    from app.ai.sofa_contract import SofaChangeAnalysis, SofaChangeSource

    source = SofaChangeSource.model_validate(source)
    current = compute_sofa(source.current, instructions_digest, runtime)
    baseline = source.baseline
    missing = []
    if baseline.mode == "observed":
        prior = compute_sofa(baseline.source, instructions_digest, runtime)
        baseline_analysis = {"mode": "observed", "analysis": prior.model_dump()}
        bmin, bmax, btotal = prior.lower_bound, prior.upper_bound, prior.complete_total_score
        baseline_scope = prior.scope_status
        if btotal is None:
            missing.append("baseline_complete_total_unavailable")
    elif baseline.mode == "conditional_zero":
        confirmed = baseline.no_known_preexisting_organ_dysfunction and baseline.preinfection_baseline_assumption_confirmed
        bmin, bmax, btotal = 0, 0 if confirmed else 24, 0 if confirmed else None
        baseline_analysis = {"mode": "conditional_zero", "assumptions_confirmed": confirmed, "lower_bound": bmin, "upper_bound": bmax, "assumed_total_score": btotal, "basis_hash": baseline.basis_hash}
        baseline_scope = "within_declared_scope" if confirmed else "unknown"
        missing.append("baseline_zero_is_current_explicit_clinician_assumption_not_measured")
        if not confirmed:
            missing.append("conditional_zero_assumptions_not_both_confirmed")
    else:
        bmin, bmax, btotal = 0, 24, None
        baseline_analysis = {"mode": "unknown", "lower_bound": 0, "upper_bound": 24, "basis_hash": baseline.basis_hash}
        baseline_scope = "unknown"
        missing.append("baseline_unknown_not_zero")
    lower, upper = current.lower_bound - bmax, current.upper_bound - bmin
    complete_delta = current.complete_total_score - btotal if current.complete_total_score is not None and btotal is not None else None
    threshold = "at_least_two" if lower >= 2 else "below_two" if upper < 2 else "indeterminate"
    infection = source.infection
    outside = current.scope_status == "outside_scope" or baseline_scope == "outside_scope" or infection.infection_status == "not_suspected" or infection.current_presence == "no"
    within = not outside and current.scope_status == baseline_scope == "within_declared_scope" and infection.infection_status in {"suspected", "documented"} and infection.current_presence == "yes"
    scope = "outside_scope" if outside else "within_declared_scope" if within else "unknown"
    if current.complete_total_score is None:
        missing.append("current_complete_total_unavailable")
    if infection.current_presence != "yes" or infection.infection_status not in {"suspected", "documented"}:
        missing.append("infection_presence_not_currently_confirmed")
    if infection.onset_at is None or infection.onset_review != "known":
        missing.append("infection_onset_unknown_or_not_currently_reviewed")
    if infection.late_original_available_after_current_as_of:
        missing.append("infection_original_available_after_current_asof_current_retrospective_only")
    if source.review.acute_change != "confirmed":
        missing.append("acute_change_not_clinician_confirmed")
    if source.review.attribution != "infection_related":
        missing.append("infection_attribution_not_clinician_confirmed")
    if source.review.temporal_relation in {"before", "unknown"}:
        missing.append("temporal_relation_not_clinician_confirmed_as_overlapping_or_after_infection")
    warnings = WARNINGS + [
        "两期SOFA-1均从完整冻结原件重新计算；变化范围为当前下界减基线上界、当前上界减基线下界，保留负变化，不相减缺项小计。",
        "条件性零基线仅为医生明确核实假设，不等于实测正常或缺失默认0；基线未知保留0至24范围。数值变化达到2本身不构成脓毒症诊断。",
        "感染存在、急性变化、归因与相对感染时序均为当前独立临床判读；本实现不从评分变化或两个日窗口推定这些结论。",
    ]
    return SofaChangeAnalysis.model_validate(
        {
            "schema_version": "1",
            "source_binding": change_source_binding(source),
            "rule_id": RULE_ID,
            "recipe_digest": recipe_digest(),
            "policy_digest": policy_digest(),
            "current_analysis": current.model_dump(),
            "baseline_analysis": baseline_analysis,
            "scope_status": scope,
            "calculation_status": "outside_scope" if outside else "computed" if complete_delta is not None and within else "partial",
            "delta_lower_bound": lower,
            "delta_upper_bound": upper,
            "exact_numeric_delta": lower if lower == upper else None,
            "complete_delta": complete_delta,
            "delta_threshold_status": threshold,
            "acute_change": source.review.acute_change,
            "attribution": source.review.attribution,
            "temporal_relation": source.review.temporal_relation,
            "local_runtime": current.local_runtime.model_dump(),
            "instructions_digest": instructions_digest,
            "warnings": warnings,
            "missing_data": missing,
            "diagnosis_provided": False,
            "probability_provided": False,
            "treatment_provided": False,
            "historical_prediction": False,
            "clinical_validation": "not_provided",
            "independent_implementation": True,
            "attribution_statement": ATTRIBUTION,
            "rule_references": RULE_REFERENCES,
        }
    )


def validate_change_analysis_binding(analysis, source, instructions_digest, model_version):
    from app.ai.sofa_contract import SofaChangeAnalysis

    analysis = SofaChangeAnalysis.model_validate(analysis)
    if analysis.local_runtime.model_version != model_version:
        raise ValueError("SOFA变化所请求模型与实际运行版本不同")
    expected = compute_change(source, instructions_digest, analysis.local_runtime)
    if canonical_json(expected.model_dump()) != canonical_json(analysis.model_dump()):
        raise ValueError("SOFA变化全部原件、两期数学、基线假设、变化界限、归因或固定解释不一致")


def generation_result_for_change_analysis(analysis):
    from app.ai.sofa_contract import SofaChangeAnalysis

    analysis = SofaChangeAnalysis.model_validate(analysis)
    baseline = {"observed": "实测原基线", "conditional_zero": "明确条件性零基线假设", "unknown": "未知基线"}[analysis.baseline_analysis.mode]
    exact = f"完整变化{analysis.complete_delta}" if analysis.complete_delta is not None else "完整变化为空"
    summary = f"SOFA-1采用{baseline}；变化范围{analysis.delta_lower_bound}至{analysis.delta_upper_bound}，{exact}。"
    summary += "数值变化与临床急变、感染归因分别核对；本结果不是脓毒症诊断、概率或自动治疗依据。"
    binding = analysis.source_binding
    return {
        "summary": summary,
        "sections": [
            {
                "title": "SOFA-1两期完整重算与变化范围",
                "content": "当前及原基线六轴完整重算、基线模式、精确或部分变化界限和当前医生感染/急变/归因/时序声明见结构化结果；未知基线不补0。",
                "source_ids": [binding.source_id, analysis.current_analysis.source_binding.source_id, binding.infection_source_id]
                + ([analysis.baseline_analysis.analysis.source_binding.source_id] if analysis.baseline_analysis.mode == "observed" else []),
            }
        ],
        "warnings": analysis.warnings,
        "missing_data": analysis.missing_data,
    }
