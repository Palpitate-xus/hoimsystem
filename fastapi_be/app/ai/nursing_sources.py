"""Explicit admission-bound nursing facts, with unknowns and score provenance intact."""

import json

from fastapi import HTTPException

from app.models import Admission, CriticalCareRecord, IcuScoreRecord, NursingAssessment, NursingPlan, NursingRecord

NURSING_REFERENCE_FEATURES = {
    "nursing_assessment_id": frozenset({44, 45, 46, 47, 48, 76}),
    "nursing_plan_id": frozenset({45, 46, 47, 76}),
    "critical_care_record_id": frozenset({41, 42, 43, 47, 48, 50, 76}),
    "icu_score_id": frozenset({41, 42, 43, 47, 48, 50, 76}),
}
NURSING_ROW_REFERENCES = {
    "completed_nursing_assessments": "nursing_assessment_id",
    "nursing_plans": "nursing_plan_id",
    "critical_care_records": "critical_care_record_id",
    "recorded_icu_scores": "icu_score_id",
}
ASSESSMENT_FIELDS = ("adl_score", "pressure_ulcer_risk", "fall_risk", "consciousness", "nutrition_risk")
NURSING_REFERENCE_MODELS = {
    "nursing_assessment_id": (NursingAssessment, "assessment_id", "completed_nursing_assessments"),
    "nursing_plan_id": (NursingPlan, "plan_id", "nursing_plans"),
    "critical_care_record_id": (CriticalCareRecord, "record_id", "critical_care_records"),
    "icu_score_id": (IcuScoreRecord, "score_id", "recorded_icu_scores"),
}
NURSING_LOADED_MODELS = {collection: (model, primary_key, key) for key, (model, primary_key, collection) in NURSING_REFERENCE_MODELS.items()}
NURSING_LOADED_MODELS["nursing_records"] = (NursingRecord, "record_id", None)


def has_frozen_nursing_sources(context):
    return bool(set(context.get("selected_sources", {})) & NURSING_REFERENCE_MODELS.keys()) or any(context.get(key) for key in NURSING_LOADED_MODELS)


def authorize_nursing_snapshot(db, user, context, patient, encounter_ref, minimize):
    """Check every disclosed nursing original, including automatically attached rows."""
    from app.ai.governance import digest, encode_json

    if user.user_role == "super_admin":
        return
    for collection, (model, primary_key, key) in NURSING_LOADED_MODELS.items():
        frozen_rows = context.get(collection, [])
        if not isinstance(frozen_rows, list):
            raise HTTPException(403, "护理或评分冻结资料格式不完整，请由超级管理员核查原始审计")
        references = []
        prefix = collection + ":"
        for item in frozen_rows:
            source_id = item.get("source_id") if isinstance(item, dict) else None
            if not isinstance(source_id, str) or not source_id.startswith(prefix):
                raise HTTPException(403, "护理或评分冻结资料缺少原引用，请由超级管理员核查原始审计")
            reference = source_id[len(prefix) :]
            if (
                not reference
                or len(reference) > 50
                or (model in {IcuScoreRecord, NursingRecord} and (not reference.isascii() or not reference.isdigit() or not 0 < int(reference) <= 2147483647 or str(int(reference)) != reference))
            ):
                raise HTTPException(403, "护理或评分冻结资料原引用不规范，请由超级管理员核查原始审计")
            references.append(reference)
        selected = context.get("selected_sources", {}).get(key)
        if len(set(references)) != len(references) or (selected is not None and selected not in references):
            raise HTTPException(403, "护理或评分冻结资料与原引用不一致，请由超级管理员核查原始审计")
        if not references:
            continue
        current_rows = db.query(model).filter(getattr(model, primary_key).in_(references)).populate_existing().all()
        originals = {str(getattr(row, primary_key)): row for row in current_rows}
        for reference, frozen in zip(references, frozen_rows, strict=True):
            row = originals.get(reference)
            if row is None or patient is None or row.patient_id != patient.patient_id or row.admission_id != encounter_ref:
                raise HTTPException(403, "护理或评分原资料不存在或归属已变化，请重新核对原资料；冻结审计由超级管理员保留")
            fields = {name: value for name, value in frozen.items() if name != "source_id"}
            try:
                current = json.loads(encode_json(minimize({name: getattr(row, name) for name in fields}, patient)))
            except (AttributeError, TypeError, ValueError) as exc:
                raise HTTPException(403, "护理或评分原资料格式已变化，请由超级管理员核查冻结审计") from exc
            if digest(current) != digest(fields):
                raise HTTPException(403, "护理或评分原资料已改变，旧结果不能继续作为当前资料读取，请重新核对；超级管理员可查冻结审计")


