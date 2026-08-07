import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import CLINICAL_ROLES, NURSING_ROLES, User, require_roles
from app.models import Doctor, InfusionObservation, InfusionOrder, Patient
from app.pharmacy_safety import get_usable_pharmaceutical
from app.schemas import InfusionCreateRequest, InfusionIdRequest, InfusionObservationRequest

router = APIRouter()


def _serialize(item: InfusionOrder):
    return {
        "id": item.infusion_id,
        "infusion_id": item.infusion_id,
        "patient_id": item.patient_id,
        "patient_name": item.patient.name if item.patient else "",
        "doctor_name": item.doctor.name if item.doctor else "",
        "nurse_name": item.nurse.username if item.nurse else "",
        "pharmaceutical_id": item.pharmaceutical_id,
        "pharmaceutical_name": item.pharmaceutical.name if item.pharmaceutical else "",
        "dose": item.dose,
        "batch_no": item.batch_no,
        "drip_rate": item.drip_rate,
        "status": item.status,
        "note": item.note or "",
        "create_time": item.create_time,
        "start_time": item.start_time,
        "end_time": item.end_time,
        "observations": [
            {
                "observation_id": row.observation_id,
                "drip_rate": row.drip_rate,
                "volume": row.volume,
                "condition": row.condition,
                "observe_time": row.observe_time,
                "nurse_name": row.nurse.username if row.nurse else "",
            }
            for row in item.observations
        ],
    }


@router.post("/infusion/create")
def create_infusion(req: InfusionCreateRequest, current_user: User = Depends(require_roles(*CLINICAL_ROLES)), db: Session = Depends(get_db)):
    doctor = db.query(Doctor).filter(Doctor.user_id == current_user.user_id).first()
    if not doctor:
        return {"code": 500, "msg": "医生信息不存在"}
    if not db.query(Patient).filter(Patient.patient_id == req.patient_id).first():
        return {"code": 500, "msg": "患者不存在"}
    pharmaceutical, medication_error = get_usable_pharmaceutical(db, req.pharmaceutical_id)
    if medication_error:
        return {"code": 500, "msg": medication_error}
    item = InfusionOrder(
        patient_id=req.patient_id,
        doctor_id=doctor.doctor_id,
        pharmaceutical_id=req.pharmaceutical_id,
        dose=req.dose.strip(),
        batch_no=req.batch_no.strip(),
        drip_rate=req.drip_rate,
        status=0,
        note=req.note.strip(),
        create_time=datetime.datetime.now(),
    )
    db.add(item)
    db.commit()
    return {"code": 200, "msg": "success", "data": _serialize(item)}


@router.get("/infusion/list")
def list_infusions(current_user: User = Depends(require_roles(*(CLINICAL_ROLES | NURSING_ROLES))), db: Session = Depends(get_db)):
    items = db.query(InfusionOrder).order_by(InfusionOrder.create_time.desc()).all()
    return {"code": 200, "msg": "success", "data": [_serialize(item) for item in items]}


@router.post("/infusion/execute")
def execute_infusion(req: InfusionIdRequest, current_user: User = Depends(require_roles(*NURSING_ROLES)), db: Session = Depends(get_db)):
    updated = (
        db.query(InfusionOrder)
        .filter(InfusionOrder.infusion_id == req.infusion_id, InfusionOrder.status == 0)
        .update({InfusionOrder.status: 1, InfusionOrder.nurse_id: current_user.user_id, InfusionOrder.start_time: datetime.datetime.now()}, synchronize_session=False)
    )
    if updated != 1:
        return {"code": 500, "msg": "输液医嘱状态不允许执行"}
    db.commit()
    return {"code": 200, "msg": "success"}


@router.post("/infusion/observe")
def observe_infusion(req: InfusionObservationRequest, current_user: User = Depends(require_roles(*NURSING_ROLES)), db: Session = Depends(get_db)):
    item = db.query(InfusionOrder).filter(InfusionOrder.infusion_id == req.infusion_id).first()
    if not item:
        return {"code": 404, "msg": "输液医嘱不存在"}
    if item.status != 1:
        return {"code": 500, "msg": "只有输液中的医嘱可以巡视"}
    db.add(
        InfusionObservation(
            infusion_id=item.infusion_id, nurse_id=current_user.user_id, drip_rate=req.drip_rate, volume=req.volume, condition=req.condition.strip(), observe_time=datetime.datetime.now()
        )
    )
    item.drip_rate = req.drip_rate
    db.commit()
    return {"code": 200, "msg": "success"}


@router.post("/infusion/complete")
def complete_infusion(req: InfusionIdRequest, current_user: User = Depends(require_roles(*NURSING_ROLES)), db: Session = Depends(get_db)):
    updated = (
        db.query(InfusionOrder)
        .filter(InfusionOrder.infusion_id == req.infusion_id, InfusionOrder.status == 1, InfusionOrder.nurse_id == current_user.user_id)
        .update({InfusionOrder.status: 2, InfusionOrder.end_time: datetime.datetime.now()}, synchronize_session=False)
    )
    if updated != 1:
        return {"code": 500, "msg": "只有执行该医嘱的护士可以结束输液"}
    db.commit()
    return {"code": 200, "msg": "success"}


@router.post("/infusion/cancel")
def cancel_infusion(req: InfusionIdRequest, current_user: User = Depends(require_roles(*CLINICAL_ROLES)), db: Session = Depends(get_db)):
    updated = (
        db.query(InfusionOrder)
        .filter(InfusionOrder.infusion_id == req.infusion_id, InfusionOrder.status == 0)
        .update({InfusionOrder.status: 3, InfusionOrder.end_time: datetime.datetime.now()}, synchronize_session=False)
    )
    if updated != 1:
        return {"code": 500, "msg": "只有未执行的输液医嘱可以取消"}
    db.commit()
    return {"code": 200, "msg": "success"}
