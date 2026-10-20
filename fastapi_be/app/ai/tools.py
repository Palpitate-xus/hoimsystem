"""Server-owned business tools; models cannot choose SQL, URLs or mutations."""

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.ai.billing_sources import billing_reconciliation
from app.ai.catalog import FeatureSpec
from app.ai.clinical_tools import critical_value_workflow, laboratory_trends, perioperative_timing
from app.ai.coding_sources import local_icd_candidates
from app.ai.context import ContextBundle
from app.ai.governance import encode_json
from app.ai.service_sources import appointment_candidates, hospital_navigation
from app.models import Department, Pharmaceutical, Prescription, User


def business_tools(db: Session, spec: FeatureSpec, user: User, patient_id: int | None, task_input: dict, context: ContextBundle) -> tuple[dict, list[dict]]:
    """Return explicit tool results and evidence without accepting instructions to execute code."""
    tools: dict = {}
    evidence: list[dict] = []
    if spec.number in {41, 42, 43}:
        window = context.data.get("observation_window", {})
        return {
            "observation_window_input": {
                "source_id": window.get("source_id"),
                "lab_input_status": window.get("lab_input_status", "not_provided"),
                "model_input_validation": window.get("model_input_validation", "not_provided"),
                "clinical_score_calculated": False,
                "urine_volume_or_rate_calculated": False,
                "scope_note": "仅所选原住院冻结窗；未加载的检验不能解释为危急值0条或无异常，未运行患者级趋势或工作流工具",
            }
        }, []
    if spec.number == 59:
        tools["appointment_candidates"], sources = appointment_candidates(db, task_input)
        evidence.extend(sources)
    if spec.number == 58:
        tools["hospital_navigation"], sources = hospital_navigation(db, user, task_input)
        evidence.extend(sources)
    if patient_id and spec.number == 69:
        tools["billing_reconciliation"] = billing_reconciliation(context.data)
    if patient_id and spec.number in {27, 68}:
        tools["icd_candidates"], dictionary_sources = local_icd_candidates(db, context.data, task_input)
        evidence.extend(dictionary_sources)
    if patient_id and spec.number == 49:
        tools["perioperative_timing"] = perioperative_timing(context.data)
        rule = tools["perioperative_timing"]["rule"]
        evidence.append({"source_id": f"rule:{rule['rule_id']}:{rule['version']}", "kind": "rule", "title": "既有围术期统计时窗口径", "content": encode_json(rule)})
    if patient_id and spec.number in {8, 19, 31, 32, 33, 56}:
        tools["laboratory_trends"] = laboratory_trends(context.data)
    if patient_id and spec.number in {1, 31, 33, 47, 50}:
        tools["critical_value_workflow"] = critical_value_workflow(context.data)
    if spec.number in {5, 6, 11, 12, 13, 14, 15, 16, 17, 18, 20}:
        rows = db.query(Pharmaceutical).filter(Pharmaceutical.status == 0).order_by(Pharmaceutical.pharmaceutical_id).limit(200).all()
        tools["hospital_drug_catalog"] = [
            {"drug_id": item.pharmaceutical_id, "name": item.name, "stock": item.stock, "expiry_date": item.expireddate, "antibiotic_level": item.antibiotic_level} for item in rows
        ]
    if spec.number in {13, 14, 15, 17} and patient_id:
        from app.rx_review_engine import review_saved_prescription

        prescription_id = task_input.get("prescription_id")
        if prescription_id:
            prescription = db.query(Prescription).filter_by(prescription_id=str(prescription_id), patient_id=patient_id).first()
            if not prescription:
                raise HTTPException(404, "处方不存在或不属于该患者")
            dose_evaluations = []
            findings = review_saved_prescription(db, prescription, evaluation_log=dose_evaluations)
            tools["prescription_review"] = {
                "findings": findings,
                "blocked": any(item["severity"] == 3 for item in findings),
                "dose_check_status": "no_matching_dose_rules"
                if not dose_evaluations
                else "incomplete"
                if any(item["issues"] for item in dose_evaluations)
                else "evaluated_against_matching_local_rules",
                "automatic_unit_conversion": False,
                "dose_evaluations": dose_evaluations,
                "unit_mapping_validation": "仅在处方与规则原始单位完全一致时比较；按处方行检查，不推测按需频次或跨行成分累计量",
                "coverage_note": "未匹配到剂量规则时不代表剂量合适；命中范围也不代表覆盖全部用药风险",
            }
            for evaluation in dose_evaluations:
                evidence.append(
                    {
                        "source_id": f"dose-rule:{evaluation['rule_id']}:{evaluation.get('version') or 'unversioned'}",
                        "kind": "rule",
                        "title": "院内剂量规则逐行校验",
                        "content": encode_json(evaluation),
                    }
                )
            for finding in findings:
                source_id = f"rule:{finding['rule_id']}:{finding.get('version') or 'unversioned'}"
                evidence.append({"source_id": source_id, "kind": "rule", "title": "现有处方审核规则", "content": encode_json(finding)})
        else:
            tools["prescription_review"] = {"findings": [], "blocked": None, "missing_data": ["未选择要核查的处方，尚未执行审方"]}
    if spec.number in {9, 51, 58, 59}:
        departments = db.query(Department).order_by(Department.department_id).all()
        tools["hospital_departments"] = [{"department_id": item.department_id, "name": item.name, "location": item.location} for item in departments]
    if spec.number in {50, 51, 52}:
        from app.routers.triage import triage_suggest

        text = str(task_input.get("symptom") or task_input.get("text") or task_input.get("question") or "")
        if text:
            outcome = triage_suggest({"symptom": text[:2000]}, db)
            if outcome.get("code") == 200:
                tools["triage_rules"] = outcome["data"]
    return tools, evidence
