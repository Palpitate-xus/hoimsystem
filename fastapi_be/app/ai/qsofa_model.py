"""Exact qSOFA evidence counting; no learned model or patient database."""

import hashlib
import re
from decimal import Decimal
from pathlib import Path

from app.ai.qsofa_contract import ATTRIBUTION, CRITERION_KEYS, MEASUREMENT_UNITS, RULE_REFERENCES, QsofaAnalysis, QsofaRuntime, QsofaSource, canonical_json, recipe_digest

RUNTIME_FILES = ("qsofa_contract.py", "qsofa_model.py", "qsofa_config.py", "qsofa_server.py")


def implementation_hashes():
    return {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest() for name in RUNTIME_FILES}


def qsofa_values(source):
    """Count only actual supported criteria in the declared adult clinical scope."""
    source = QsofaSource.model_validate(source)
    outside = (source.age_at_observation_years is not None and source.age_at_observation_years < 18) or source.care_setting == "icu" or source.infection_status == "not_suspected"
    unknown = not outside and (source.age_at_observation_years is None or source.care_setting == "unknown" or source.infection_status == "unknown")
    scope = "outside_scope" if outside else "unknown" if unknown else "confirmed"
    missing, criteria = [], []
    if outside:
        missing.append("outside_declared_adult_non_icu_suspected_or_documented_infection_scope")
    elif unknown:
        missing.append("adult_non_icu_infection_scope_requires_explicit_clinical_review")
    gcs = source.gcs
    gcs_scores = [getattr(gcs.components, key).score for key in ("eye", "verbal", "motor")] if gcs else []
    raw_gcs_total = sum(gcs_scores) if len(gcs_scores) == 3 and all(value is not None for value in gcs_scores) else None
    for key in CRITERION_KEYS:
        if key in MEASUREMENT_UNITS:
            measurement = source.measurements.get(key)
            raw = measurement.value if measurement else None
            item = {"key": key, "raw_value": raw, "unit": MEASUREMENT_UNITS[key], "observed_at": source.observed_at, "source_ids": [source.point_source_id], "score": None, "status": "missing", "reason": "not_recorded"}
        else:
            item = {"key": key, "raw_value": str(raw_gcs_total) if raw_gcs_total is not None else None, "unit": "score", "observed_at": gcs.observed_at if gcs else None, "source_ids": [gcs.source_id, source.point_source_id] if gcs else [source.source_id], "score": None, "status": "missing", "reason": "gcs_not_selected_no_avpu_substitution"}
        if outside or unknown:
            item.update(status="outside_scope" if outside else "requires_review", reason="population_outside_scope" if outside else "population_applicability_unknown")
        elif key in source.point_conflicts:
            item.update(status="conflict", reason="same_time_original_point_conflict")
        elif key in MEASUREMENT_UNITS:
            if raw is None:
                item["reason"] = f"absent_{measurement.absent_reason}" if measurement else "not_recorded"
            else:
                met = Decimal(raw) >= Decimal("22") if key == "respiratory_rate" else Decimal(raw) <= Decimal("100")
                item.update(score=int(met), status="scored", reason="meets_original_qsofa_criterion" if met else "does_not_meet_this_qsofa_criterion_not_proof_of_normality")
        elif gcs:
            if gcs.conflict:
                item.update(status="conflict", reason="same_anchor_original_gcs_conflict")
            elif source.gcs_interpretability != "confirmed":
                item.update(status="requires_review", reason="gcs_clinical_interpretability_not_confirmed")
            elif raw_gcs_total is None:
                item["reason"] = "gcs_incomplete_or_not_testable_no_imputation"
            else:
                met = raw_gcs_total < 15
                item.update(score=int(met), status="scored", reason="complete_gcs_less_than_15" if met else "complete_gcs_15_does_not_meet_mentation_criterion")
        if item["score"] is None and scope == "confirmed":
            missing.append(f"{key}:{item['reason']}")
        criteria.append(item)
    scored = [item for item in criteria if item["score"] is not None]
    count = len(scored)
    subtotal = sum(item["score"] for item in scored) if scored and scope == "confirmed" else None
    complete = count == 3 and scope == "confirmed"
    threshold = "at_least_two" if subtotal is not None and subtotal >= 2 else "below_two_in_complete_data" if complete else "unknown"
    warnings = [
        "本结果为成人、非ICU、疑似或已知感染范围内所选原资料的qSOFA固定计数；独立软件实现不代表本院临床有效性、来源可靠性或个体适用性已经验证。",
        "SSC 2026推荐NEWS/NEWS2、MEWS或SIRS优于把qSOFA作为单一脓毒症筛查工具；本结果不得作为唯一筛查、脓毒症确诊/排除、死亡概率或自动治疗依据。",
        "完整计数低于2不排除脓毒症或病情恶化；单项0分仅表示未达到该qSOFA阈值，不证明原生理数值正常，呼吸频率0仍原样保留。",
        "年龄、实际非ICU场景、感染及GCS可判读性为当前临床医生对所选原时点的回顾性核实；核实可能晚于原截止，不代表当时已知这些声明，不是历史预测。",
        "呼吸频率与收缩压只取同一显式原点测，按原十进制值比较，不舍入、不换单位、不跨时间取最高/最低值。",
        "GCS须显式锚定同次原检查并保留其独立真实时刻；不是自动最近值匹配，不用AVPU/ACVPU或默认15补全，不把NT当1或估算缺失分项。",
    ]
    if scope == "confirmed" and not complete:
        warnings.append("原资料缺项、判读受限或相关原资料冲突，完整计数为空；只保留实际可计分项及其小计，未测项未填0。已知至少两项达到阈值时保留该事实，其余不完整低小计的阈值状态未知。")
    elif scope != "confirmed":
        warnings.append("适用范围未知或超出本实现范围，原事实保留但全部分项分数、小计及完整计数为空；不得假设符合成人非ICU感染范围。")
    return {
        "rule_id": "qsofa_sepsis3_2016",
        "calculation_status": "outside_scope" if outside else "computed" if complete else "insufficient_data",
        "scope_status": scope,
        "criteria": criteria,
        "total_score": subtotal if complete else None,
        "observed_subtotal": subtotal,
        "scored_count": count,
        "score_is_lower_bound": subtotal is not None and not complete,
        "threshold_status": threshold,
        "diagnosis_provided": False,
        "probability_provided": False,
        "missing_data": missing,
        "warnings": warnings,
        "attribution": ATTRIBUTION,
        "rule_references": RULE_REFERENCES,
        "independent_implementation": True,
        "clinical_validation": "not_provided",
    }


