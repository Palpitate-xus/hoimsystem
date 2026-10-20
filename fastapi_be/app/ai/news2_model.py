"""Deterministic Decimal NEWS2 arithmetic; no learned model or patient database."""

import hashlib
import re
from decimal import Decimal
from pathlib import Path

from app.ai.news2_contract import ATTRIBUTION, COMPONENT_KEYS, MEASUREMENT_UNITS, RECIPE, RULE_REFERENCES, News2Analysis, News2Runtime, News2Source, canonical_json, recipe_digest

RUNTIME_FILES = ("news2_contract.py", "news2_model.py", "news2_config.py", "news2_server.py")


def implementation_hashes():
    return {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest() for name in RUNTIME_FILES}


def _band(value, bands):
    for lower, upper, score in bands:
        if (lower is None or value >= Decimal(lower)) and (upper is None or value <= Decimal(upper)):
            return score
    raise ValueError("原数值未落在官方明确分段，不能补齐小数间隙")


def _classification(total, red, *, partial=False):
    if total >= 7:
        return "high"
    if total >= 5:
        return "medium"
    if red:
        return "single_red"
    if total == 0:
        return None if partial else "zero"
    return "low"


def news2_values(source):
    """Score only declared eligible observations; unknown values are never zero."""
    source = News2Source.model_validate(source)
    outside = source.age_at_observation_years < 16 or source.pregnancy_status == "pregnant"
    unknown = source.pregnancy_status == "unknown" and not outside
    scope_status = "outside_scope" if outside else "unknown" if unknown else "within_declared_scope"
    missing, components = [], []
    if outside:
        missing.append("outside_scope_under_16_or_pregnant")
    elif unknown:
        missing.append("pregnancy_applicability_unknown")
    for key in COMPONENT_KEYS:
        if key in MEASUREMENT_UNITS:
            measurement = source.measurements.get(key)
            raw, unit = (measurement.value if measurement else None), MEASUREMENT_UNITS[key]
        elif key == "supplemental_oxygen":
            raw, unit = source.supplemental_oxygen, None
        else:
            raw, unit = (f"{source.consciousness.system}:{source.consciousness.code}" if source.consciousness else None), None
        item = {"key": key, "raw_value": raw, "unit": unit, "observed_at": source.observed_at, "source_id": source.point_source_id, "score": None, "status": "missing", "reason": "not_recorded"}
        if outside or unknown:
            item.update(status="outside_scope" if outside else "requires_review", reason="population_outside_scope" if outside else "population_applicability_unknown")
        elif key in source.conflict_codes:
            item.update(status="conflict", reason="same_time_relevant_conflict")
        elif key in MEASUREMENT_UNITS:
            if raw is None:
                item["reason"] = f"absent_{measurement.absent_reason}" if measurement else "not_recorded"
            else:
                value = Decimal(raw)
                quantum = Decimal("0.1") if key == "temperature" else Decimal("1")
                if value % quantum != 0:
                    item.update(status="outside_precision", reason="requires_exact_tenth_no_rounding" if key == "temperature" else "requires_integer_value_no_rounding")
                elif (
                    key == "spo2"
                    and source.spo2_scale == 2
                    and (source.scale2_review is None or not source.scale2_review.hypercapnic_respiratory_failure_confirmed or not source.scale2_review.clinical_decision_confirmed)
                ):
                    item.update(status="requires_review", reason="scale2_blood_gas_and_clinical_decision_required")
                elif key == "spo2" and source.spo2_scale == 2 and value >= 93 and "supplemental_oxygen" in source.conflict_codes:
                    item.update(status="conflict", reason="scale2_high_spo2_depends_on_conflicting_oxygen")
                elif key == "spo2" and source.spo2_scale == 2 and value >= 93 and source.supplemental_oxygen == "unknown":
                    item.update(status="requires_review", reason="scale2_high_spo2_requires_explicit_air_or_oxygen")
                else:
                    if key != "spo2":
                        bands = RECIPE["bands"][key]
                    elif source.spo2_scale == 1:
                        bands = RECIPE["bands"]["spo2_scale1"]
                    elif value <= 92:
                        bands = RECIPE["bands"]["spo2_scale2_low"]
                    else:
                        bands = RECIPE["bands"]["spo2_scale2_air_high" if source.supplemental_oxygen == "no" else "spo2_scale2_oxygen_high"]
                    item.update(score=_band(value, bands), status="scored", reason="official_2017_band")
        elif key == "supplemental_oxygen":
            if raw == "unknown":
                item["reason"] = "supplemental_oxygen_unknown"
            else:
                item.update(score=RECIPE["oxygen"][raw], status="scored", reason="explicit_binary_oxygen")
        elif source.consciousness:
            score = RECIPE["consciousness"][source.consciousness.system][source.consciousness.code]
            if score is None:
                item.update(status="requires_review", reason="avpu_alert_does_not_exclude_new_confusion")
            else:
                item.update(score=score, status="scored", reason="explicit_acvpu_alert" if score == 0 else "explicit_cvpu_abnormality")
        if item["score"] is None and not outside and not unknown:
            missing.append(f"{key}:{item['reason']}")
        components.append(item)
    scored = [item for item in components if item["score"] is not None]
    red = [item["key"] for item in scored if item["score"] == 3]
    count = len(scored)
    subtotal = sum(item["score"] for item in scored) if scope_status == "within_declared_scope" else None
    complete = count == 7 and scope_status == "within_declared_scope"
    total = subtotal if complete else None
    band = _classification(total, red) if complete else None
    minimum = band if complete else _classification(subtotal, red, partial=True) if subtotal is not None else None
    warnings = [
        "独立实现RCP NEWS2 2017固定规则，非RCP认证；工程一致性核对不证明本院临床有效性或原测量可靠性。",
        "NEWS2是急性生理异常评分；本结果不是事件概率、脓毒症诊断、病因判断或自动治疗/处置指令，不能替代临床判断。",
        "本实现仅接受整值呼吸频率/SpO₂/收缩压/脉率及精确0.1°C温度；这是避免扩展原表分段的软件输入范围，不对原数值舍入。",
        "本次只计算明确选定的一条原点测，不把窗口中不同时刻指标拼接，不以前填、零值或心率代替缺失脉率。",
        "年龄、妊娠及Scale2核实依据来自显式声明；其真实性、适用性及原资料可用时刻未由规则服务独立临床核实。",
        "高位脊髓损伤等情况可能使NEWS2不可靠；本输入未独立核实全部个体适用条件，低分不排除恶化。",
        "氧疗项只有使用/未使用的二元分数，不反映氧需求递增的程度，不根据氧流量、FiO₂或装置推断其状态。",
        "The wording of this translation has not been specifically approved by the Royal College of Physicians – please refer to the English language version before making any clinical use of this information.",
    ]
    if not complete and scope_status == "within_declared_scope":
        warnings.append("原资料不完整、精度不支持或存在相关冲突，完整总分与正式分类为空；已知小计只是下界，未测项未填0。RCP强调不完整资料中的已知异常及单项3分仍须关注。")
    if unknown or outside:
        warnings.append("当前人群适用性未知或超出本实现范围；所有分项分数与小计均为空，不将原值冒称可适用的NEWS2。")
    return {
        "rule_id": "news2_2017",
        "calculation_status": "outside_scope" if outside else "computed" if complete else "insufficient_data",
        "scope_status": scope_status,
        "components": components,
        "total_score": total,
        "observed_subtotal": subtotal,
        "scored_component_count": count,
        "minimum_classification": minimum,
        "score_is_lower_bound": scope_status == "within_declared_scope" and not complete,
        "red_flag_components": red,
        "classification": band,
        "missing_data": missing,
        "warnings": warnings,
        "attribution": ATTRIBUTION,
        "rule_references": RULE_REFERENCES,
        "independent_implementation": True,
        "clinical_validation": "not_provided",
    }


