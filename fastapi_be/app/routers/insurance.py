import datetime
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import case, func
from sqlalchemy.orm import Session, joinedload

from app.config import settings
from app.database import get_db
from app.dependencies import ADMIN_ROLES, CASHIER_ROLES, CLINICAL_ROLES, ROLE_DIRECTOR, ROLE_PATIENT, User, get_current_user, require_roles
from app.integration_outbox import enqueue_integration_event
from app.models import (
    ChronicDiseaseRegistration,
    DrgGrouping,
    DrgRule,
    HomeIcdBinding,
    InsuranceCatalog,
    InsuranceSettlement,
    MedicalRecordHome,
    Patient,
)
from app.pagination import paginate
from app.routers.integration import _check_key
from app.schemas import InsuranceSettlementIntegrationRequest

router = APIRouter()
MANAGE_ROLES = {*ADMIN_ROLES, ROLE_DIRECTOR, *CASHIER_ROLES}


def _money(value) -> Decimal | None:
    try:
        parsed = Decimal(str(value)).quantize(Decimal("0.01"))
        return parsed if parsed.is_finite() and parsed >= 0 else None
    except (InvalidOperation, TypeError, ValueError):
        return None


def _date(value):
    if not value:
        return None
    return value if isinstance(value, datetime.date) else datetime.date.fromisoformat(str(value))


