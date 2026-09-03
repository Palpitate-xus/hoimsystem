"""审方规则引擎 API：规则 CRUD + 开方前预检。"""
import datetime
import json
import math

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import ADMIN_ROLES, CLINICAL_ROLES, PHARMACY_ROLES, User, require_roles
from app.models import Patient, PatientClinicalProfile, PrescriptionReviewRule
from app.rx_review_engine import build_patient_context, check_prescription, has_blocking

router = APIRouter()

RULE_TYPES = {"interaction", "contraindication", "dose", "duplicate", "allergy_key", "context"}
CONDITION_KEYS = {
    "min_age", "max_age", "min_weight", "max_weight", "min_egfr", "max_egfr",
    "pregnant", "sex", "hepatic_min", "diagnosis_keywords", "labs",
}


def _condition_json(value) -> str | None:
    if value in (None, "", {}):
        return None
    condition = json.loads(value) if isinstance(value, str) else value
    if not isinstance(condition, dict) or not condition or set(condition) - CONDITION_KEYS:
        raise ValueError("患者条件包含不支持的字段或为空")
    numeric_keys = {"min_age", "max_age", "min_weight", "max_weight", "min_egfr", "max_egfr", "hepatic_min"}
    for key in numeric_keys & set(condition):
        number = float(condition[key])
        if not math.isfinite(number):
            raise ValueError(f"{key} 必须是有限数值")
        condition[key] = number
    if "pregnant" in condition and not isinstance(condition["pregnant"], bool):
        raise ValueError("pregnant 必须是布尔值")
    if "sex" in condition and condition["sex"] not in (0, 1):
        raise ValueError("sex 必须是0或1")
    if "diagnosis_keywords" in condition:
        values = condition["diagnosis_keywords"]
        if not isinstance(values, list) or not values or len(values) > 100:
            raise ValueError("diagnosis_keywords 必须是非空字符串数组")
        condition["diagnosis_keywords"] = [str(item).strip()[:200] for item in values if str(item).strip()]
    if "labs" in condition:
        if not isinstance(condition["labs"], dict) or len(condition["labs"]) > 100:
            raise ValueError("labs 必须是检验名到上下限的对象")
        for name, bounds in condition["labs"].items():
            if not isinstance(bounds, dict) or not bounds or set(bounds) - {"min", "max"}:
                raise ValueError(f"检验条件 {name} 只能包含 min/max")
            for bound, raw in bounds.items():
                number = float(raw)
                if not math.isfinite(number):
                    raise ValueError(f"检验条件 {name}.{bound} 必须是有限数值")
                bounds[bound] = number
    return json.dumps(condition, ensure_ascii=False, separators=(",", ":"))


def _optional_date(value):
    if value in (None, ""):
        return None
    if isinstance(value, datetime.date):
        return value
    return datetime.date.fromisoformat(str(value))