def validate_runtime(runtime) -> None:
    runtime = News2Runtime.model_validate(runtime).model_dump()
    if runtime["implementation"] != implementation_hashes() or runtime["recipe_digest"] != recipe_digest():
        raise ValueError("NEWS2固定规则或实际运行源码不一致")
    if set(runtime["engine_versions"]) != {"fastapi", "pydantic"} or any(not re.fullmatch(r"\d+\.\d+\.\d+(?:[A-Za-z0-9.+_-]{0,50})?", value) for value in runtime["engine_versions"].values()):
        raise ValueError("NEWS2运行依赖声明无效")
    identity = {key: value for key, value in runtime.items() if key not in {"runtime_digest", "model_version"}}
    digest = hashlib.sha256(canonical_json(identity).encode()).hexdigest()
    if runtime["runtime_digest"] != digest or runtime["model_version"] != "news2:" + digest:
        raise ValueError("NEWS2运行版本绑定不一致")


def validate_analysis_binding(analysis, source, instructions_digest: str, model_version: str) -> None:
    """Recompute every score, provenance field, subtotal and classification."""
    analysis, source = News2Analysis.model_validate(analysis), News2Source.model_validate(source)
    validate_runtime(analysis.local_runtime)
    if analysis.local_runtime.model_version != model_version:
        raise ValueError("所请求NEWS2模型与实际运行版本不同")
    expected = {"schema_version": "1", "source_binding": source.model_dump(), **news2_values(source), "instructions_digest": instructions_digest}
    if canonical_json(analysis.model_dump(exclude={"local_runtime"})) != canonical_json(expected):
        raise ValueError("NEWS2来源、原值、规则分项、总分、下界、分类或Prompt绑定不一致")


def generation_result_for_analysis(analysis) -> dict:
    """Fixed text, bound to the same verified arithmetic; no generated claims."""
    analysis = News2Analysis.model_validate(analysis)
    if analysis.calculation_status == "computed":
        summary = f"所选原点测NEWS2完整总分为{analysis.total_score}分，规则分类为{analysis.classification}；请结合原测量与临床情况人工复核。"
    elif analysis.scope_status == "within_declared_scope":
        summary = f"所选原点测有{analysis.scored_component_count}/7项可计分，已知小计{analysis.observed_subtotal}分仅为下界；完整NEWS2总分和正式分类未提供。"
    else:
        summary = "所选原点测的人群适用性未知或超出本实现范围，未提供NEWS2分项分数、总分或分类。"
    return {
        "summary": summary,
        "sections": [
            {
                "title": "所选原点测NEWS2规则核对",
                "content": "原值、时刻、分项、单项3分、完整总分或已知下界及规则版本见结构化核对表。结果不是概率、诊断或自动处置指令。",
                "source_ids": [analysis.source_binding.source_id, analysis.source_binding.point_source_id, analysis.source_binding.rule_profile_source_id],
            }
        ],
        "warnings": analysis.warnings,
        "missing_data": analysis.missing_data,
    }
