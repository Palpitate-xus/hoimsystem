import datetime
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Referral
from app.dependencies import get_current_user

router = APIRouter()

@router.post("/referral/create")
def create_referral(req: dict, db: Session = Depends(get_db)):
    r = Referral(
        patient_id=req.get("patient_id"),
        from_department_id=req.get("from_department_id"),
        to_department_id=req.get("to_department_id"),
        referral_type=req.get("referral_type", "up"),
        reason=req.get("reason", ""),
        status=0,
        create_time=datetime.datetime.now(),
    )
    db.add(r)
    db.commit()
    return {"code": 200, "msg": "success"}

@router.get("/referral/getList")
def get_referral_list(db: Session = Depends(get_db)):
    items = db.query(Referral).order_by(Referral.create_time.desc()).all()
    data = []
    for it in items:
        data.append({
            "referral_id": it.referral_id,
            "patient_name": it.patient.name if it.patient else "",
            "from_department": it.from_department.name if it.from_department else "",
            "to_department": it.to_department.name if it.to_department else "",
            "referral_type": "上转" if it.referral_type == "up" else "下转",
            "reason": it.reason,
            "status": it.status,
            "status_text": {0: "待接收", 1: "已接收", 2: "已退回"}.get(it.status, ""),
            "create_time": str(it.create_time) if it.create_time else "",
        })
    return {"code": 200, "msg": "success", "data": data}

@router.post("/referral/updateStatus")
def update_referral_status(req: dict, db: Session = Depends(get_db)):
    r = db.query(Referral).filter(Referral.referral_id == req.get("referral_id")).first()
    if not r:
        return {"code": 500, "msg": "记录不存在"}
    r.status = req.get("status")
    db.commit()
    return {"code": 200, "msg": "success"}
