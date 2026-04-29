import datetime
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Prescription, PrePha, Pharmaceutical
from app.schemas import PharmacyAuditRequest, PharmacyDispenseRequest, PharmacyReturnRequest, PrescriptionCancelRequest

router = APIRouter()


@router.get("/pharmacy/dispenseList")
def get_dispense_list(db: Session = Depends(get_db)):
    prescriptions = db.query(Prescription).filter(Prescription.status.in_([0, 1])).all()
    data = []
    for item in prescriptions:
        phas = []
        for j in item.pre_phas:
            phas.append({
                "name": j.pharmaceutical.name if j.pharmaceutical else "",
                "number": j.number,
                "pharmaceutical_id": j.pharmaceutical_id,
            })
        data.append({
            "uuid": str(item.prescription_id),
            "patient_name": item.patient.name if item.patient else "",
            "doctor_name": item.doctor.name if item.doctor else "",
            "phas": phas,
            "status": item.status,
            "create_time": str(item.create_time),
        })
    return {"code": 200, "msg": "success", "data": data}


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
    pp = db.query(PrePha).filter(
        PrePha.prescription_id == req.prescription_id,
        PrePha.pharmaceutical_id == req.pha_id
    ).first()
    if not pp:
        return {"code": 500, "msg": "药品记录不存在"}
    pha = db.query(Pharmaceutical).filter(Pharmaceutical.pharmaceutical_id == req.pha_id).first()
    if pha:
        pha.stock += req.number
        db.add(pha)
    db.commit()
    return {"code": 200, "msg": "success"}
