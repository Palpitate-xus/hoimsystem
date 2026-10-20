"""Server-owned business tools; models cannot choose SQL, URLs or mutations."""

import datetime

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.ai.catalog import FeatureSpec
from app.ai.context import ContextBundle
from app.ai.governance import encode_json
from app.models import Admission, DailyOperationalMetric, Department, Doctor, Pharmaceutical, Prescription, User


def operational_context(db: Session, user: User) -> ContextBundle:
    """Expose aggregates at the user's actual hospital or department scope."""
    today = datetime.date.today()
    since = today - datetime.timedelta(days=90)
    if user.user_role in {"admin", "super_admin"}:
        metrics = db.query(DailyOperationalMetric).filter(DailyOperationalMetric.metric_date >= since).order_by(DailyOperationalMetric.metric_date).all()
        from app.analytics import serialize_metric

        return ContextBundle(
            data={
                "scope": "hospital",
                "since": since.isoformat(),
                "until": today.isoformat(),
                "daily_metrics": [serialize_metric(item) for item in metrics],
                "missing_data": [] if metrics else ["尚无已汇总的历史指标"],
            }
        )
    departments = {item[0] for item in db.query(Doctor.department_id).filter_by(user_id=user.user_id).all() if item[0]}
    if user.user_role != "director" or not departments:
        raise HTTPException(403, "没有医院或科室运营指标访问权限")
    inpatients = db.query(func.count(Admission.admission_id)).filter(Admission.department_id.in_(departments), Admission.status == 1).scalar() or 0
    return ContextBundle(data={"scope": "department", "active_inpatients": inpatients, "missing_data": ["全院预聚合指标未按科室拆分，不在科室范围提供"]}, department_ids=departments)


def business_tools(db: Session, spec: FeatureSpec, user: User, patient_id: int | None, task_input: dict) -> tuple[dict, list[dict]]:
    """Return explicit tool results and evidence without accepting instructions to execute code."""
    tools: dict = {}
    evidence: list[dict] = []
    if spec.number in {5, 6, 11, 12, 13, 14, 15, 16, 17, 18, 20}:
        rows = db.query(Pharmaceutical).filter(Pharmaceutical.status == 0).order_by(Pharmaceutical.pharmaceutical_id).limit(200).all()
        tools["hospital_drug_catalog"] = [
            {"drug_id": item.pharmaceutical_id, "name": item.name, "stock": item.stock, "expiry_date": item.expireddate, "antibiotic_level": item.antibiotic_level} for item in rows
        ]
    if spec.number in {13, 14, 15, 17} and patient_id:
        from app.models import Patient
        from app.rx_review_engine import build_patient_context, check_prescription

        patient = db.get(Patient, patient_id)
        prescription_id = task_input.get("prescription_id")
        if prescription_id:
            prescription = db.query(Prescription).filter_by(prescription_id=str(prescription_id), patient_id=patient_id).first()
            if not prescription:
                raise HTTPException(404, "处方不存在或不属于该患者")
            items = [{"name": pp.pharmaceutical.name, "number": pp.number} for pp in prescription.pre_phas if pp.pharmaceutical]
            findings = check_prescription(db, items, patient.allergy_history, build_patient_context(db, patient))
            tools["prescription_review"] = {
                "findings": findings,
                "blocked": any(item["severity"] == 3 for item in findings),
                "dose_check_status": "not_evaluated_without_complete_units_and_dose_rules",
            }
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
