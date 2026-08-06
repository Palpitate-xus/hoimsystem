import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import ADMIN_ROLES, PHARMACY_ROLES, User, require_roles
from app.models import Patient, Pharmaceutical, SpecialDrugRegister
from app.schemas import SpecialDrugRegisterActionRequest, SpecialDrugRegisterCreateRequest

router = APIRouter()
VALID_ACTIONS = {"in", "out", "return", "destroy"}
ACTION_TEXT = {"in": "入库", "out": "发出", "return": "退回", "destroy": "销毁"}


def _serialize(item: SpecialDrugRegister):
    return {
        "id": item.register_id,
        "register_id": item.register_id,
        "pharmaceutical_id": item.pharmaceutical_id,
        "pharmaceutical_name": item.pharmaceutical.name if item.pharmaceutical else "",
        "patient_id": item.patient_id,
        "patient_name": item.patient.name if item.patient else "",
        "action": item.action,
        "action_text": ACTION_TEXT.get(item.action, item.action),
        "quantity": item.quantity,
        "reason": item.reason,
        "status": item.status,
        "status_text": {0: "待双人复核", 1: "已确认", 2: "已驳回"}.get(item.status, "未知"),
        "applicant_name": item.applicant.username if item.applicant else "",
        "checker_name": item.checker.username if item.checker else "",
        "create_time": item.create_time,
        "check_time": item.check_time,
    }


@router.post("/specialDrug/create")
def create_special_drug(req: SpecialDrugRegisterCreateRequest, current_user: User = Depends(require_roles(*PHARMACY_ROLES)), db: Session = Depends(get_db)):
    if req.action not in VALID_ACTIONS:
        return {"code": 500, "msg": "特殊药品操作类型不正确"}
    if not db.query(Pharmaceutical).filter(Pharmaceutical.pharmaceutical_id == req.pharmaceutical_id).first():
        return {"code": 500, "msg": "药品不存在"}
    if req.patient_id and not db.query(Patient).filter(Patient.patient_id == req.patient_id).first():
        return {"code": 500, "msg": "患者不存在"}
    item = SpecialDrugRegister(pharmaceutical_id=req.pharmaceutical_id, patient_id=req.patient_id, action=req.action, quantity=req.quantity, reason=req.reason.strip(), status=0, applicant_id=current_user.user_id, create_time=datetime.datetime.now())
    db.add(item)
    db.commit()
    return {"code": 200, "msg": "success", "data": _serialize(item)}


@router.get("/specialDrug/list")
def list_special_drugs(current_user: User = Depends(require_roles(*(PHARMACY_ROLES | ADMIN_ROLES))), db: Session = Depends(get_db)):
    items = db.query(SpecialDrugRegister).order_by(SpecialDrugRegister.create_time.desc()).all()
    return {"code": 200, "msg": "success", "data": [_serialize(item) for item in items]}


def _check_special_drug(register_id: str, current_user: User, db: Session, status: int):
    item = db.query(SpecialDrugRegister).filter(SpecialDrugRegister.register_id == register_id, SpecialDrugRegister.status == 0).first()
    if not item:
        return None, {"code": 500, "msg": "记录不存在或已处理"}
    if item.applicant_id == current_user.user_id:
        return None, {"code": 500, "msg": "申请人不能作为第二复核人"}
    item.status = status
    item.checker_id = current_user.user_id
    item.check_time = datetime.datetime.now()
    return item, None


@router.post("/specialDrug/approve")
def approve_special_drug(req: SpecialDrugRegisterActionRequest, current_user: User = Depends(require_roles(*ADMIN_ROLES)), db: Session = Depends(get_db)):
    item, error = _check_special_drug(req.register_id, current_user, db, 1)
    if error:
        return error
    drug = db.query(Pharmaceutical).filter(Pharmaceutical.pharmaceutical_id == item.pharmaceutical_id).first()
    delta = item.quantity if item.action in {"in", "return"} else -item.quantity
    if drug.stock + delta < 0:
        db.rollback()
        return {"code": 500, "msg": "库存不足，不能确认该操作"}
    drug.stock += delta
    db.commit()
    return {"code": 200, "msg": "success"}


@router.post("/specialDrug/reject")
def reject_special_drug(req: SpecialDrugRegisterActionRequest, current_user: User = Depends(require_roles(*ADMIN_ROLES)), db: Session = Depends(get_db)):
    item, error = _check_special_drug(req.register_id, current_user, db, 2)
    if error:
        return error
    db.commit()
    return {"code": 200, "msg": "success"}
