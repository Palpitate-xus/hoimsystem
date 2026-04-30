import datetime
from fastapi import APIRouter, Depends
from typing import Optional
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import LabOrder, LabResult
from app.schemas import LabResultCreateRequest, LabResultAuditRequest
from app.dependencies import get_current_user

router = APIRouter()


@router.post("/labResult/create")
def create_lab_result(req: LabResultCreateRequest, current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    lab_order = db.query(LabOrder).filter(LabOrder.lab_order_id == req.lab_order_id).first()
    if not lab_order:
        return {"code": 500, "msg": "检查申请单不存在"}
    result = LabResult(
        lab_order_id=req.lab_order_id,
        sample_id=req.sample_id,
        result=req.result,
        abnormal_flag=req.abnormal_flag,
        technician_id=current_user.user_id,
        report_time=datetime.datetime.now(),
        audit_status=0,
    )
    db.add(result)
    lab_order.status = 1
    db.add(lab_order)
    db.commit()
    return {"code": 200, "msg": "success"}


@router.post("/labResult/audit")
def audit_lab_result(req: LabResultAuditRequest, db: Session = Depends(get_db)):
    result = db.query(LabResult).filter(LabResult.lab_result_id == req.lab_result_id).first()
    if not result:
        return {"code": 500, "msg": "检查结果不存在"}
    result.audit_status = 1
    if result.lab_order:
        result.lab_order.status = 2
        db.add(result.lab_order)
    db.add(result)
    db.commit()
    return {"code": 200, "msg": "success"}


@router.get("/labResult/getPending")
def get_pending_lab_orders(keyword: Optional[str] = None, db: Session = Depends(get_db)):
    orders = db.query(LabOrder).filter(LabOrder.status == 0).order_by(LabOrder.create_time.desc()).all()
    data = []
    for item in orders:
        data.append({
            "id": str(item.lab_order_id),
            "patient_name": item.patient.name if item.patient else "",
            "check_type": item.check_type,
            "status": item.status,
            "create_time": str(item.create_time),
        })
    if keyword:
        kw = keyword.lower()
        data = [item for item in data if any(kw in str(val).lower() for val in item.values())]
    return {"code": 200, "msg": "success", "data": data}


@router.get("/labResult/getList")
def get_lab_result_list(keyword: Optional[str] = None, db: Session = Depends(get_db)):
    results = db.query(LabResult).order_by(LabResult.report_time.desc()).all()
    data = []
    for item in results:
        data.append({
            "id": str(item.lab_result_id),
            "check_name": item.lab_order.check_type if item.lab_order else "",
            "check_time": str(item.report_time),
            "result": item.result,
            "abnormal_flag": item.abnormal_flag,
            "technician_name": item.technician.username if item.technician else "",
        })
    if keyword:
        kw = keyword.lower()
        data = [item for item in data if any(kw in str(val).lower() for val in item.values())]
    return {"code": 200, "msg": "success", "data": data}


@router.post("/labResult/detail")
def get_lab_result_detail(req: LabResultAuditRequest, db: Session = Depends(get_db)):
    result = db.query(LabResult).filter(LabResult.lab_result_id == req.lab_result_id).first()
    if not result:
        return {"code": 500, "msg": "检查结果不存在"}
    data = {
        "id": str(result.lab_result_id),
        "check_name": result.lab_order.check_type if result.lab_order else "",
        "check_time": str(result.report_time),
        "result": result.result,
        "abnormal_flag": result.abnormal_flag,
        "technician_name": result.technician.username if result.technician else "",
    }
    return {"code": 200, "msg": "success", "data": data}