def validate_runtime(runtime) -> None:
    runtime = QsofaRuntime.model_validate(runtime).model_dump()
    if runtime["implementation"] != implementation_hashes() or runtime["recipe_digest"] != recipe_digest():
        raise ValueError("qSOFA固定规则或实际运行源码不一致")
    if set(runtime["engine_versions"]) != {"fastapi", "pydantic"} or any(not re.fullmatch(r"\d+\.\d+\.\d+(?:[A-Za-z0-9.+_-]{0,50})?", value) for value in runtime["engine_versions"].values()):
        raise ValueError("qSOFA实际运行依赖声明无效")
    identity = {key: value for key, value in runtime.items() if key not in {"runtime_digest", "model_version"}}
    digest = hashlib.sha256(canonical_json(identity).encode()).hexdigest()
    if runtime["runtime_digest"] != digest or runtime["model_version"] != "qsofa:" + digest:
        raise ValueError("qSOFA实际运行版本绑定不一致")


def validate_analysis_binding(analysis, source, instructions_digest: str, model_version: str) -> None:
    """Recompute every original value, scope, criterion, subtotal and warning."""
    analysis, source = QsofaAnalysis.model_validate(analysis), QsofaSource.model_validate(source)
    validate_runtime(analysis.local_runtime)
    if analysis.local_runtime.model_version != model_version:
        raise ValueError("所请求qSOFA模型与实际运行版本不同")
    expected = {"schema_version": "1", "source_binding": source.model_dump(), **qsofa_values(source), "instructions_digest": instructions_digest}
    if canonical_json(analysis.model_dump(exclude={"local_runtime"})) != canonical_json(expected):
        raise ValueError("qSOFA原量、同次证据、范围、分项、小计、阈值、固定解释或Prompt绑定不一致")


def generation_result_for_analysis(analysis) -> dict:
    """Fixed explanation of verified facts; no generated clinical claims."""
    analysis = QsofaAnalysis.model_validate(analysis)
    if analysis.calculation_status == "computed":
        summary = f"所选原资料qSOFA三项完整计数为{analysis.total_score}/3；" + ("已达到至少两项的提示阈值。" if analysis.threshold_status == "at_least_two" else "本次完整资料未达到两项提示阈值，但不能排除脓毒症或病情恶化。")
    elif analysis.scope_status == "confirmed":
        subtotal = str(analysis.observed_subtotal) if analysis.observed_subtotal is not None else "未提供"
        summary = f"所选原资料有{analysis.scored_count}/3项可计分，已知小计为{subtotal}，完整qSOFA计数为空；" + ("实际已知两项已达到提示阈值，仍缺完整资料。" if analysis.threshold_status == "at_least_two" else "不完整资料的阈值状态未知，不能据此排除脓毒症。")
    else:
        summary = "当前临床核实的适用范围未知或超出本实现范围，原事实保留，未提供qSOFA分项分数、小计或完整计数。"
    summary += "本结果不是唯一脓毒症筛查、诊断、概率或自动治疗依据。"
    source = analysis.source_binding
    source_ids = [source.source_id, source.point_source_id, source.rule_profile_source_id]
    if source.gcs:
        source_ids.append(source.gcs.source_id)
    return {
        "summary": summary,
        "sections": [{"title": "所选原资料qSOFA三项核对", "content": "原呼吸频率、收缩压、完整或缺测GCS分项、实际时刻、同次锚定、当前回顾性临床声明、相关冲突与固定规则版本见结构化核对表。0分仅表示未达该单项阈值，不证明数值正常。", "source_ids": source_ids}],
        "warnings": analysis.warnings,
        "missing_data": analysis.missing_data,
    }
