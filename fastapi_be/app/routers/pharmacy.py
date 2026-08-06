import datetime
import math
import traceback

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import PHARMACY_ROLES, User, require_roles
from app.models import Pharmaceutical, PrePha, Prescription
from app.pagination import paginate
from app.schemas import PharmacyAuditRequest, PharmacyDispenseRequest, PharmacyReturnRequest

router = APIRouter()


@router.get("/pharmacy/dispenseList")
def get_dispense_list(keyword: str | None = None, page: int | None = None, page_size: int | None = None, current_user: User = Depends(require_roles(*PHARMACY_ROLES)), db: Session = Depends(get_db)):
    query = db.query(Prescription).filter(Prescription.status.in_([0, 1, 2]))
    prescriptions, total = paginate(query, page, page_size)
    data = []
    for item in prescriptions:
        phas = []
        for j in item.pre_phas:
            phas.append(
                {
                    "name": j.pharmaceutical.name if j.pharmaceutical else "",
                    "number": j.number,
                    "pharmaceutical_id": j.pharmaceutical_id,
                }
            )
        data.append(
            {
                "uuid": str(item.prescription_id),
                "patient_name": item.patient.name if item.patient else "",
                "doctor_name": item.doctor.name if item.doctor else "",
                "phas": phas,
                "status": item.status,
                "create_time": (item.create_time.strftime("%Y-%m-%d %H:%M:%S") if item.create_time else None),
            }
        )
    if keyword:
        kw = keyword.lower()
        data = [item for item in data if any(kw in str(val).lower() for val in item.values())]
    result = {"code": 200, "msg": "success", "data": data}
    if page and page_size:
        result["total"] = total
    return result


@router.post("/pharmacy/audit")
def audit_prescription(req: PharmacyAuditRequest, current_user: User = Depends(require_roles(*PHARMACY_ROLES)), db: Session = Depends(get_db)):
    pre = db.query(Prescription).filter(Prescription.prescription_id == req.prescription_id).first()
    if not pre:
        return {"code": 500, "msg": "处方不存在"}
    if pre.status != 0:
        return {"code": 500, "msg": "处方状态不正确"}

    # Use a conditional update so two concurrent audit requests cannot both
    # observe status=0 and report success.
    updated = (
        db.query(Prescription)
        .filter(Prescription.prescription_id == req.prescription_id, Prescription.status == 0)
        .update({Prescription.status: 1}, synchronize_session=False)
    )
    if updated != 1:
        db.rollback()
        return {"code": 500, "msg": "处方状态不正确"}
    db.commit()
    return {"code": 200, "msg": "success"}


@router.post("/pharmacy/dispense")
def dispense_prescription(req: PharmacyDispenseRequest, current_user: User = Depends(require_roles(*PHARMACY_ROLES)), db: Session = Depends(get_db)):
    pre = db.query(Prescription).filter(Prescription.prescription_id == req.prescription_id).first()
    if not pre:
        return {"code": 500, "msg": "处方不存在"}
    if pre.status != 1:
        return {"code": 500, "msg": "处方未审核或已发药"}

    # Only the audited state may transition to dispensed.  Keeping the state
    # predicate in the UPDATE closes the duplicate-dispense race window.
    updated = (
        db.query(Prescription)
        .filter(Prescription.prescription_id == req.prescription_id, Prescription.status == 1)
        .update({Prescription.status: 2}, synchronize_session=False)
    )
    if updated != 1:
        db.rollback()
        return {"code": 500, "msg": "处方未审核或已发药"}
    db.commit()
    return {"code": 200, "msg": "success"}