@router.get("/insurance/catalog/list")
def list_insurance_catalog(keyword: str | None = None, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    query = db.query(InsuranceCatalog).filter(InsuranceCatalog.status == 1)
    if keyword:
        query = query.filter((InsuranceCatalog.name.ilike(f"%{keyword}%")) | (InsuranceCatalog.code.ilike(f"%{keyword}%")))
    return {"code": 200, "msg": "success", "data": [{"catalog_id": item.catalog_id, "code": item.code, "name": item.name, "category": item.category or "", "reimbursement_ratio": item.reimbursement_ratio} for item in query.order_by(InsuranceCatalog.name).all()]}


@router.post("/insurance/catalog/save")
def save_insurance_catalog(req: dict, current_user: User = Depends(require_roles(*MANAGE_ROLES)), db: Session = Depends(get_db)):
    item = db.query(InsuranceCatalog).filter(InsuranceCatalog.catalog_id == req.get("catalog_id")).first() if req.get("catalog_id") else None
    if not item:
        if not req.get("code") or not req.get("name"):
            return {"code": 400, "msg": "医保编码和名称不能为空"}
        item = InsuranceCatalog(code=req["code"], name=req["name"], category=req.get("category"), reimbursement_ratio=float(req.get("reimbursement_ratio", 0)), update_time=datetime.datetime.now())
        db.add(item)
    else:
        item.name = req.get("name", item.name)
        item.category = req.get("category", item.category)
        item.reimbursement_ratio = float(req.get("reimbursement_ratio", item.reimbursement_ratio))
        item.update_time = datetime.datetime.now()
    db.commit()
    return {"code": 200, "msg": "success"}


@router.get("/insurance/settlement/list")
def list_insurance_settlement(current_user: User = Depends(require_roles(*MANAGE_ROLES)), db: Session = Depends(get_db)):
    items = db.query(InsuranceSettlement).order_by(InsuranceSettlement.settlement_time.desc()).all()
    return {"code": 200, "msg": "success", "data": [{
        "settlement_id": item.settlement_id,
        "patient_name": item.patient.name if item.patient else "",
        "insurance_no": item.insurance_no,
        "total_amount": item.total_amount,
        "covered_amount": item.covered_amount,
        "self_amount": item.self_amount,
        "status": item.status,
        "status_text": {0: "处理中", 1: "成功", 2: "失败"}.get(item.status, ""),
        "integration_status": item.integration_status or "local",
        "external_settlement_id": item.external_settlement_id or "",
        "settlement_time": item.settlement_time.strftime("%Y-%m-%d %H:%M:%S"),
    } for item in items]}


@router.post("/insurance/settlement/create")
def create_insurance_settlement(req: dict, current_user: User = Depends(require_roles(*CASHIER_ROLES)), db: Session = Depends(get_db)):
    patient = db.query(Patient).filter(Patient.patient_id == req.get("patient_id")).first()
    if not patient or not req.get("insurance_no"):
        return {"code": 400, "msg": "患者和医保号不能为空"}
    total = float(req.get("total_amount", 0))
    covered = float(req.get("covered_amount", 0))
    if total <= 0 or covered < 0 or covered > total:
        return {"code": 400, "msg": "结算金额不合法"}
    integration_mode = req.get("integration_mode", "local")
    if integration_mode not in ("local", "external"):
        return {"code": 400, "msg": "结算模式不合法"}
    item = InsuranceSettlement(
        patient_id=patient.patient_id, insurance_no=req["insurance_no"], total_amount=total,
        covered_amount=covered, self_amount=round(total - covered, 2),
        status=0 if integration_mode == "external" else 1,
        integration_status="pending" if integration_mode == "external" else "local",
        operator_id=current_user.user_id, settlement_time=datetime.datetime.now(),
    )
    db.add(item)
    db.flush()
    if integration_mode == "external":
        enqueue_integration_event(
            db,
            destination="insurance",
            event_type="insurance.settlement.created",
            aggregate_type="insurance_settlement",
            aggregate_id=item.settlement_id,
            payload={
                "settlement_id": item.settlement_id,
                "patient_id": item.patient_id,
                "insurance_no": item.insurance_no,
                "total_amount": item.total_amount,
                "covered_amount": item.covered_amount,
                "self_amount": item.self_amount,
                "settlement_time": item.settlement_time,
            },
        )
    db.commit()
    return {"code": 200, "msg": "已提交医保平台" if integration_mode == "external" else "结算成功", "data": {"settlement_id": item.settlement_id, "self_amount": item.self_amount, "status": item.status}}


@router.post("/integration/insurance/settlement")
def receive_insurance_settlement(
    req: InsuranceSettlementIntegrationRequest,
    x_integration_key: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    """接收医保平台结算结果；外部结果只更新待处理结算，不绕过本地收费权限。"""
    _check_key(x_integration_key, settings.MEDICAL_INSURANCE_INTEGRATION_KEY, "医保")
    item = db.query(InsuranceSettlement).filter(InsuranceSettlement.settlement_id == req.settlement_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="医保结算记录不存在")
    if req.external_settlement_id:
        external_id = req.external_settlement_id.strip()
        if item.external_settlement_id and item.external_settlement_id != external_id:
            raise HTTPException(status_code=409, detail="外部结算号与本地记录绑定不一致")
        item.external_settlement_id = external_id
    if item.integration_status == "synced":
        return {"code": 200, "msg": "医保结果已同步，重复回调已忽略", "data": {"settlement_id": item.settlement_id, "idempotent": True}}
    if req.covered_amount > req.total_amount:
        raise HTTPException(status_code=400, detail="医保报销金额不能超过总金额")
    expected_self = round(req.total_amount - req.covered_amount, 2)
    if req.self_amount is not None and round(req.self_amount, 2) != expected_self:
        raise HTTPException(status_code=400, detail="医保自付金额与总金额不一致")
    item.total_amount = req.total_amount
    item.covered_amount = req.covered_amount
    item.self_amount = expected_self
    item.status = req.status
    item.integration_status = "synced"
    item.last_sync_time = datetime.datetime.now()
    db.commit()
    return {"code": 200, "msg": "医保结算结果已同步", "data": {"settlement_id": item.settlement_id, "idempotent": False, "status": item.status}}


@router.get("/insurance/chronic/list")
def list_chronic(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    query = db.query(ChronicDiseaseRegistration)
    if current_user.user_role == ROLE_PATIENT:
        patient = db.query(Patient).filter(Patient.identity == current_user.username).first()
        query = query.filter(ChronicDiseaseRegistration.patient_id == patient.patient_id if patient else -1)
    items = query.order_by(ChronicDiseaseRegistration.create_time.desc()).all()
    return {"code": 200, "msg": "success", "data": [{"registration_id": item.registration_id, "patient_name": item.patient.name if item.patient else "", "disease_name": item.disease_name, "card_no": item.card_no or "", "limit_amount": item.limit_amount, "status": item.status, "create_time": item.create_time.strftime("%Y-%m-%d %H:%M:%S")} for item in items]}


@router.post("/insurance/chronic/create")
def create_chronic(req: dict, current_user: User = Depends(require_roles(*CLINICAL_ROLES)), db: Session = Depends(get_db)):
    if not req.get("patient_id") or not req.get("disease_name"):
        return {"code": 400, "msg": "患者和慢病名称不能为空"}
    item = ChronicDiseaseRegistration(patient_id=req["patient_id"], disease_name=req["disease_name"], card_no=req.get("card_no"), limit_amount=req.get("limit_amount"), doctor_id=None, create_time=datetime.datetime.now())
    db.add(item)
    db.commit()
    return {"code": 200, "msg": "success"}


@router.post("/insurance/drg/group")
def create_drg_group(req: dict, current_user: User = Depends(require_roles(*MANAGE_ROLES)), db: Session = Depends(get_db)):
    patient = db.query(Patient).filter(Patient.patient_id == req.get("patient_id")).first()
    if not patient or not req.get("group_code") or not req.get("diagnosis"):
        return {"code": 400, "msg": "患者、分组编码和诊断不能为空"}
    expected = float(req.get("expected_amount", 0))
    actual = float(req.get("actual_amount", 0))
    item = DrgGrouping(patient_id=patient.patient_id, group_code=req["group_code"], diagnosis=req["diagnosis"], expected_amount=expected, actual_amount=actual, profit=round(expected - actual, 2), create_time=datetime.datetime.now())
    db.add(item)
    db.commit()
    return {"code": 200, "msg": "success", "data": {"grouping_id": item.grouping_id, "profit": item.profit}}


@router.post("/insurance/drg/rule")
def save_drg_rule(req: dict, current_user: User = Depends(require_roles(*ADMIN_ROLES, ROLE_DIRECTOR)), db: Session = Depends(get_db)):
    method = str(req.get("payment_method") or "DRG").upper()
    if method not in ("DRG", "DIP"):
        return {"code": 400, "msg": "支付方式必须为 DRG 或 DIP"}
    expected = _money(req.get("expected_amount"))
    diagnosis_prefix = str(req.get("diagnosis_prefix") or "").strip().upper()
    if not all((req.get("group_code"), req.get("group_name"), diagnosis_prefix, req.get("version"))) or expected is None:
        return {"code": 400, "msg": "组编码、名称、诊断前缀、版本和标准支付额不能为空"}
    try:
        effective_from = _date(req.get("effective_from"))
        effective_to = _date(req.get("effective_to"))
    except ValueError:
        return {"code": 400, "msg": "规则生效期必须为 YYYY-MM-DD"}
    if effective_from and effective_to and effective_from > effective_to:
        return {"code": 400, "msg": "失效日期不能早于生效日期"}
    rule = db.get(DrgRule, req.get("rule_id")) if req.get("rule_id") else DrgRule(
        creator_id=current_user.user_id,
        create_time=datetime.datetime.now(),
    )
    if not rule:
        return {"code": 404, "msg": "分组规则不存在"}
    rule.payment_method = method
    rule.group_code = str(req["group_code"]).strip().upper()[:30]
    rule.group_name = str(req["group_name"]).strip()[:200]
    rule.diagnosis_prefix = diagnosis_prefix[:20]
    rule.procedure_prefix = str(req.get("procedure_prefix") or "").strip().upper()[:20] or None
    rule.expected_amount = expected
    rule.priority = max(-1000, min(int(req.get("priority", 0)), 1000))
    rule.version = str(req["version"]).strip()[:30]
    rule.effective_from = effective_from
    rule.effective_to = effective_to
    rule.status = int(req.get("status", 1))
    rule.update_time = datetime.datetime.now()
    db.add(rule)
    db.commit()
    return {"code": 200, "msg": "success", "data": {"rule_id": rule.rule_id}}


@router.get("/insurance/drg/rules")
def list_drg_rules(
    payment_method: str | None = None,
    page: int = 1,
    page_size: int = 20,
    current_user: User = Depends(require_roles(*MANAGE_ROLES)),
    db: Session = Depends(get_db),
):
    query = db.query(DrgRule)
    if payment_method:
        query = query.filter(DrgRule.payment_method == payment_method.upper())
    rows, total = paginate(query.order_by(DrgRule.priority.desc(), DrgRule.rule_id.desc()), page, page_size)
    return {"code": 200, "msg": "success", "data": [{
        "rule_id": row.rule_id, "payment_method": row.payment_method, "group_code": row.group_code,
        "group_name": row.group_name, "diagnosis_prefix": row.diagnosis_prefix,
        "procedure_prefix": row.procedure_prefix or "", "expected_amount": row.expected_amount,
        "priority": row.priority, "version": row.version, "effective_from": row.effective_from,
        "effective_to": row.effective_to, "status": row.status,
    } for row in rows], "total": total}


@router.post("/insurance/drg/autoGroup")
def automatic_drg_group(req: dict, current_user: User = Depends(require_roles(*MANAGE_ROLES)), db: Session = Depends(get_db)):
    home = db.query(MedicalRecordHome).options(joinedload(MedicalRecordHome.patient)).filter(
        MedicalRecordHome.home_id == req.get("home_id")
    ).first()
    if not home or home.status not in (1, 2):
        return {"code": 400, "msg": "仅已提交或已归档的病案首页可自动分组"}
    existing = db.query(DrgGrouping).filter(DrgGrouping.home_id == home.home_id).first()
    if existing and not req.get("force"):
        return {"code": 200, "msg": "该病案已完成分组", "data": {"grouping_id": existing.grouping_id, "group_code": existing.group_code, "idempotent": True}}
    bindings = db.query(HomeIcdBinding).filter(HomeIcdBinding.home_id == home.home_id).all()
    diagnosis_codes = [row.icd_code.upper() for row in bindings if row.kind == "diagnosis"]
    procedure_codes = [row.icd_code.upper() for row in bindings if row.kind == "operation"]
    primary = next((row.icd_code.upper() for row in bindings if row.kind == "diagnosis" and row.is_primary == 1), None)
    if not primary:
        return {"code": 400, "msg": "病案首页尚未设置主要诊断 ICD 编码"}
    today = datetime.date.today()
    rules = db.query(DrgRule).filter(
        DrgRule.status == 1,
        (DrgRule.effective_from.is_(None)) | (DrgRule.effective_from <= today),
        (DrgRule.effective_to.is_(None)) | (DrgRule.effective_to >= today),
    ).all()
    matched = [rule for rule in rules if primary.startswith(rule.diagnosis_prefix.upper()) and (
        not rule.procedure_prefix or any(code.startswith(rule.procedure_prefix.upper()) for code in procedure_codes)
    )]
    if not matched:
        return {"code": 404, "msg": f"主要诊断 {primary} 未匹配到有效 DRG/DIP 规则"}
    rule = max(matched, key=lambda item: (item.priority, len(item.diagnosis_prefix), len(item.procedure_prefix or ""), item.rule_id))
    actual = _money(req.get("actual_amount", home.total_fee))
    if actual is None:
        return {"code": 400, "msg": "实际费用不合法"}
    grouping = existing or DrgGrouping(home_id=home.home_id, patient_id=home.patient_id)
    grouping.rule_id = rule.rule_id
    grouping.group_code = rule.group_code
    grouping.payment_method = rule.payment_method
    grouping.diagnosis = home.discharge_diagnosis or home.admission_diagnosis
    grouping.diagnosis_codes = ",".join(diagnosis_codes)
    grouping.procedure_codes = ",".join(procedure_codes)
    grouping.grouping_method = "automatic"
    grouping.expected_amount = rule.expected_amount
    grouping.actual_amount = actual
    grouping.profit = rule.expected_amount - actual
    grouping.create_time = datetime.datetime.now()
    db.add(grouping)
    db.commit()
    return {"code": 200, "msg": "自动分组完成", "data": {
        "grouping_id": grouping.grouping_id, "payment_method": grouping.payment_method,
        "group_code": grouping.group_code, "group_name": rule.group_name,
        "expected_amount": grouping.expected_amount, "actual_amount": grouping.actual_amount,
        "profit": grouping.profit, "rule_version": rule.version, "idempotent": False,
    }}


@router.get("/insurance/drg/analysis")
def drg_analysis(current_user: User = Depends(require_roles(*MANAGE_ROLES)), db: Session = Depends(get_db)):
    row = db.query(
        func.count(DrgGrouping.grouping_id),
        func.coalesce(func.sum(DrgGrouping.expected_amount), 0),
        func.coalesce(func.sum(DrgGrouping.actual_amount), 0),
        func.coalesce(func.sum(DrgGrouping.profit), 0),
        func.coalesce(func.sum(case((DrgGrouping.profit < 0, 1), else_=0)), 0),
    ).one()
    return {"code": 200, "msg": "success", "data": {"case_count": row[0], "expected_amount": row[1], "actual_amount": row[2], "profit": row[3], "loss_cases": row[4]}}


@router.get("/insurance/control/warnings")
def insurance_cost_warnings(threshold: float = 10000, current_user: User = Depends(require_roles(*MANAGE_ROLES)), db: Session = Depends(get_db)):
    rows = db.query(DrgGrouping).filter(DrgGrouping.actual_amount > threshold).order_by(DrgGrouping.actual_amount.desc()).all()
    return {"code": 200, "msg": "success", "data": [{"grouping_id": item.grouping_id, "patient_name": item.patient.name if item.patient else "", "group_code": item.group_code, "actual_amount": item.actual_amount, "expected_amount": item.expected_amount, "over_amount": round(item.actual_amount - item.expected_amount, 2)} for item in rows]}