def _serialize(r: PrescriptionReviewRule) -> dict:
    return {
        "rule_id": r.rule_id,
        "rule_type": r.rule_type,
        "rule_type_text": {"interaction": "配伍禁忌", "contraindication": "禁忌", "dose": "剂量范围", "duplicate": "重复用药", "allergy_key": "过敏关键词", "context": "患者条件"}.get(r.rule_type, r.rule_type),
        "drug_a": r.drug_a or "",
        "drug_b": r.drug_b or "",
        "min_dose": float(r.min_dose) if r.min_dose is not None else None,
        "max_dose": float(r.max_dose) if r.max_dose is not None else None,
        "max_daily_dose": float(r.max_daily_dose) if r.max_daily_dose is not None else None,
        "condition": json.loads(r.condition_json) if r.condition_json else None,
        "source": r.source or "",
        "version": r.version or "",
        "effective_from": r.effective_from,
        "effective_to": r.effective_to,
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
    if rule_type == "context" and not (req.get("drug_a") or "").strip():
        return {"code": 400, "msg": "患者条件规则必须填写药品关键词"}
    try:
        condition_json = _condition_json(req.get("condition"))
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        return {"code": 400, "msg": f"患者条件格式错误：{exc}"}
    if rule_type == "context" and not condition_json:
        return {"code": 400, "msg": "患者条件规则必须配置至少一个条件"}
    try:
        effective_from = _optional_date(req.get("effective_from"))
        effective_to = _optional_date(req.get("effective_to"))
    except ValueError:
        return {"code": 400, "msg": "生效期必须为 YYYY-MM-DD 日期"}
    if effective_from and effective_to and effective_from > effective_to:
        return {"code": 400, "msg": "规则失效日期不能早于生效日期"}
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
        condition_json=condition_json,
        source=(req.get("source") or "").strip()[:100] or None,
        version=(req.get("version") or "").strip()[:30] or None,
        effective_from=effective_from,
        effective_to=effective_to,
        severity=severity,
        message=(req.get("message") or "").strip(),
        status=1,
        create_time=datetime.datetime.now(),
        update_time=datetime.datetime.now(),
        updated_by=current_user.user_id,
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
    if "condition" in req:
        try:
            rule.condition_json = _condition_json(req.get("condition"))
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            return {"code": 400, "msg": f"患者条件格式错误：{exc}"}
    for field in ("source", "version"):
        if field in req:
            setattr(rule, field, req.get(field) or None)
    for field in ("effective_from", "effective_to"):
        if field in req:
            try:
                setattr(rule, field, _optional_date(req.get(field)))
            except ValueError:
                return {"code": 400, "msg": f"{field} 必须为 YYYY-MM-DD 日期"}
    if req.get("severity") in (1, 2, 3):
        rule.severity = int(req["severity"])
    if req.get("status") in (0, 1):
        rule.status = int(req["status"])
    rule.update_time = datetime.datetime.now()
    rule.updated_by = current_user.user_id
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
    context = None
    if req.get("patient_id"):
        patient = db.query(Patient).filter(Patient.patient_id == req["patient_id"]).first()
        allergy_history = patient.allergy_history if patient else None
        context = build_patient_context(db, patient) if patient else None
    findings = check_prescription(db, items, allergy_history, context)
    return {
        "code": 200,
        "msg": "success",
        "data": {"findings": findings, "blocked": has_blocking(findings)},
    }


@router.get("/clinicalProfile/{patient_id}")
def get_clinical_profile(
    patient_id: int,
    current_user: User = Depends(require_roles(*{*PHARMACY_ROLES, *ADMIN_ROLES, *CLINICAL_ROLES})),
    db: Session = Depends(get_db),
):
    patient = db.get(Patient, patient_id)
    if not patient:
        return {"code": 404, "msg": "患者不存在"}
    return {"code": 200, "msg": "success", "data": build_patient_context(db, patient)}


@router.post("/clinicalProfile/{patient_id}")
def save_clinical_profile(
    patient_id: int,
    req: dict,
    current_user: User = Depends(require_roles(*{*PHARMACY_ROLES, *ADMIN_ROLES, *CLINICAL_ROLES})),
    db: Session = Depends(get_db),
):
    if not db.get(Patient, patient_id):
        return {"code": 404, "msg": "患者不存在"}
    pregnant = req.get("pregnant")
    if pregnant not in (None, True, False, 0, 1):
        return {"code": 400, "msg": "妊娠状态不合法"}
    hepatic = req.get("hepatic_impairment", 0)
    if hepatic not in (0, 1, 2, 3):
        return {"code": 400, "msg": "肝功能损害等级必须为0至3"}
    diagnoses = req.get("diagnoses") or []
    labs = req.get("labs") or {}
    if not isinstance(diagnoses, list) or len(diagnoses) > 100 or not isinstance(labs, dict) or len(labs) > 100:
        return {"code": 400, "msg": "诊断或检验上下文格式不合法"}
    egfr = req.get("egfr")
    try:
        egfr = float(egfr) if egfr is not None else None
    except (TypeError, ValueError):
        return {"code": 400, "msg": "eGFR 必须是数值"}
    if egfr is not None and (not math.isfinite(egfr) or not 0 <= egfr <= 300):
        return {"code": 400, "msg": "eGFR 应在0至300之间"}
    normalized_labs = {}
    try:
        for name, value in labs.items():
            number = float(value)
            if not math.isfinite(number):
                raise ValueError
            normalized_labs[str(name)[:100]] = number
    except (TypeError, ValueError):
        return {"code": 400, "msg": "检验上下文必须使用有限数值"}
    profile = db.get(PatientClinicalProfile, patient_id) or PatientClinicalProfile(patient_id=patient_id)
    profile.pregnant = int(pregnant) if pregnant is not None else None
    profile.egfr = egfr
    profile.hepatic_impairment = hepatic
    profile.diagnoses_json = json.dumps([str(item)[:200] for item in diagnoses], ensure_ascii=False)
    profile.labs_json = json.dumps(normalized_labs, ensure_ascii=False)
    profile.updated_by = current_user.user_id
    profile.update_time = datetime.datetime.now()
    db.add(profile)
    db.commit()
    return {"code": 200, "msg": "临床上下文已更新"}