@router.post("/pharmacy/return")
def return_medicine(req: PharmacyReturnRequest, current_user: User = Depends(require_roles(*PHARMACY_ROLES)), db: Session = Depends(get_db)):
    pre = db.query(Prescription).filter(Prescription.prescription_id == req.prescription_id).first()
    if not pre:
        return {"code": 500, "msg": "处方不存在"}
    if pre.status != 2:
        return {"code": 500, "msg": "处方未发药或已退药"}
    if req.number <= 0:
        return {"code": 500, "msg": "退药数量必须大于0"}

    pp = db.query(PrePha).filter(PrePha.prescription_id == req.prescription_id, PrePha.pharmaceutical_id == req.pha_id).first()
    if not pp:
        return {"code": 500, "msg": "药品记录不存在"}

    # Make the quantity check part of the update so concurrent return
    # requests cannot both consume the same remaining prescription quantity.
    updated = (
        db.query(PrePha)
        .filter(
            PrePha.prescription_id == req.prescription_id,
            PrePha.pharmaceutical_id == req.pha_id,
            PrePha.number >= req.number,
        )
        .update({PrePha.number: PrePha.number - req.number}, synchronize_session=False)
    )
    if updated != 1:
        db.rollback()
        return {"code": 500, "msg": "退药数量超过处方数量"}

    db.expire_all()
    pp = db.query(PrePha).filter(PrePha.prescription_id == req.prescription_id, PrePha.pharmaceutical_id == req.pha_id).first()
    if not pp:
        db.rollback()
        return {"code": 500, "msg": "药品记录不存在"}
    if pp.number <= 0:
        db.delete(pp)

    try:
        pha = db.query(Pharmaceutical).filter(Pharmaceutical.pharmaceutical_id == req.pha_id).first()
        if pha:
            pha.stock += req.number
            db.add(pha)

        # Status 4 is the documented fully-returned state.  Partial returns
        # keep status=2 so the remaining dispensed medicines can be returned.
        remaining = db.query(PrePha).filter(PrePha.prescription_id == req.prescription_id, PrePha.number > 0).count()
        if remaining == 0:
            pre.status = 4
            db.add(pre)

        db.commit()
        return {"code": 200, "msg": "success"}
    except Exception:
        db.rollback()
        traceback.print_exc()
        return {"code": 500, "msg": "退药失败"}


@router.post("/pharmacy/stockCheck")
def stock_check(req: dict, current_user: User = Depends(require_roles(*PHARMACY_ROLES)), db: Session = Depends(get_db)):
    """库存盘点：传入 {items: [{pharmaceutical_id, actual_stock}]}，返回盈亏"""
    items = req.get("items", [])
    if not isinstance(items, list):
        return {"code": 500, "msg": "盘点明细格式错误"}
    seen_ids = set()
    for item in items:
        pha_id = item.get("pharmaceutical_id") if isinstance(item, dict) else None
        actual = item.get("actual_stock") if isinstance(item, dict) else None
        if pha_id in seen_ids:
            return {"code": 500, "msg": "同一药品不能重复盘点"}
        seen_ids.add(pha_id)
        try:
            actual_value = float(actual)
        except (TypeError, ValueError, OverflowError):
            return {"code": 500, "msg": "实盘库存必须是非负整数"}
        if not math.isfinite(actual_value) or actual_value < 0 or not actual_value.is_integer():
            return {"code": 500, "msg": "实盘库存必须是非负整数"}
    result = []
    for item in items:
        pha_id = item.get("pharmaceutical_id")
        actual = int(item.get("actual_stock"))
        pha = db.query(Pharmaceutical).filter(Pharmaceutical.pharmaceutical_id == pha_id).first()
        if pha:
            diff = actual - pha.stock
            result.append(
                {
                    "pharmaceutical_id": pha_id,
                    "name": pha.name,
                    "system_stock": pha.stock,
                    "actual_stock": actual,
                    "diff": diff,
                }
            )
            # 以实盘数为准更新库存
            pha.stock = actual
            db.add(pha)
    db.commit()
    return {"code": 200, "msg": "success", "data": result}


@router.post("/pharmacy/review")
def review_prescription(req: dict, current_user: User = Depends(require_roles(*PHARMACY_ROLES)), db: Session = Depends(get_db)):
    """处方点评"""
    pre = db.query(Prescription).filter(Prescription.prescription_id == req.get("prescription_id")).first()
    if not pre:
        return {"code": 500, "msg": "处方不存在"}
    pre.review_score = req.get("score")
    pre.review_comment = req.get("comment", "")
    pre.review_time = datetime.datetime.now()
    db.add(pre)
    db.commit()
    return {"code": 200, "msg": "success"}


@router.get("/pharmacy/reviewList")
def get_review_list(keyword: str | None = None, current_user: User = Depends(require_roles(*PHARMACY_ROLES)), db: Session = Depends(get_db)):
    """已点评处方列表"""
    prescriptions = db.query(Prescription).filter(Prescription.review_score.isnot(None)).order_by(Prescription.review_time.desc()).all()
    data = []
    for item in prescriptions:
        phas = []
        for j in item.pre_phas:
            phas.append({"name": j.pharmaceutical.name if j.pharmaceutical else "", "number": j.number})
        data.append(
            {
                "uuid": str(item.prescription_id),
                "patient_name": item.patient.name if item.patient else "",
                "doctor_name": item.doctor.name if item.doctor else "",
                "phas": phas,
                "review_score": item.review_score,
                "review_comment": item.review_comment or "",
                "review_time": (item.review_time.strftime("%Y-%m-%d %H:%M:%S") if item.review_time else None) if item.review_time else "",
            }
        )
    if keyword:
        kw = keyword.lower()
        data = [item for item in data if any(kw in str(val).lower() for val in item.values())]
    return {"code": 200, "msg": "success", "data": data}