def validate_nursing_selection(spec, selected, encounter):
    """A clicked row never assigns itself to another admission, patient or capability."""
    for key, features in NURSING_REFERENCE_FEATURES.items():
        row = selected.get(key)
        if row is None:
            continue
        if spec.number not in features:
            raise HTTPException(422, "该功能不接受所选护理或评分资料")
        if not isinstance(encounter, Admission):
            raise HTTPException(422, "请明确选择原护理或评分记录所属住院，不能按日期推定")
        if row.admission_id != encounter.admission_id or row.patient_id != encounter.patient_id:
            raise HTTPException(409, "所选护理或评分记录不属于本次住院，请核对原记录")
        if key == "nursing_assessment_id" and row.status != 1:
            raise HTTPException(409, "所选护理评估尚未完成，不能作为AI复核依据")


def recorded_score_check(row):
    """Recheck a new manual sum without reinterpreting or rewriting a legacy score."""
    from app.clinical_scores import CALCULATION_VERSION, compute_manual_score

    version = row.get("calculation_version") or "legacy_unverified"
    result = {"calculation_version": version, "clinical_validation": "not_provided", "state": "legacy_unverified", "calculated_total": None}
    if version != CALCULATION_VERSION:
        result["note"] = "历史评分保留原总分与解释，分项完整性及旧默认值未核实，不重新给分或升级为预测结果"
        return result
    try:
        detail = json.loads(row.get("detail_json") or "null")
        total, _ = compute_manual_score(row["score_type"], detail)
    except (ValueError, TypeError, KeyError):
        result.update(state="invalid_components", note="原分项不满足该版本的完整人工输入契约，不作为可复核工具总数")
        return result
    result["calculated_total"] = total
    if type(row.get("total_score")) is not int or total != row["total_score"]:
        result.update(state="total_mismatch", note="原总分与原分项汇总矛盾，请核对原评分；未重写原记录")
    else:
        result.update(state="manual_sum_matches", note="仅核对全部人工分项及其算术总和；不证明原评估正确、临床适用、死亡风险或转出条件")
    return result


def attach_nursing_review(bundle):
    """Summarize already scoped sources; zero remains a recorded value, never an unknown."""
    data = bundle.data
    scope = data.get("inpatient_source_scope")
    if not scope or not any(key in data for key in NURSING_ROW_REFERENCES):
        return
    review = {
        "scope": scope,
        "selected_sources": {key: value for key, value in data.get("selected_sources", {}).items() if key in NURSING_REFERENCE_FEATURES},
        "assessments": [],
        "critical_records": [],
        "scores": [],
        "plans": [],
        "clinical_validation": "not_provided",
        "limitations": [
            "仅所选住院的有限原始记录，截断与缺项须保留；不是连续监测、完整观测窗或已验证风险预测",
            "本地护理风险0–3标记及ADL数值未提供标准量表定义、版本与逐项答案，不自动换算Morse、Braden或其他量表",
            "历史默认值可能未经过显式评估；nullable_v1仅表示新输入允许未知，不证明人工评估或临床正确",
            "评估发生时间未知时不以创建或更新时间代替；其他患者级体征和检验不按日期归入本次住院",
            "既有护理记录原时间没有独立发生/登记来源标记，不视为已核实的连续监测时间窗",
            "原自由文本入量、出量、氧疗及尿量不自动解析单位、累计区间或给药暴露，不据缺项判断正常",
        ],
    }
    selected = review["selected_sources"]
    for row in data.get("completed_nursing_assessments", []):
        version = row.get("entry_version") or "legacy_unverified"
        review["assessments"].append(
            {
                **row,
                "explicitly_selected": row["source_id"].split(":", 1)[1] == selected.get("nursing_assessment_id"),
                "entry_version": version,
                "legacy_defaults_possible": version != "nullable_v1",
                "missing_fields": [key for key in ASSESSMENT_FIELDS if row.get(key) is None],
                "assessed_fields": [key for key in ASSESSMENT_FIELDS if row.get(key) is not None],
                "assessment_time_basis": "explicit_utc" if row.get("assessed_at") else "not_recorded",
                "standard_scale_validated": False,
            }
        )
    for row in data.get("critical_care_records", []):
        review["critical_records"].append(
            {
                **row,
                "explicitly_selected": row["source_id"].split(":", 1)[1] == selected.get("critical_care_record_id"),
                "entry_version": row.get("entry_version") or "legacy_unverified",
                "legacy_defaults_possible": row.get("entry_version") != "nullable_v1",
                "time_basis": row.get("time_basis") or "unspecified",
                "missing_fields": [key for key in ("consciousness", "gcs_score", "pulse", "spo2") if row.get(key) is None],
                "gcs_component_assessment": "not_provided",
            }
        )
    for row in data.get("recorded_icu_scores", []):
        review["scores"].append(
            {
                **row,
                "explicitly_selected": row["source_id"].split(":", 1)[1] == selected.get("icu_score_id"),
                "assessment_time_basis": "explicit_utc" if row.get("assessed_at") else "not_recorded",
                "component_check": recorded_score_check(row),
            }
        )
    for row in data.get("nursing_plans", []):
        review["plans"].append({**row, "explicitly_selected": row["source_id"].split(":", 1)[1] == selected.get("nursing_plan_id"), "status_note": "原计划内容与状态不代表实际护理执行或疗效"})
    data["nursing_source_review"] = review
