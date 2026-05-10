import datetime
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import MdtCase
from app.dependencies import get_current_user

router = APIRouter()

@router.post("/mdt/create")
def create_mdt(req: dict, db: Session = Depends(get_db)):
    m = MdtCase(
        patient_id=req.get("patient_id"),
        diagnosis=req.get("diagnosis", ""),
        department_ids=req.get("department_ids", ""),
        status=0,
        create_time=datetime.datetime.now(),
    )
    db.add(m)
    db.commit()
    return {"code": 200, "msg": "success"}

@router.get("/mdt/getList")
def get_mdt_list(db: Session = Depends(get_db)):
    items = db.query(MdtCase).order_by(MdtCase.create_time.desc()).all()
    data = []
    for it in items:
        data.append({
            "mdt_id": it.mdt_id,
            "patient_name": it.patient.name if it.patient else "",
            "diagnosis": it.diagnosis,
            "department_ids": it.department_ids,
            "status": it.status,
            "status_text": {0: "待会诊", 1: "会诊中", 2: "已完成"}.get(it.status, ""),
            "result": it.result,
            "create_time": str(it.create_time) if it.create_time else "",
        })
    return {"code": 200, "msg": "success", "data": data}

@router.post("/mdt/update")
def update_mdt(req: dict, db: Session = Depends(get_db)):
    m = db.query(MdtCase).filter(MdtCase.mdt_id == req.get("mdt_id")).first()
    if not m:
        return {"code": 500, "msg": "记录不存在"}
    if "status" in req:
        m.status = req["status"]
    if "result" in req:
        m.result = req["result"]
    db.commit()
    return {"code": 200, "msg": "success"}
