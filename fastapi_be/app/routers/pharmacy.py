import datetime
import traceback

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Pharmaceutical, PrePha, Prescription
from app.pagination import paginate
from app.schemas import PharmacyAuditRequest, PharmacyDispenseRequest, PharmacyReturnRequest

router = APIRouter()


@router.get("/pharmacy/dispenseList")
def get_dispense_list(keyword: str | None = None, page: int | None = None, page_size: int | None = None, db: Session = Depends(get_db)):
    query = db.query(Prescription).filter(Prescription.status.in_([0, 1]))
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
def audit_prescription(req: PharmacyAuditRequest, db: Session = Depends(get_db)):
    pre = db.query(Prescription).filter(Prescription.prescription_id == req.prescription_id).first()
    if not pre:
        return {"code": 500, "msg": "处方不存在"}
    if pre.status != 0:
        return {"code": 500, "msg": "处方状态不正确"}
    pre.status = 1
    db.add(pre)
    db.commit()
    return {"code": 200, "msg": "success"}


@router.post("/pharmacy/dispense")
def dispense_prescription(req: PharmacyDispenseRequest, db: Session = Depends(get_db)):
    pre = db.query(Prescription).filter(Prescription.prescription_id == req.prescription_id).first()
    if not pre:
        return {"code": 500, "msg": "处方不存在"}
    if pre.status != 1:
        return {"code": 500, "msg": "处方未审核或已发药"}
    pre.status = 2
    db.add(pre)
    db.commit()
    return {"code": 200, "msg": "success"}


@router.post("/pharmacy/return")
def return_medicine(req: PharmacyReturnRequest, db: Session = Depends(get_db)):
    pre = db.query(Prescription).filter(Prescription.prescription_id == req.prescription_id).first()
    if not pre:
        return {"code": 500, "msg": "处方不存在"}
    pp = db.query(PrePha).filter(PrePha.prescription_id == req.prescription_id, PrePha.pharmaceutical_id == req.pha_id).first()
    if not pp:
        return {"code": 500, "msg": "药品记录不存在"}
    if pp.number < req.number:
        return {"code": 500, "msg": "退药数量超过处方数量"}
    try:
        pha = db.query(Pharmaceutical).filter(Pharmaceutical.pharmaceutical_id == req.pha_id).first()
        if pha:
            pha.stock += req.number
            db.add(pha)
        pp.number -= req.number
        if pp.number <= 0:
            db.delete(pp)
        else:
            db.add(pp)
        db.commit()
        return {"code": 200, "msg": "success"}
    except Exception:
        db.rollback()
        traceback.print_exc()
        return {"code": 500, "msg": "退药失败"}


@router.post("/pharmacy/stockCheck")
def stock_check(req: dict, db: Session = Depends(get_db)):
    """库存盘点：传入 {items: [{pharmaceutical_id, actual_stock}]}，返回盈亏"""
    items = req.get("items", [])
    result = []
    for item in items:
        pha_id = item.get("pharmaceutical_id")
        actual = item.get("actual_stock")
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
def review_prescription(req: dict, db: Session = Depends(get_db)):
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
def get_review_list(keyword: str | None = None, db: Session = Depends(get_db)):
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
