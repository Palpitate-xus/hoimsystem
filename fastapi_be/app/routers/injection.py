import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import CLINICAL_ROLES, NURSING_ROLES, User, require_roles
from app.models import Doctor, InjectionOrder, Patient, Pharmaceutical
from app.schemas import InjectionCreateRequest, InjectionIdRequest

router = APIRouter()
VALID_ROUTES = {"im", "sc", "id"}


def _serialize(item: InjectionOrder):
    return {"id": item.injection_id, "injection_id": item.injection_id, "patient_id": item.patient_id, "patient_name": item.patient.name if item.patient else "", "doctor_name": item.doctor.name if item.doctor else "", "nurse_name": item.nurse.username if item.nurse else "", "pharmaceutical_id": item.pharmaceutical_id, "pharmaceutical_name": item.pharmaceutical.name if item.pharmaceutical else "", "route": item.route, "dose": item.dose, "status": item.status, "note": item.note or "", "create_time": item.create_time, "execute_time": item.execute_time, "complete_time": item.complete_time}


@router.post("/injection/create")
def create_injection(req: InjectionCreateRequest, current_user: User = Depends(require_roles(*CLINICAL_ROLES)), db: Session = Depends(get_db)):
    doctor = db.query(Doctor).filter(Doctor.user_id == current_user.user_id).first()
    if not doctor:
        return {"code": 500, "msg": "医生信息不存在"}
    if req.route not in VALID_ROUTES:
        return {"code": 500, "msg": "注射途径必须为肌注、皮下或皮内"}
    if not db.query(Patient).filter(Patient.patient_id == req.patient_id).first():
        return {"code": 500, "msg": "患者不存在"}
    if not db.query(Pharmaceutical).filter(Pharmaceutical.pharmaceutical_id == req.pharmaceutical_id).first():
        return {"code": 500, "msg": "药品不存在"}
    item = InjectionOrder(patient_id=req.patient_id, doctor_id=doctor.doctor_id, pharmaceutical_id=req.pharmaceutical_id, route=req.route, dose=req.dose.strip(), status=0, note=req.note.strip(), create_time=datetime.datetime.now())
    db.add(item)
    db.commit()
    return {"code": 200, "msg": "success", "data": _serialize(item)}


@router.get("/injection/list")
def list_injections(current_user: User = Depends(require_roles(*(CLINICAL_ROLES | NURSING_ROLES))), db: Session = Depends(get_db)):
    items = db.query(InjectionOrder).order_by(InjectionOrder.create_time.desc()).all()
    return {"code": 200, "msg": "success", "data": [_serialize(item) for item in items]}


@router.post("/injection/execute")
def execute_injection(req: InjectionIdRequest, current_user: User = Depends(require_roles(*NURSING_ROLES)), db: Session = Depends(get_db)):
    updated = db.query(InjectionOrder).filter(InjectionOrder.injection_id == req.injection_id, InjectionOrder.status == 0).update({InjectionOrder.status: 1, InjectionOrder.nurse_id: current_user.user_id, InjectionOrder.execute_time: datetime.datetime.now()}, synchronize_session=False)
    if updated != 1:
        return {"code": 500, "msg": "注射医嘱状态不允许执行"}
    db.commit()
    return {"code": 200, "msg": "success"}


@router.post("/injection/complete")
def complete_injection(req: InjectionIdRequest, current_user: User = Depends(require_roles(*NURSING_ROLES)), db: Session = Depends(get_db)):
    updated = db.query(InjectionOrder).filter(InjectionOrder.injection_id == req.injection_id, InjectionOrder.status == 1, InjectionOrder.nurse_id == current_user.user_id).update({InjectionOrder.status: 2, InjectionOrder.complete_time: datetime.datetime.now()}, synchronize_session=False)
    if updated != 1:
        return {"code": 500, "msg": "只有执行该医嘱的护士可以完成注射"}
    db.commit()
    return {"code": 200, "msg": "success"}


@router.post("/injection/cancel")
def cancel_injection(req: InjectionIdRequest, current_user: User = Depends(require_roles(*CLINICAL_ROLES)), db: Session = Depends(get_db)):
    updated = db.query(InjectionOrder).filter(InjectionOrder.injection_id == req.injection_id, InjectionOrder.status == 0).update({InjectionOrder.status: 3, InjectionOrder.complete_time: datetime.datetime.now()}, synchronize_session=False)
    if updated != 1:
        return {"code": 500, "msg": "只有未执行的注射医嘱可以取消"}
    db.commit()
    return {"code": 200, "msg": "success"}
