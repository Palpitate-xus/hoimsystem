"""审方规则引擎 API：规则 CRUD + 开方前预检。"""
import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import ADMIN_ROLES, CLINICAL_ROLES, PHARMACY_ROLES, User, require_roles
from app.models import Patient, PrescriptionReviewRule
from app.rx_review_engine import check_prescription, has_blocking

router = APIRouter()

RULE_TYPES = {"interaction", "contraindication", "dose", "duplicate", "allergy_key"}


def _serialize(r: PrescriptionReviewRule) -> dict:
    return {
        "rule_id": r.rule_id,
        "rule_type": r.rule_type,
        "rule_type_text": {"interaction": "配伍禁忌", "contraindication": "禁忌", "dose": "剂量范围", "duplicate": "重复用药", "allergy_key": "过敏关键词"}.get(r.rule_type, r.rule_type),
        "drug_a": r.drug_a or "",
        "drug_b": r.drug_b or "",
        "min_dose": float(r.min_dose) if r.min_dose is not None else None,
        "max_dose": float(r.max_dose) if r.max_dose is not None else None,
        "max_daily_dose": float(r.max_daily_dose) if r.max_daily_dose is not None else None,
        "severity": r.severity,
        "severity_text": {1: "提示", 2: "警告", 3: "禁止"}.get(r.severity, str(r.severity)),
        "message": r.message,
        "status": r.status,
        "create_time": r.create_time.strftime("%Y-%m-%d %H:%M:%S") if r.create_time else "",
    }


@router.get("/rxReviewRule/getList")
def list_rules(rule_type: str | None = None, status: int | None = None, current_user: User = Depends(require_roles(*{*PHARMACY_ROLES, *ADMIN_ROLES, *CLINICAL_ROLES})), db: Session = Depends(get_db)):
    query = db.query(PrescriptionReviewRule)
    if rule_type:
        query = query.filter(PrescriptionReviewRule.rule_type == rule_type)
    if status is not None:
        query = query.filter(PrescriptionReviewRule.status == status)
    rules = query.order_by(PrescriptionReviewRule.rule_id.desc()).all()
    return {"code": 200, "msg": "success", "data": [_serialize(r) for r in rules]}


@router.post("/rxReviewRule/create")
def create_rule(req: dict, current_user: User = Depends(require_roles(*{*PHARMACY_ROLES, *ADMIN_ROLES})), db: Session = Depends(get_db)):
    rule_type = (req.get("rule_type") or "").strip()
    if rule_type not in RULE_TYPES:
        return {"code": 400, "msg": f"规则类型必须为 {'/'.join(sorted(RULE_TYPES))}"}
    if not (req.get("message") or "").strip():
        return {"code": 400, "msg": "规则提示消息不能为空"}
    if rule_type in ("interaction", "duplicate", "allergy_key") and not (req.get("drug_a") or "").strip():
        return {"code": 400, "msg": "该规则类型必须填写药品关键词"}
    if rule_type == "interaction" and not (req.get("drug_b") or "").strip():
        return {"code": 400, "msg": "配伍禁忌必须填写第二个药品关键词"}
    if rule_type == "dose" and not (req.get("drug_a") or "").strip():
        return {"code": 400, "msg": "剂量规则必须填写药品关键词"}
    severity = int(req.get("severity", 1))
    if severity not in (1, 2, 3):
        return {"code": 400, "msg": "严重程度必须为 1提示/2警告/3禁止"}
    rule = PrescriptionReviewRule(
        rule_type=rule_type,
        drug_a=(req.get("drug_a") or "").strip() or None,
        drug_b=(req.get("drug_b") or "").strip() or None,
        min_dose=req.get("min_dose"),
        max_dose=req.get("max_dose"),
        max_daily_dose=req.get("max_daily_dose"),
        severity=severity,
        message=(req.get("message") or "").strip(),
        status=1,
        create_time=datetime.datetime.now(),
    )
    db.add(rule)
    db.commit()
    return {"code": 200, "msg": "success", "data": {"rule_id": rule.rule_id}}


@router.post("/rxReviewRule/update")
def update_rule(req: dict, current_user: User = Depends(require_roles(*{*PHARMACY_ROLES, *ADMIN_ROLES})), db: Session = Depends(get_db)):
    rule = db.query(PrescriptionReviewRule).filter(PrescriptionReviewRule.rule_id == req.get("rule_id")).first()
    if not rule:
        return {"code": 500, "msg": "规则不存在"}
    for field in ("drug_a", "drug_b", "message"):
        if req.get(field) is not None:
            setattr(rule, field, (req.get(field) or "").strip() or None)
    for field in ("min_dose", "max_dose", "max_daily_dose"):
        if req.get(field) is not None:
            setattr(rule, field, req.get(field))
    if req.get("severity") in (1, 2, 3):
        rule.severity = int(req["severity"])
    if req.get("status") in (0, 1):
        rule.status = int(req["status"])
    db.add(rule)
    db.commit()
    return {"code": 200, "msg": "success"}


@router.post("/rxReviewRule/delete")
def delete_rule(req: dict, current_user: User = Depends(require_roles(*{*PHARMACY_ROLES, *ADMIN_ROLES})), db: Session = Depends(get_db)):
    rule = db.query(PrescriptionReviewRule).filter(PrescriptionReviewRule.rule_id == req.get("rule_id")).first()
    if not rule:
        return {"code": 500, "msg": "规则不存在"}
    db.delete(rule)
    db.commit()
    return {"code": 200, "msg": "success"}


@router.post("/rxReviewRule/check")
def run_check(req: dict, current_user: User = Depends(require_roles(*{*PHARMACY_ROLES, *ADMIN_ROLES, *CLINICAL_ROLES})), db: Session = Depends(get_db)):
    """开方前预检：items=[{name, dosage, frequency, number}], patient_id 可选（带过敏史）。"""
    items = req.get("items") or []
    if not items:
        return {"code": 400, "msg": "处方明细不能为空"}
    allergy_history = None
    if req.get("patient_id"):
        patient = db.query(Patient).filter(Patient.patient_id == req["patient_id"]).first()
        allergy_history = patient.allergy_history if patient else None
    findings = check_prescription(db, items, allergy_history)
    return {
        "code": 200,
        "msg": "success",
        "data": {"findings": findings, "blocked": has_blocking(findings)},
    }
